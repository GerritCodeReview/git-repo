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

import unittest
from unittest import mock

import main


class RepoTests(unittest.TestCase):
    def setUp(self):
        self.repo = main._Repo("repodir")
        # Overriding the command list here ensures that we are only testing
        # against a fixed set of commands, reducing fragility to new
        # subcommands being added to the main repo tool.
        self.repo.commands = {"start": None, "sync": None}

        self.mock_config = mock.MagicMock()

    @mock.patch("time.sleep")
    def test_autocorrect_delay(self, mock_sleep):
        """Test autocorrect with positive delay."""
        self.mock_config.GetString.return_value = "10"

        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )

        self.mock_config.GetString.assert_called_with(
            "help.autocorrect"
        )
        mock_sleep.assert_called_with(1.0)
        assert res == "start"

    @mock.patch("time.sleep")
    def test_autocorrect_immediate(self, mock_sleep):
        """Test autocorrect with immediate/negative delay."""
        # Test numeric negative.
        self.mock_config.GetString.return_value = "-1"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        mock_sleep.assert_not_called()
        assert res == "start"

        # Test string boolean "true".
        self.mock_config.GetString.return_value = "true"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        mock_sleep.assert_not_called()
        assert res == "start"

        # Test string boolean "yes".
        self.mock_config.GetString.return_value = "YES"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        mock_sleep.assert_not_called()
        assert res == "start"

        # Test string boolean "immediate".
        self.mock_config.GetString.return_value = "Immediate"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        mock_sleep.assert_not_called()
        assert res == "start"

    def test_autocorrect_zero_or_show(self):
        """Test autocorrect with zero delay (suggestions only)."""
        # Test numeric zero.
        self.mock_config.GetString.return_value = "0"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        assert res is None

        # Test string boolean "false".
        self.mock_config.GetString.return_value = "False"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        assert res is None

        # Test string boolean "show".
        self.mock_config.GetString.return_value = "show"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        assert res is None

    def test_autocorrect_never(self):
        """Test autocorrect with 'never'."""
        self.mock_config.GetString.return_value = "never"
        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )
        assert res is None

    @mock.patch("builtins.input", return_value="y")
    def test_autocorrect_prompt_yes(self, mock_input):
        """Test autocorrect with prompt and user answers yes."""
        self.mock_config.GetString.return_value = "prompt"

        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )

        assert res == "start"

    @mock.patch("builtins.input", return_value="n")
    def test_autocorrect_prompt_no(self, mock_input):
        """Test autocorrect with prompt and user answers no."""
        self.mock_config.GetString.return_value = "prompt"

        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )

        assert res is None

    @mock.patch("builtins.input", side_effect=KeyboardInterrupt())
    def test_autocorrect_prompt_interrupt(self, mock_input):
        """Test autocorrect with prompt and user interrupts."""
        self.mock_config.GetString.return_value = "prompt"

        res = self.repo._autocorrect_command_name(
            "tart", self.mock_config
        )

        assert res is None
