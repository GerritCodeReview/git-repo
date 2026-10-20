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
import tempfile
from typing import List
import unittest
from unittest import mock

import pytest

from command import UsageError
import git_config
from subcmds import config


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["a.b", "c", "d"],
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
def test_validate_options_rejects(argv: List[str]) -> None:
    """Invalid argument combinations are rejected."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises((SystemExit, UsageError)):
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
        ["repo.superprojectChoice", "false"],
        ["section.sub.section.name"],
        ["section.with-dash.name-2", "x"],
    ],
)
def test_validate_options_accepts(argv: List[str]) -> None:
    """Valid argument combinations pass validation."""
    cmd = config.Config()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)


class ConfigCommand(unittest.TestCase):
    """Tests for Config.Execute against a real config file."""

    def setUp(self) -> None:
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.config_file = Path(self.tempdirobj.name) / "config"
        self.config = git_config.RepoConfig(configfile=self.config_file)
        self.cmd = config.Config()
        mock.patch.object(
            self.cmd, "_GetConfig", return_value=self.config
        ).start()

    def tearDown(self) -> None:
        mock.patch.stopall()
        self.tempdirobj.cleanup()

    def _run(self, argv: List[str]) -> str:
        opts, args = self.cmd.OptionParser.parse_args(argv)
        self.cmd.ValidateOptions(opts, args)
        with mock.patch("builtins.print") as mock_print:
            self.cmd.Execute(opts, args)
        return "\n".join(
            " ".join(str(a) for a in call.args)
            for call in mock_print.call_args_list
        )

    def _file_contents(self) -> str:
        if not self.config_file.exists():
            return ""
        return self.config_file.read_text()

    def test_set_creates_file(self) -> None:
        """Setting a value writes it to the config file."""
        self._run(["sync.smartsync", "true"])
        self.assertIn("smartsync = true", self._file_contents())
        self.assertEqual(self.config.GetBoolean("sync.smartsync"), True)

    def test_set_then_get(self) -> None:
        """Getting a value prints what was set."""
        self._run(["sync.smartsync", "false"])
        self.assertEqual(self._run(["sync.smartsync"]), "false")

    def test_set_overwrites(self) -> None:
        """Setting an existing key replaces its value."""
        self._run(["sync.smartsync", "true"])
        self._run(["sync.smartsync", "false"])
        self.assertEqual(self._run(["sync.smartsync"]), "false")
        self.assertEqual(self._file_contents().count("smartsync"), 1)

    def test_get_missing_exits_quietly(self) -> None:
        """Reading an unset key exits 1 without output, like git config."""
        opts, args = self.cmd.OptionParser.parse_args(["sync.smartsync"])
        with mock.patch("builtins.print") as mock_print:
            with self.assertRaises(config.NotSetError) as e:
                self.cmd.Execute(opts, args)
        self.assertEqual(e.exception.exit_code, 1)
        mock_print.assert_not_called()

    def test_unset(self) -> None:
        """--unset removes the key."""
        self._run(["sync.smartsync", "true"])
        self._run(["--unset", "sync.smartsync"])
        self.assertIsNone(self.config.GetString("sync.smartsync"))
        self.assertNotIn("smartsync", self._file_contents())

    def test_unset_missing_is_noop(self) -> None:
        """--unset on a missing key does not fail or create the file."""
        self._run(["--unset", "sync.smartsync"])
        self.assertFalse(self.config_file.exists())

    def test_list(self) -> None:
        """--list prints all keys sorted as key=value."""
        self._run(["sync.smartsync", "true"])
        self._run(["alias.ss", "sync -s"])
        self.assertEqual(
            self._run(["--list"]),
            "alias.ss=sync -s\nsync.smartsync=true",
        )

    def test_list_empty(self) -> None:
        """--list on a missing file prints nothing."""
        self.assertEqual(self._run(["--list"]), "")

    def test_value_with_spaces(self) -> None:
        """Values containing spaces round trip."""
        self._run(["alias.ss", "sync -s -j 4"])
        self.assertEqual(self._run(["alias.ss"]), "sync -s -j 4")

    def test_key_is_case_insensitive(self) -> None:
        """Section and name are case-insensitive, like git."""
        self._run(["Sync.SmartSync", "true"])
        self.assertEqual(self._run(["sync.smartsync"]), "true")
