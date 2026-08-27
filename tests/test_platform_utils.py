# Copyright (C) 2021 The Android Open Source Project
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

"""Unittests for the platform_utils.py module."""

from pathlib import Path

import pytest

import platform_utils


def test_remove_missing_ok(tmp_path: Path) -> None:
    """Check missing_ok handling."""
    path = tmp_path / "test"

    # Should not fail.
    platform_utils.remove(path, missing_ok=True)

    # Should fail.
    with pytest.raises(OSError):
        platform_utils.remove(path)
    with pytest.raises(OSError):
        platform_utils.remove(path, missing_ok=False)

    # Should not fail if it exists.
    path.touch()
    platform_utils.remove(path, missing_ok=True)
    assert not path.exists()

    path.touch()
    platform_utils.remove(path)
    assert not path.exists()

    path.touch()
    platform_utils.remove(path, missing_ok=False)
    assert not path.exists()


def test_removedirs_nonexistent(tmp_path: Path) -> None:
    """removedirs should silently succeed on nonexistent paths."""
    platform_utils.removedirs(tmp_path / "does-not-exist")


def test_removedirs_symlink(tmp_path: Path) -> None:
    """removedirs should remove a symlink."""
    link = tmp_path / "link"
    link.symlink_to("target")
    platform_utils.removedirs(link)
    assert not link.exists()


def test_removedirs_empty_dir(tmp_path: Path) -> None:
    """removedirs should remove an empty directory."""
    d = tmp_path / "empty"
    d.mkdir()
    platform_utils.removedirs(d)
    assert not d.exists()


def test_removedirs_nested_empty_dirs(tmp_path: Path) -> None:
    """removedirs should remove nested empty directories."""
    d = tmp_path / "a" / "b" / "c"
    d.mkdir(parents=True)
    platform_utils.removedirs(tmp_path / "a")
    assert not (tmp_path / "a").exists()


def test_removedirs_symlinks_inside_dir(tmp_path: Path) -> None:
    """removedirs should remove symlinks inside a directory."""
    d = tmp_path / "dir"
    d.mkdir()
    (d / "link1").symlink_to("target1")
    (d / "link2").symlink_to("target2")
    platform_utils.removedirs(d)
    assert not d.exists()


def test_removedirs_preserves_user_files(tmp_path: Path) -> None:
    """removedirs should not delete regular files or their parent dirs."""
    d = tmp_path / "dir"
    d.mkdir()
    (d / "link").symlink_to("target")
    (d / "user-file.txt").write_text("keep me")
    platform_utils.removedirs(d)
    assert d.exists()
    assert not (d / "link").exists()
    assert (d / "user-file.txt").read_text() == "keep me"


def test_removedirs_deep_nested_with_symlinks(tmp_path: Path) -> None:
    """removedirs should handle deep nesting: sub/dir/target."""
    d = tmp_path / "sub" / "dir"
    d.mkdir(parents=True)
    (d / "link").symlink_to("target")
    platform_utils.removedirs(tmp_path / "sub")
    assert not (tmp_path / "sub").exists()


def test_removedirs_regular_file_noop(tmp_path: Path) -> None:
    """removedirs should not delete a regular file."""
    f = tmp_path / "file.txt"
    f.write_text("data")
    platform_utils.removedirs(f)
    assert f.exists()


@pytest.fixture(autouse=True)
def clean_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all agent-related environment variables before each test."""
    for var in (
        "GEMINI_CLI",
        "ANTIGRAVITY_AGENT",
        "INVOKER_INFO_NAME",
        "AGENT_INVOCATION",
        "REPO_AGENT_MODE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize(
    "env_var",
    (
        "GEMINI_CLI",
        "ANTIGRAVITY_AGENT",
        "AGENT_INVOCATION",
    ),
)
@pytest.mark.parametrize(
    "val, expected",
    (
        ("1", True),
        ("true", True),
        ("yes", True),
        ("TRUE", True),
        ("Yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("random", False),
    ),
)
def test_is_agentic_invocation_boolean_vars(
    monkeypatch: pytest.MonkeyPatch, env_var: str, val: str, expected: bool
) -> None:
    """Check boolean agent environment variables with truthy/falsy values."""
    monkeypatch.setenv(env_var, val)
    assert platform_utils.is_agentic_invocation() is expected


@pytest.mark.parametrize(
    "name, expected",
    (
        ("jetski", True),
        ("gemini_cli", True),
        ("gemini", True),
        ("Jetski", True),
        ("GEMINI_CLI", True),
        ("gcert", False),
        ("0", False),
        ("1", False),
        ("random_agent", False),
        ("", False),
    ),
)
def test_is_agentic_invocation_invoker_info_name(
    monkeypatch: pytest.MonkeyPatch, name: str, expected: bool
) -> None:
    """Check INVOKER_INFO_NAME against allowed agent identifiers."""
    monkeypatch.setenv("INVOKER_INFO_NAME", name)
    assert platform_utils.is_agentic_invocation() is expected


@pytest.mark.parametrize(
    "val, expected",
    (
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("TRUE", True),
        ("Yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("FALSE", False),
        ("Off", False),
    ),
)
def test_is_agentic_invocation_repo_agent_mode(
    monkeypatch: pytest.MonkeyPatch, val: str, expected: bool
) -> None:
    """Check REPO_AGENT_MODE truthy/falsy values."""
    monkeypatch.setenv("REPO_AGENT_MODE", val)
    assert platform_utils.is_agentic_invocation() is expected


def test_is_agentic_invocation_opt_out_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REPO_AGENT_MODE=0 should override other active agent variables."""
    monkeypatch.setenv("GEMINI_CLI", "1")
    monkeypatch.setenv("ANTIGRAVITY_AGENT", "1")
    monkeypatch.setenv("INVOKER_INFO_NAME", "jetski")
    monkeypatch.setenv("AGENT_INVOCATION", "1")
    monkeypatch.setenv("REPO_AGENT_MODE", "0")
    assert not platform_utils.is_agentic_invocation()


def test_is_agentic_invocation_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly verify required edge cases."""
    # GEMINI_CLI="0" -> False
    monkeypatch.setenv("GEMINI_CLI", "0")
    assert not platform_utils.is_agentic_invocation()
    monkeypatch.delenv("GEMINI_CLI")

    # ANTIGRAVITY_AGENT="false" -> False
    monkeypatch.setenv("ANTIGRAVITY_AGENT", "false")
    assert not platform_utils.is_agentic_invocation()
    monkeypatch.delenv("ANTIGRAVITY_AGENT")

    # INVOKER_INFO_NAME="gcert" -> False
    monkeypatch.setenv("INVOKER_INFO_NAME", "gcert")
    assert not platform_utils.is_agentic_invocation()
    monkeypatch.delenv("INVOKER_INFO_NAME")

    # INVOKER_INFO_NAME="jetski" -> True
    monkeypatch.setenv("INVOKER_INFO_NAME", "jetski")
    assert platform_utils.is_agentic_invocation()
    monkeypatch.delenv("INVOKER_INFO_NAME")

    # REPO_AGENT_MODE="0" with GEMINI_CLI="1" -> False (override check)
    monkeypatch.setenv("REPO_AGENT_MODE", "0")
    monkeypatch.setenv("GEMINI_CLI", "1")
    assert not platform_utils.is_agentic_invocation()
    monkeypatch.delenv("REPO_AGENT_MODE")
    monkeypatch.delenv("GEMINI_CLI")

    # AGENT_INVOCATION="1" -> True
    monkeypatch.setenv("AGENT_INVOCATION", "1")
    assert platform_utils.is_agentic_invocation()
    monkeypatch.delenv("AGENT_INVOCATION")
