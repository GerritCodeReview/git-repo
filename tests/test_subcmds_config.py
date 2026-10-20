# Copyright (C) 2026 The Android Open Source Project
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

"""Unittests for the subcmds/config.py module."""

from pathlib import Path
from typing import List
from unittest import mock

import pytest

from command import UsageError
from error import GitError
import git_config
from subcmds import config


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["a.b", "c", "d"],
    ],
)
def test_validate_options_usage(argv: List[str]) -> None:
    """Wrong number of positional arguments shows usage."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises(UsageError):
        cmd.ValidateOptions(opts, args)


@pytest.mark.parametrize(
    "argv",
    [
        ["--unset"],
        ["--unset", "a.b", "c"],
        ["--list", "a.b"],
        ["--list", "--unset", "a.b"],
        ["nodot"],
        ["nodot", "value"],
        ["1bad.name"],
        ["bad.1name"],
        ["bad name.x"],
    ],
)
def test_validate_options_error(argv: List[str]) -> None:
    """Invalid option combinations and names are rejected."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opts, args)


@pytest.mark.parametrize(
    "argv",
    [
        ["sync.smartsync"],
        ["sync.smartsync", "true"],
        ["--unset", "sync.smartsync"],
        ["--list"],
        ["-l"],
        ["alias.ss", "sync -s"],
        ["section.camelCase", "false"],
        ["section.sub.section.name"],
        ["section.with-dash.name-2", "x"],
    ],
)
def test_validate_options_accepts(argv: List[str]) -> None:
    """Valid argument combinations pass validation."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)


@pytest.fixture
def cfg(tmp_path: Path) -> git_config.RepoConfig:
    """A RepoConfig backed by a temp file, used as the per-user config."""
    cfg = git_config.RepoConfig(configfile=tmp_path / "config")
    with mock.patch.object(config.RepoConfig, "ForUser", return_value=cfg):
        yield cfg


def run(argv: List[str], capsys: pytest.CaptureFixture) -> str:
    """Runs `repo config` with |argv| and returns its stdout."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)
    capsys.readouterr()
    cmd.Execute(opts, args)
    return capsys.readouterr().out


def test_set_creates_file(cfg, capsys) -> None:
    """Setting a value writes it to the config file."""
    run(["sync.smartsync", "true"], capsys)
    assert "smartsync = true" in Path(cfg.file).read_text()
    assert cfg.GetBoolean("sync.smartsync") is True


def test_set_then_get(cfg, capsys) -> None:
    """Getting a value prints what was set."""
    run(["sync.smartsync", "false"], capsys)
    assert run(["sync.smartsync"], capsys) == "false\n"


def test_set_overwrites(cfg, capsys) -> None:
    """Setting an existing key replaces its value."""
    run(["sync.smartsync", "true"], capsys)
    run(["sync.smartsync", "false"], capsys)
    assert run(["sync.smartsync"], capsys) == "false\n"
    assert Path(cfg.file).read_text().count("smartsync") == 1


def test_get_missing_exits_quietly(cfg, capsys) -> None:
    """Reading an unset key exits 1 without output, like git config."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(["sync.smartsync"])
    with pytest.raises(config.NotSetError) as e:
        cmd.Execute(opts, args)
    assert e.value.exit_code == 1
    assert capsys.readouterr().out == ""


def test_get_multiple_values(cfg, capsys) -> None:
    """All values of a multi-valued key are printed."""
    cfg.SetString("section.multi", ["one", "two"])
    assert run(["section.multi"], capsys) == "one\ntwo\n"


def test_get_valueless_key(cfg, capsys) -> None:
    """A key present without a value prints an empty line, like git."""
    Path(cfg.file).write_text("[sync]\n\tsmartsync\n")
    assert run(["sync.smartsync"], capsys) == "\n"


def test_unset(cfg, capsys) -> None:
    """--unset removes the key."""
    run(["sync.smartsync", "true"], capsys)
    run(["--unset", "sync.smartsync"], capsys)
    assert cfg.GetString("sync.smartsync") is None
    assert "smartsync" not in Path(cfg.file).read_text()


def test_unset_missing_is_noop(cfg, capsys) -> None:
    """--unset on a missing key does not fail or create the file."""
    run(["--unset", "sync.smartsync"], capsys)
    assert not Path(cfg.file).exists()


def test_list(cfg, capsys) -> None:
    """--list prints all keys sorted as key=value, with every value."""
    run(["sync.smartsync", "true"], capsys)
    run(["alias.ss", "sync -s"], capsys)
    cfg.SetString("section.multi", ["one", "two"])
    assert run(["--list"], capsys) == (
        "alias.ss=sync -s\n"
        "section.multi=one\n"
        "section.multi=two\n"
        "sync.smartsync=true\n"
    )


def test_list_valueless_key(cfg, capsys) -> None:
    """--list prints a bare key for a key without a value, like git."""
    Path(cfg.file).write_text("[sync]\n\tsmartsync\n")
    assert run(["--list"], capsys) == "sync.smartsync\n"


def test_list_empty(cfg, capsys) -> None:
    """--list on a missing file prints nothing."""
    assert run(["--list"], capsys) == ""


def test_value_with_spaces(cfg, capsys) -> None:
    """Values containing spaces round trip."""
    run(["alias.ss", "sync -s -j 4"], capsys)
    assert run(["alias.ss"], capsys) == "sync -s -j 4\n"


def test_key_is_case_insensitive(cfg, capsys) -> None:
    """Section and name are case-insensitive, like git."""
    run(["Sync.SmartSync", "true"], capsys)
    assert run(["sync.smartsync"], capsys) == "true\n"


def test_write_failure_is_reported(cfg, capsys) -> None:
    """A git failure while writing becomes a clean error, not a traceback."""
    with mock.patch.object(cfg, "SetString", side_effect=GitError("locked")):
        with pytest.raises(config.Error) as e:
            run(["sync.smartsync", "true"], capsys)
    assert "locked" in str(e.value)
