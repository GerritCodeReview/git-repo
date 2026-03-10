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

"""Tests for the main repo script and subcommand routing."""

from unittest import mock

import pytest

from main import _Repo


@pytest.fixture(name="repo")
def fixture_repo():
    repo = _Repo("repodir")
    # Overriding the command list here ensures that we are only testing
    # against a fixed set of commands, reducing fragility to new
    # subcommands being added to the main repo tool.
    repo.commands = {"start": None, "sync": None}
    return repo


@pytest.fixture(name="mock_config")
def fixture_mock_config():
    return mock.MagicMock()


@mock.patch("time.sleep")
def test_autocorrect_delay(mock_sleep, repo, mock_config):
    """Test autocorrect with positive delay."""
    mock_config.GetString.return_value = "10"

    res = repo._autocorrect_command_name("tart", mock_config)

    mock_config.GetString.assert_called_with("help.autocorrect")
    mock_sleep.assert_called_with(1.0)
    assert res == "start"


@mock.patch("time.sleep")
def test_autocorrect_immediate(mock_sleep, repo, mock_config):
    """Test autocorrect with immediate/negative delay."""
    # Test numeric negative.
    mock_config.GetString.return_value = "-1"
    res = repo._autocorrect_command_name("tart", mock_config)
    mock_sleep.assert_not_called()
    assert res == "start"

    # Test string boolean "true".
    mock_config.GetString.return_value = "true"
    res = repo._autocorrect_command_name("tart", mock_config)
    mock_sleep.assert_not_called()
    assert res == "start"

    # Test string boolean "yes".
    mock_config.GetString.return_value = "YES"
    res = repo._autocorrect_command_name("tart", mock_config)
    mock_sleep.assert_not_called()
    assert res == "start"

    # Test string boolean "immediate".
    mock_config.GetString.return_value = "Immediate"
    res = repo._autocorrect_command_name("tart", mock_config)
    mock_sleep.assert_not_called()
    assert res == "start"


def test_autocorrect_zero_or_show(repo, mock_config):
    """Test autocorrect with zero delay (suggestions only)."""
    # Test numeric zero.
    mock_config.GetString.return_value = "0"
    res = repo._autocorrect_command_name("tart", mock_config)
    assert res is None

    # Test string boolean "false".
    mock_config.GetString.return_value = "False"
    res = repo._autocorrect_command_name("tart", mock_config)
    assert res is None

    # Test string boolean "show".
    mock_config.GetString.return_value = "show"
    res = repo._autocorrect_command_name("tart", mock_config)
    assert res is None


def test_autocorrect_never(repo, mock_config):
    """Test autocorrect with 'never'."""
    mock_config.GetString.return_value = "never"
    res = repo._autocorrect_command_name("tart", mock_config)
    assert res is None


@mock.patch("builtins.input", return_value="y")
def test_autocorrect_prompt_yes(mock_input, repo, mock_config):
    """Test autocorrect with prompt and user answers yes."""
    mock_config.GetString.return_value = "prompt"

    res = repo._autocorrect_command_name("tart", mock_config)

    assert res == "start"


@mock.patch("builtins.input", return_value="n")
def test_autocorrect_prompt_no(mock_input, repo, mock_config):
    """Test autocorrect with prompt and user answers no."""
    mock_config.GetString.return_value = "prompt"

    res = repo._autocorrect_command_name("tart", mock_config)

    assert res is None


@mock.patch("builtins.input", side_effect=KeyboardInterrupt())
def test_autocorrect_prompt_interrupt(mock_input, repo, mock_config):
    """Test autocorrect with prompt and user interrupts."""
    mock_config.GetString.return_value = "prompt"

    res = repo._autocorrect_command_name("tart", mock_config)

    assert res is None
