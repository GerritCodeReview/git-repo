# Copyright (C) 2009 The Android Open Source Project
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

"""Unittests for the git_config.py module."""

import os
from pathlib import Path
from typing import Any

import pytest

import git_config


def fixture_path(*paths: str) -> str:
    """Return a path relative to test/fixtures."""
    return os.path.join(os.path.dirname(__file__), "fixtures", *paths)


@pytest.fixture
def readonly_config() -> git_config.GitConfig:
    """Create a GitConfig object using the test.gitconfig fixture."""
    config_fixture = fixture_path("test.gitconfig")
    return git_config.GitConfig(config_fixture)


def test_get_string_with_empty_config_values(
    readonly_config: git_config.GitConfig,
) -> None:
    """Test config entries with no value.

    [section]
        empty

    """
    val = readonly_config.GetString("section.empty")
    assert val is None


def test_get_string_with_true_value(
    readonly_config: git_config.GitConfig,
) -> None:
    """Test config entries with a string value.

    [section]
        nonempty = true

    """
    val = readonly_config.GetString("section.nonempty")
    assert val == "true"


def test_get_string_from_missing_file() -> None:
    """Test missing config file."""
    config_fixture = fixture_path("not.present.gitconfig")
    config = git_config.GitConfig(config_fixture)
    val = config.GetString("empty")
    assert val is None


def test_get_boolean_undefined(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on key that doesn't exist."""
    assert readonly_config.GetBoolean("section.missing") is None


def test_get_boolean_invalid(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on invalid boolean value."""
    assert readonly_config.GetBoolean("section.boolinvalid") is None


def test_get_boolean_true(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on valid true boolean."""
    assert readonly_config.GetBoolean("section.booltrue") is True


def test_get_boolean_false(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on valid false boolean."""
    assert readonly_config.GetBoolean("section.boolfalse") is False


def test_get_int_undefined(readonly_config: git_config.GitConfig) -> None:
    """Test GetInt on key that doesn't exist."""
    assert readonly_config.GetInt("section.missing") is None


def test_get_int_invalid(readonly_config: git_config.GitConfig) -> None:
    """Test GetInt on invalid integer value."""
    assert readonly_config.GetInt("section.intinvalid") is None


@pytest.mark.parametrize(
    "key, expected",
    (
        ("inthex", 16),
        ("inthexk", 16384),
        ("int", 10),
        ("intk", 10240),
        ("intm", 10485760),
        ("intg", 10737418240),
    ),
)
def test_get_int_valid(
    readonly_config: git_config.GitConfig, key: str, expected: int
) -> None:
    """Test GetInt on valid integers."""
    assert readonly_config.GetInt(f"section.{key}") == expected


@pytest.fixture
def rw_config_file(tmp_path: Path) -> Path:
    """Return a path to a temporary config file."""
    return tmp_path / "config"


def test_set_string(rw_config_file: Path) -> None:
    """Test SetString behavior."""
    config = git_config.GitConfig(str(rw_config_file))

    # Set a value.
    assert config.GetString("foo.bar") is None
    config.SetString("foo.bar", "val")
    assert config.GetString("foo.bar") == "val"

    # Make sure the value was actually written out.
    config2 = git_config.GitConfig(str(rw_config_file))
    assert config2.GetString("foo.bar") == "val"

    # Update the value.
    config.SetString("foo.bar", "valll")
    assert config.GetString("foo.bar") == "valll"
    config3 = git_config.GitConfig(str(rw_config_file))
    assert config3.GetString("foo.bar") == "valll"

    # Delete the value.
    config.SetString("foo.bar", None)
    assert config.GetString("foo.bar") is None
    config4 = git_config.GitConfig(str(rw_config_file))
    assert config4.GetString("foo.bar") is None


def test_set_boolean(rw_config_file: Path) -> None:
    """Test SetBoolean behavior."""
    config = git_config.GitConfig(str(rw_config_file))

    # Set a true value.
    assert config.GetBoolean("foo.bar") is None
    for val in (True, 1):
        config.SetBoolean("foo.bar", val)
        assert config.GetBoolean("foo.bar") is True

    # Make sure the value was actually written out.
    config2 = git_config.GitConfig(str(rw_config_file))
    assert config2.GetBoolean("foo.bar") is True
    assert config2.GetString("foo.bar") == "true"

    # Set a false value.
    for val in (False, 0):
        config.SetBoolean("foo.bar", val)
        assert config.GetBoolean("foo.bar") is False

    # Make sure the value was actually written out.
    config3 = git_config.GitConfig(str(rw_config_file))
    assert config3.GetBoolean("foo.bar") is False
    assert config3.GetString("foo.bar") == "false"

    # Delete the value.
    config.SetBoolean("foo.bar", None)
    assert config.GetBoolean("foo.bar") is None
    config4 = git_config.GitConfig(str(rw_config_file))
    assert config4.GetBoolean("foo.bar") is None


def test_set_int(rw_config_file: Path) -> None:
    """Test SetInt behavior."""
    config = git_config.GitConfig(str(rw_config_file))

    # Set a value.
    assert config.GetInt("foo.bar") is None
    config.SetInt("foo.bar", 10)
    assert config.GetInt("foo.bar") == 10

    # Make sure the value was actually written out.
    config2 = git_config.GitConfig(str(rw_config_file))
    assert config2.GetInt("foo.bar") == 10
    assert config2.GetString("foo.bar") == "10"

    # Update the value.
    config.SetInt("foo.bar", 20)
    assert config.GetInt("foo.bar") == 20
    config3 = git_config.GitConfig(str(rw_config_file))
    assert config3.GetInt("foo.bar") == 20

    # Delete the value.
    config.SetInt("foo.bar", None)
    assert config.GetInt("foo.bar") is None
    config4 = git_config.GitConfig(str(rw_config_file))
    assert config4.GetInt("foo.bar") is None


def test_get_sync_analysis_state_data(rw_config_file: Path) -> None:
    """Test config entries with a sync state analysis data."""
    config = git_config.GitConfig(str(rw_config_file))
    superproject_logging_data: dict[str, Any] = {"test": False}

    class Options:
        """Container for testing."""

    options = Options()
    options.verbose = "true"
    options.mp_update = "false"

    TESTS = (
        ("superproject.test", "false"),
        ("options.verbose", "true"),
        ("options.mpupdate", "false"),
        ("main.version", "1"),
    )
    config.UpdateSyncAnalysisState(options, superproject_logging_data)
    sync_data = config.GetSyncAnalysisStateData()
    for key, value in TESTS:
        assert sync_data[f"{git_config.SYNC_STATE_PREFIX}{key}"] == value
    assert sync_data[f"{git_config.SYNC_STATE_PREFIX}main.synctime"]
