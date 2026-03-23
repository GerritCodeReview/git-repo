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

"""Unittests for RepoMon message in subcmds/sync.py."""

import unittest
from unittest import mock
from subcmds import sync

class TestRepoMon(unittest.TestCase):
    def setUp(self):
        self.cmd = sync.Sync()
        self.cmd.manifest = mock.MagicMock()
        self.cmd.manifest.default.repomon_threshold = None
        self.opt = mock.MagicMock()
        self.opt.quiet = False

    def test_is_googleplex_android_true(self):
        """Test _IsGoogleplexAndroid returns True when a remote matches."""
        remote = mock.MagicMock()
        remote.resolvedFetchUrl = "https://googleplex-android.googlesource.com/manifest"
        self.cmd.manifest.remotes = {"origin": remote}
        self.assertTrue(self.cmd._IsGoogleplexAndroid())

    def test_is_googleplex_android_false(self):
        """Test _IsGoogleplexAndroid returns False when no remote matches."""
        remote = mock.MagicMock()
        remote.resolvedFetchUrl = "https://android.googlesource.com/manifest"
        self.cmd.manifest.remotes = {"origin": remote}
        self.assertFalse(self.cmd._IsGoogleplexAndroid())

    def test_maybe_report_repomon_quiet(self):
        """Test no message is printed when quiet is True."""
        self.opt.quiet = True
        with mock.patch("builtins.print") as mock_print:
            self.cmd._MaybeReportRepoMon(self.opt, 1000)
            mock_print.assert_not_called()

    def test_maybe_report_repomon_not_googleplex(self):
        """Test no message is printed when not on googleplex-android."""
        with mock.patch.object(self.cmd, "_IsGoogleplexAndroid", return_value=False):
            with mock.patch("builtins.print") as mock_print:
                self.cmd._MaybeReportRepoMon(self.opt, 1000)
                mock_print.assert_not_called()

    def test_maybe_report_repomon_below_default_threshold(self):
        """Test no message is printed when duration is below default threshold."""
        self.cmd.manifest.default.repomon_threshold = None
        with mock.patch.object(self.cmd, "_IsGoogleplexAndroid", return_value=True):
            with mock.patch("builtins.print") as mock_print:
                self.cmd._MaybeReportRepoMon(self.opt, 500)
                mock_print.assert_not_called()

    def test_maybe_report_repomon_above_default_threshold(self):
        """Test message is printed when duration is above default threshold."""
        self.cmd.manifest.default.repomon_threshold = None
        with mock.patch.object(self.cmd, "_IsGoogleplexAndroid", return_value=True):
            with mock.patch("builtins.print") as mock_print:
                self.cmd._MaybeReportRepoMon(self.opt, 700)
                mock_print.assert_called_once()
                self.assertIn("Sync took over 600 seconds", mock_print.call_args[0][0])
                self.assertIn("http://go/repomon", mock_print.call_args[0][0])

    def test_maybe_report_repomon_manifest_threshold(self):
        """Test message is printed when duration is above manifest threshold."""
        self.cmd.manifest.default.repomon_threshold = 300
        with mock.patch.object(self.cmd, "_IsGoogleplexAndroid", return_value=True):
            with mock.patch("builtins.print") as mock_print:
                self.cmd._MaybeReportRepoMon(self.opt, 400)
                mock_print.assert_called_once()
                self.assertIn("Sync took over 300 seconds", mock_print.call_args[0][0])

    def test_execute_calls_maybe_report_repomon(self):
        """Test Execute calls _MaybeReportRepoMon in finally block."""
        with mock.patch.object(self.cmd, "_ExecuteHelper") as mock_helper:
            with mock.patch.object(self.cmd, "_MaybeReportRepoMon") as mock_report:
                with mock.patch.object(self.cmd, "_RunPostSyncHook"):
                    self.cmd.Execute(self.opt, [])
                    mock_helper.assert_called_once()
                    mock_report.assert_called_once()
                    # Check that duration (second arg) is a number (float or int)
                    duration = mock_report.call_args[0][1]
                    self.assertIsInstance(duration, (float, int))

    def test_execute_calls_maybe_report_repomon_on_error(self):
        """Test Execute calls _MaybeReportRepoMon even on error."""
        with mock.patch.object(self.cmd, "_ExecuteHelper", side_effect=Exception("error")):
            with mock.patch.object(self.cmd, "_MaybeReportRepoMon") as mock_report:
                with self.assertRaises(Exception):
                    self.cmd.Execute(self.opt, [])
                mock_report.assert_called_once()

if __name__ == "__main__":
    unittest.main()
