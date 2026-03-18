# Copyright (C) 2020 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unittests for the subcmds module (mostly __init__.py than subcommands)."""

import optparse
from typing import Type

import pytest

from command import Command
import subcmds


# NB: We don't test all subcommands as we want to avoid "change detection"
# tests, so we just look for the most common/important ones here that are
# unlikely to ever change.
@pytest.mark.parametrize(
    "cmd", ("cherry-pick", "help", "init", "start", "sync", "upload")
)
def test_required_basic(cmd: str) -> None:
    """Basic checking of registered commands."""
    assert cmd in subcmds.all_commands


@pytest.mark.parametrize("name", subcmds.all_commands.keys())
def test_naming(name: str) -> None:
    """Verify we don't add things that we shouldn't."""
    # Reject filename suffixes like "help.py".
    assert "." not in name

    # Make sure all '_' were converted to '-'.
    assert "_" not in name

    # Reject internal python paths like "__init__".
    assert not name.startswith("__")


@pytest.mark.parametrize("name, cls", subcmds.all_commands.items())
def test_help_desc_style(name: str, cls: Type[Command]) -> None:
    """Force some consistency in option descriptions.

    Python's optparse & argparse has a few default options like --help.
    Their option description text uses lowercase sentence fragments, so
    enforce our options follow the same style so UI is consistent.

    We enforce:
    * Text starts with lowercase.
    * Text doesn't end with period.
    """
    cmd = cls()
    parser = cmd.OptionParser
    for option in parser.option_list:
        if option.help == optparse.SUPPRESS_HELP or not option.help:
            continue

        c = option.help[0]
        assert c.lower() == c, (
            f"subcmds/{name}.py: {option.get_opt_string()}: "
            f'help text should start with lowercase: "{option.help}"'
        )

        assert option.help[-1] != ".", (
            f"subcmds/{name}.py: {option.get_opt_string()}: "
            f'help text should not end in a period: "{option.help}"'
        )


@pytest.mark.parametrize("name, cls", subcmds.all_commands.items())
def test_cli_option_style(name: str, cls: Type[Command]) -> None:
    """Force some consistency in option flags."""
    cmd = cls()
    parser = cmd.OptionParser
    for option in parser.option_list:
        for opt in option._long_opts:
            assert "_" not in opt, (
                f"subcmds/{name}.py: {opt}: only use dashes in "
                "options, not underscores"
            )


def test_cli_option_dest() -> None:
    """Block redundant dest= arguments."""
    bad_opts: list[tuple[str, str]] = []

    def _check_dest(opt: optparse.Option) -> None:
        """Check the dest= setting."""
        # If the destination is not set, nothing to check.
        # If long options are not set, then there's no implicit destination.
        # If callback is used, then a destination might be needed because
        # optparse cannot assume a value is always stored.
        if opt.dest is None or not opt._long_opts or opt.callback:
            return

        long = opt._long_opts[0]
        assert long.startswith("--")
        # This matches optparse's behavior.
        implicit_dest = long[2:].replace("-", "_")
        if implicit_dest == opt.dest:
            bad_opts.append((str(opt), opt.dest))

    # Hook the option check list.
    optparse.Option.CHECK_METHODS.insert(0, _check_dest)

    try:
        # Gather all the bad options up front so people can see all bad options
        # instead of failing at the first one.
        all_bad_opts: dict[str, list[tuple[str, str]]] = {}
        for name, cls in subcmds.all_commands.items():
            bad_opts = []
            cmd = cls()
            # Trigger construction of parser.
            _ = cmd.OptionParser
            all_bad_opts[name] = bad_opts

        errmsg = ""
        for name, bad_opts_list in sorted(all_bad_opts.items()):
            if bad_opts_list:
                if not errmsg:
                    errmsg = "Omit redundant dest= when defining options.\n"
                errmsg += f"\nSubcommand {name} (subcmds/{name}.py):\n"
                errmsg += "".join(
                    f"    {opt}: dest='{dest}'\n" for opt, dest in bad_opts_list
                )
        if errmsg:
            pytest.fail(errmsg)
    finally:
        # Make sure we aren't popping the wrong stuff.
        assert optparse.Option.CHECK_METHODS.pop(0) is _check_dest


@pytest.mark.parametrize("name, cls", subcmds.all_commands.items())
def test_common_validate_options(name: str, cls: Type[Command]) -> None:
    """Verify CommonValidateOptions sets up expected fields."""
    cmd = cls()
    opts, args = cmd.OptionParser.parse_args([])

    # Verify the fields don't exist yet.
    assert not hasattr(
        opts, "verbose"
    ), f"{name}: has verbose before validation"
    assert not hasattr(opts, "quiet"), f"{name}: has quiet before validation"

    cmd.CommonValidateOptions(opts, args)

    # Verify the fields exist now.
    assert hasattr(opts, "verbose"), f"{name}: missing verbose after validation"
    assert hasattr(opts, "quiet"), f"{name}: missing quiet after validation"
    assert hasattr(
        opts, "outer_manifest"
    ), f"{name}: missing outer_manifest after validation"


def test_attribute_error_repro() -> None:
    """Confirm that accessing verbose before CommonValidateOptions fails."""
    from subcmds.sync import Sync

    cmd = Sync()
    opts, args = cmd.OptionParser.parse_args([])

    # This confirms that without the fix in main.py, an AttributeError
    # would be raised because CommonValidateOptions hasn't been called yet.
    with pytest.raises(AttributeError):
        _ = opts.verbose

    cmd.CommonValidateOptions(opts, args)
    assert hasattr(opts, "verbose")
