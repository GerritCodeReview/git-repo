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

from pathlib import Path
from unittest import mock

import pytest

from main import _Repo


@pytest.fixture(name="repo")
def fixture_repo():
    repo = _Repo("repodir")
    # Overriding the command list here ensures that we are only testing
    # against a fixed set of commands, reducing fragility to new
    # subcommands being added to the main repo tool.
    repo.commands = {"start": None, "sync": None, "smart": None}
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
def test_autocorrect_delay_one(mock_sleep, repo, mock_config):
    """Test autocorrect with '1' (0.1s delay, not immediate)."""
    mock_config.GetString.return_value = "1"

    res = repo._autocorrect_command_name("tart", mock_config)

    mock_sleep.assert_called_with(0.1)
    assert res == "start"


@mock.patch("time.sleep", side_effect=KeyboardInterrupt())
def test_autocorrect_delay_interrupt(mock_sleep, repo, mock_config):
    """Test autocorrect handles KeyboardInterrupt during delay."""
    mock_config.GetString.return_value = "10"

    res = repo._autocorrect_command_name("tart", mock_config)

    mock_sleep.assert_called_with(1.0)
    assert res is None


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


@mock.patch("builtins.input", return_value="y")
def test_autocorrect_multiple_candidates(mock_input, repo, mock_config):
    """Test autocorrect with multiple matches forces a prompt."""
    mock_config.GetString.return_value = "10"  # Normally just delay

    # 'snart' matches both 'start' and 'smart' with > 0.7 ratio
    res = repo._autocorrect_command_name("snart", mock_config)

    # Because there are multiple candidates, it should prompt
    mock_input.assert_called_once()
    assert res == "start"


@mock.patch("builtins.input", side_effect=KeyboardInterrupt())
def test_autocorrect_prompt_interrupt(mock_input, repo, mock_config):
    """Test autocorrect with prompt and user interrupts."""
    mock_config.GetString.return_value = "prompt"

    res = repo._autocorrect_command_name("tart", mock_config)

    assert res is None


@mock.patch("main.RepoClient")
def test_run_long_gates_event_log_on_flag(
    mock_client_cls: mock.MagicMock, tmp_path: Path
) -> None:
    """Test _RunLong enables cmd.event_log only when --event-log is set."""
    client = mock_client_cls.return_value
    client.manifest.IsMirror = False
    client.manifest.manifestProject.config.DumpConfigDict.return_value = {}
    repo = _Repo("repodir")

    for log_path, expected in (
        (None, False),
        (str(tmp_path / "events.log"), True),
    ):
        cmd = mock.MagicMock()
        cmd.manifest = client.manifest
        cmd.MULTI_MANIFEST_SUPPORT = True
        cmd.OptionParser.parse_args.return_value = (mock.MagicMock(), [])
        cmd.ReadEnvironmentOptions.side_effect = lambda copts: copts
        cmd.Execute.return_value = 0
        repo.commands = {"sync": mock.Mock(return_value=cmd)}
        gopts = mock.MagicMock(
            color=None,
            submanifest_path="",
            pager=False,
            time=False,
            event_log=log_path,
            git_trace2_event_log=None,
        )

        assert repo._RunLong("sync", gopts, [], mock.MagicMock()) == 0
        assert cmd.event_log_enabled is expected
        assert cmd.event_log.Add.called is expected
        assert cmd.event_log.Write.called is expected
