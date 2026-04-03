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

"""Unittests for the subcmds/info.py module."""

import unittest
from unittest import mock

from subcmds import info


class InfoCommand(unittest.TestCase):
    """Tests for the Info subcommand."""

    def setUp(self):
        """Common setup: build a mock manifest and construct the command."""
        self.manifest = manifest = mock.MagicMock()
        manifest.default.revisionExpr = "refs/heads/main"
        manifest.manifestProject.config.GetBranch.return_value.merge = (
            "refs/heads/main"
        )
        manifest.GetManifestGroupsStr.return_value = "all"
        manifest.superproject = None
        # Execute does self.manifest = self.manifest.outer_client when
        # this_manifest_only is False, so wire it back to the same mock.
        manifest.outer_client = manifest

        self.client = client = mock.MagicMock()
        git_event_log = mock.MagicMock()

        self.cmd = info.Info(
            manifest=manifest,
            client=client,
            git_event_log=git_event_log,
        )

    def _parse(self, argv=None):
        """Parse argv and return (opts, args)."""
        if argv is None:
            argv = []
        opts, args = self.cmd.OptionParser.parse_args(argv)
        return opts, args

    def test_include_options_default_true(self):
        """Both include options should default to True."""
        opts, _ = self._parse([])
        self.assertTrue(opts.include_summary)
        self.assertTrue(opts.include_projects)

    def test_no_include_projects_skips_projects(self):
        """--no-include-projects should skip project iteration."""
        opts, args = self._parse(["--no-include-projects"])

        with mock.patch.object(
            self.cmd, "_printDiffInfo"
        ) as mock_diff, mock.patch.object(
            self.cmd, "_printCommitOverview"
        ) as mock_overview:
            self.cmd.Execute(opts, args)
            mock_diff.assert_not_called()
            mock_overview.assert_not_called()

    def test_no_include_summary_skips_summary(self):
        """--no-include-summary should not query or print manifest metadata."""
        opts, args = self._parse(["--no-include-summary"])

        with mock.patch.object(self.cmd, "_printDiffInfo"):
            self.cmd.Execute(opts, args)
        self.manifest.GetManifestGroupsStr.assert_not_called()

    def test_include_summary_parses(self):
        """--include-summary should set include_summary to True."""
        opts, _ = self._parse(["--include-summary"])
        self.assertTrue(opts.include_summary)

    def test_no_include_summary_parses(self):
        """--no-include-summary should set include_summary to False."""
        opts, _ = self._parse(["--no-include-summary"])
        self.assertFalse(opts.include_summary)

    def test_include_projects_parses(self):
        """--include-projects should set include_projects to True."""
        opts, _ = self._parse(["--include-projects"])
        self.assertTrue(opts.include_projects)

    def test_no_include_projects_parses(self):
        """--no-include-projects should set include_projects to False."""
        opts, _ = self._parse(["--no-include-projects"])
        self.assertFalse(opts.include_projects)

    def test_default_calls_diff_info(self):
        """Default options should call _printDiffInfo."""
        opts, args = self._parse([])

        with mock.patch.object(
            self.cmd, "_printDiffInfo"
        ) as mock_diff, mock.patch.object(
            self.cmd, "_printCommitOverview"
        ) as mock_overview:
            self.cmd.Execute(opts, args)
            mock_diff.assert_called_once_with(opts, args)
            mock_overview.assert_not_called()

    def test_overview_calls_commit_overview(self):
        """--overview should call _printCommitOverview, not _printDiffInfo."""
        opts, args = self._parse(["--overview"])

        self.cmd.GetProjects = mock.Mock(return_value=[])

        with mock.patch.object(
            self.cmd, "_printDiffInfo"
        ) as mock_diff, mock.patch.object(
            self.cmd, "_printCommitOverview"
        ) as mock_overview:
            self.cmd.Execute(opts, args)
            mock_diff.assert_not_called()
            mock_overview.assert_called_once_with(opts, args)

    def test_no_include_projects_with_overview(self):
        """--no-include-projects should take priority over --overview."""
        opts, args = self._parse(["--no-include-projects", "--overview"])

        with mock.patch.object(
            self.cmd, "_printDiffInfo"
        ) as mock_diff, mock.patch.object(
            self.cmd, "_printCommitOverview"
        ) as mock_overview:
            self.cmd.Execute(opts, args)
            mock_diff.assert_not_called()
            mock_overview.assert_not_called()
