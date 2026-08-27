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

"""Unittests for the subcmds/init.py module."""

from typing import List

import pytest

from subcmds import init


@pytest.mark.parametrize(
    "argv",
    ([],),
)
def test_cli_parser_good(argv: List[str]) -> None:
    """Check valid command line options."""
    cmd = init.Init()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)


@pytest.mark.parametrize(
    "argv",
    (
        # Too many arguments.
        ["url", "asdf"],
        # Conflicting options.
        ["--mirror", "--archive"],
    ),
)
def test_cli_parser_bad(argv: List[str]) -> None:
    """Check invalid command line options."""
    cmd = init.Init()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opts, args)


def test_configure_user_agentic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that _ConfigureUser does not block in agentic environment."""
    from unittest import mock

    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    cmd = init.Init()
    cmd.manifest = mock.MagicMock()
    mp = mock.MagicMock()
    mp.UserName = "Agent Name"
    mp.UserEmail = "agent@example.com"
    cmd.manifest.manifestProject = mp

    opts, _ = cmd.OptionParser.parse_args([])
    with mock.patch("sys.stdin.readline") as mock_readline:
        cmd._ConfigureUser(opts)
        mock_readline.assert_not_called()


def test_configure_color_agentic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check that _ConfigureColor returns early in agentic environment."""
    from unittest import mock

    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    cmd = init.Init()
    cmd.client = mock.MagicMock()
    cmd._HasColorSet = mock.MagicMock(return_value=False)

    with mock.patch("builtins.print") as mock_print:
        cmd._ConfigureColor()
        mock_print.assert_not_called()
