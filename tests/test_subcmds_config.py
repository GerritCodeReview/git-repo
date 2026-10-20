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
from typing import Iterator, List
from unittest import mock

import pytest

import command
import error
import git_config
from subcmds import config


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["get"],
        ["get", "a.b", "c"],
        ["set"],
        ["set", "a.b"],
        ["set", "a.b", "c", "d"],
        ["unset"],
        ["unset", "a.b", "c"],
        ["list", "a.b"],
    ],
)
def test_validate_options_usage(argv: List[str]) -> None:
    """Wrong number of arguments for an action shows usage."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises(command.UsageError):
        cmd.ValidateOptions(opts, args)


@pytest.mark.parametrize(
    "argv",
    [
        ["bogus"],
        ["a.b", "c"],
        ["--type=bool", "unset", "a.b"],
        ["--type=bool", "list"],
        ["-z", "set", "a.b", "c"],
        ["-z", "unset", "a.b"],
    ],
)
def test_validate_options_error(argv: List[str]) -> None:
    """Unknown actions and inapplicable options are rejected."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opts, args)


def test_validate_options_unknown_type() -> None:
    """--type only accepts the supported types."""
    cmd = config.Config()
    with pytest.raises(SystemExit):
        cmd.OptionParser.parse_args(["--type=path", "get", "a.b"])


@pytest.mark.parametrize(
    "argv",
    [
        ["get", "sync.smartsync"],
        ["set", "sync.smartsync", "true"],
        ["unset", "sync.smartsync"],
        ["list"],
        ["--type=bool", "get", "sync.smartsync"],
        ["--type=int", "set", "a.b", "1"],
        ["-z", "get", "sync.smartsync"],
        ["--null", "list"],
    ],
)
def test_validate_options_accepts(argv: List[str]) -> None:
    """Valid invocations pass validation."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)


@pytest.fixture
def cfg(tmp_path: Path) -> Iterator[git_config.RepoConfig]:
    """A RepoConfig backed by a temp file, used as the per-user config."""
    cfg = git_config.RepoConfig(configfile=tmp_path / "config")
    with mock.patch.object(git_config.RepoConfig, "ForUser", return_value=cfg):
        yield cfg


def run(argv: List[str], capsys: pytest.CaptureFixture) -> str:
    """Runs `repo config` with |argv| and returns its stdout."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)
    capsys.readouterr()
    cmd.Execute(opts, args)
    return capsys.readouterr().out


def test_set_creates_file(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """Setting a value writes it to the config file."""
    run(["set", "sync.smartsync", "true"], capsys)
    assert "smartsync = true" in Path(cfg.file).read_text()
    assert cfg.GetBoolean("sync.smartsync") is True


def test_set_then_get(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """Getting a value prints what was set."""
    run(["set", "sync.smartsync", "false"], capsys)
    assert run(["get", "sync.smartsync"], capsys) == "false\n"


def test_set_overwrites(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """Setting an existing key replaces its value."""
    run(["set", "sync.smartsync", "true"], capsys)
    run(["set", "sync.smartsync", "false"], capsys)
    assert run(["get", "sync.smartsync"], capsys) == "false\n"
    assert Path(cfg.file).read_text().count("smartsync") == 1


def test_set_invalid_name(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """git's own validation of the name is surfaced as a clean error."""
    with pytest.raises(config.Error) as e:
        run(["set", "nodot", "true"], capsys)
    assert "nodot" in str(e.value)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("true", "true"),
        ("Yes", "true"),
        ("on", "true"),
        ("1", "true"),
        ("false", "false"),
        ("No", "false"),
        ("off", "false"),
        ("0", "false"),
    ],
)
def test_set_type_bool(
    cfg: git_config.RepoConfig,
    capsys: pytest.CaptureFixture,
    value: str,
    expected: str,
) -> None:
    """--type=bool canonicalizes accepted spellings on set."""
    run(["--type=bool", "set", "sync.smartsync", value], capsys)
    assert run(["get", "sync.smartsync"], capsys) == f"{expected}\n"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("42", "42"),
        ("1k", "1024"),
        ("2M", "2097152"),
        ("1g", "1073741824"),
        ("0x10", "16"),
    ],
)
def test_set_type_int(
    cfg: git_config.RepoConfig,
    capsys: pytest.CaptureFixture,
    value: str,
    expected: str,
) -> None:
    """--type=int canonicalizes accepted spellings on set."""
    run(["--type=int", "set", "section.num", value], capsys)
    assert run(["get", "section.num"], capsys) == f"{expected}\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["--type=bool", "set", "sync.smartsync", "maybe"],
        ["--type=bool", "set", "sync.smartsync", "2"],
        ["--type=int", "set", "section.num", "lots"],
        ["--type=int", "set", "section.num", "1x"],
        ["--type=int", "set", "section.num", ""],
    ],
)
def test_set_type_rejects_bad_values(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture, argv: List[str]
) -> None:
    """--type rejects values that do not parse and writes nothing."""
    with pytest.raises(config.Error):
        run(argv, capsys)
    assert not Path(cfg.file).exists()


def test_get_type_canonicalizes(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """--type on get prints the canonical form of a stored value."""
    Path(cfg.file).write_text("[a]\n\tb = Yes\n\tn = 1k\n")
    assert run(["--type=bool", "get", "a.b"], capsys) == "true\n"
    assert run(["--type=int", "get", "a.n"], capsys) == "1024\n"
    with pytest.raises(config.Error):
        run(["--type=int", "get", "a.b"], capsys)


def test_get_missing_exits_quietly(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """Reading an unset key exits 1 without output, like git config."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(["get", "sync.smartsync"])
    with pytest.raises(config.NotSetError) as e:
        cmd.Execute(opts, args)
    assert e.value.exit_code == 1
    assert capsys.readouterr().out == ""


def test_get_multiple_values(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """All values of a multi-valued key are printed."""
    cfg.SetString("section.multi", ["one", "two"])
    assert run(["get", "section.multi"], capsys) == "one\ntwo\n"


def test_get_valueless_key(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """A key present without a value prints an empty line, like git."""
    Path(cfg.file).write_text("[sync]\n\tsmartsync\n")
    assert run(["get", "sync.smartsync"], capsys) == "\n"


def test_get_null(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """-z terminates each value with NUL."""
    cfg.SetString("section.multi", ["one", "two"])
    assert run(["-z", "get", "section.multi"], capsys) == "one\0two\0"


def test_unset(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """unset removes the key."""
    run(["set", "sync.smartsync", "true"], capsys)
    run(["unset", "sync.smartsync"], capsys)
    assert cfg.GetString("sync.smartsync") is None
    assert "smartsync" not in Path(cfg.file).read_text()


def test_unset_missing_is_noop(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """unset on a missing key does not fail or create the file."""
    run(["unset", "sync.smartsync"], capsys)
    assert not Path(cfg.file).exists()


def test_list(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """list prints all keys sorted as key=value, with every value."""
    run(["set", "sync.smartsync", "true"], capsys)
    run(["set", "alias.ss", "sync -s"], capsys)
    cfg.SetString("section.multi", ["one", "two"])
    assert run(["list"], capsys) == (
        "alias.ss=sync -s\n"
        "section.multi=one\n"
        "section.multi=two\n"
        "sync.smartsync=true\n"
    )


def test_list_null(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """-z separates key and value with a newline and entries with NUL."""
    Path(cfg.file).write_text("[alias]\n\tss = sync -s\n[sync]\n\tsmartsync\n")
    assert run(["-z", "list"], capsys) == "alias.ss\nsync -s\0sync.smartsync\0"


def test_list_valueless_key(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """list prints a bare key for a key without a value, like git."""
    Path(cfg.file).write_text("[sync]\n\tsmartsync\n")
    assert run(["list"], capsys) == "sync.smartsync\n"


def test_list_empty(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """list on a missing file prints nothing."""
    assert run(["list"], capsys) == ""


def test_value_with_spaces(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """Values containing spaces round trip."""
    run(["set", "alias.ss", "sync -s -j 4"], capsys)
    assert run(["get", "alias.ss"], capsys) == "sync -s -j 4\n"


def test_key_is_case_insensitive(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """Section and name are case-insensitive, like git."""
    run(["set", "Sync.SmartSync", "true"], capsys)
    assert run(["get", "sync.smartsync"], capsys) == "true\n"


def test_write_failure_is_reported(
    cfg: git_config.RepoConfig, capsys: pytest.CaptureFixture
) -> None:
    """A git failure while writing becomes a clean error, not a traceback."""
    with mock.patch.object(
        cfg, "SetString", side_effect=error.GitError("locked")
    ):
        with pytest.raises(config.Error) as e:
            run(["set", "sync.smartsync", "true"], capsys)
    assert "locked" in str(e.value)
