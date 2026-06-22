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

import json
from unittest import mock

import pytest

from subcmds import info


def _get_cmd() -> info.Info:
    """Build a mock-backed Info command for testing."""
    manifest = mock.MagicMock()
    manifest.default.revisionExpr = "refs/heads/main"
    manifest.manifestProject.config.GetBranch.return_value.merge = (
        "refs/heads/main"
    )
    manifest.GetManifestGroupsStr.return_value = "all"
    manifest.superproject = None
    manifest.outer_client = manifest

    client = mock.MagicMock()
    git_event_log = mock.MagicMock()

    return info.Info(
        manifest=manifest,
        client=client,
        git_event_log=git_event_log,
    )


def test_include_options_default_true() -> None:
    """Both include options should default to True."""
    opts, _ = _get_cmd().OptionParser.parse_args([])
    assert opts.include_summary
    assert opts.include_projects


def test_no_include_summary_parses() -> None:
    """--no-include-summary should set include_summary to False."""
    opts, _ = _get_cmd().OptionParser.parse_args(["--no-include-summary"])
    assert not opts.include_summary


def test_no_include_projects_parses() -> None:
    """--no-include-projects should set include_projects to False."""
    opts, _ = _get_cmd().OptionParser.parse_args(["--no-include-projects"])
    assert not opts.include_projects


def test_format_default_text() -> None:
    """Default format should be text."""
    opts, _ = _get_cmd().OptionParser.parse_args([])
    assert opts.format == "text"


def test_format_json_parses() -> None:
    """--format=json should be accepted."""
    opts, _ = _get_cmd().OptionParser.parse_args(["--format=json"])
    assert opts.format == "json"


def test_no_include_projects_skips_projects() -> None:
    """--no-include-projects should skip project iteration."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(["--no-include-projects"])

    with mock.patch.object(
        cmd, "_printDiffInfo"
    ) as mock_diff, mock.patch.object(
        cmd, "_printCommitOverview"
    ) as mock_overview:
        cmd.Execute(opts, args)
        mock_diff.assert_not_called()
        mock_overview.assert_not_called()


def test_no_include_summary_skips_summary() -> None:
    """--no-include-summary should not query or print manifest metadata."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(["--no-include-summary"])

    with mock.patch.object(cmd, "_printDiffInfo"):
        cmd.Execute(opts, args)
    cmd.manifest.GetManifestGroupsStr.assert_not_called()


def test_default_calls_diff_info() -> None:
    """Default options should call _printDiffInfo."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args([])

    with mock.patch.object(
        cmd, "_printDiffInfo"
    ) as mock_diff, mock.patch.object(
        cmd, "_printCommitOverview"
    ) as mock_overview:
        cmd.Execute(opts, args)
        mock_diff.assert_called_once_with(opts, args)
        mock_overview.assert_not_called()


def test_overview_calls_commit_overview() -> None:
    """--overview should call _printCommitOverview, not _printDiffInfo."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(["--overview"])

    with mock.patch.object(
        cmd, "_printDiffInfo"
    ) as mock_diff, mock.patch.object(
        cmd, "_printCommitOverview"
    ) as mock_overview:
        cmd.Execute(opts, args)
        mock_diff.assert_not_called()
        mock_overview.assert_called_once_with(opts, args)


def test_no_include_projects_with_overview() -> None:
    """--no-include-projects should take priority over --overview."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(
        ["--no-include-projects", "--overview"]
    )

    with mock.patch.object(
        cmd, "_printDiffInfo"
    ) as mock_diff, mock.patch.object(
        cmd, "_printCommitOverview"
    ) as mock_overview:
        cmd.Execute(opts, args)
        mock_diff.assert_not_called()
        mock_overview.assert_not_called()


def test_json_summary_only(capsys) -> None:
    """--format=json --no-include-projects should emit only summary."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(
        ["--format=json", "--no-include-projects"]
    )
    cmd.Execute(opts, args)
    data = json.loads(capsys.readouterr().out)
    assert "summary" in data
    assert "projects" not in data
    assert data["summary"]["manifest_branch"] == "refs/heads/main"
    assert data["summary"]["manifest_groups"] == "all"


def test_json_no_summary(capsys) -> None:
    """--format=json --no-include-summary should omit summary."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(
        ["--format=json", "--no-include-summary", "--no-include-projects"]
    )
    cmd.Execute(opts, args)
    data = json.loads(capsys.readouterr().out)
    assert "summary" not in data


def test_json_rejects_diff() -> None:
    """--format=json --diff should be rejected."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(["--format=json", "--diff"])
    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opts, args)


def test_json_rejects_overview() -> None:
    """--format=json --overview should be rejected."""
    cmd = _get_cmd()
    opts, args = cmd.OptionParser.parse_args(["--format=json", "--overview"])
    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opts, args)


def test_json_disables_pager() -> None:
    """--format=json should disable the pager."""
    cmd = _get_cmd()
    opts, _ = cmd.OptionParser.parse_args(["--format=json"])
    assert not cmd.WantPager(opts)


def test_text_enables_pager() -> None:
    """Default text format should enable the pager."""
    cmd = _get_cmd()
    opts, _ = cmd.OptionParser.parse_args([])
    assert cmd.WantPager(opts)


def test_get_project_data_uses_head_revision() -> None:
    """_getProjectData should use GetHeadRevisionId if available."""
    cmd = _get_cmd()
    project = mock.MagicMock()
    project.name = "foo"
    project.worktree = "/path/to/foo"
    project.revisionExpr = "refs/heads/main"
    project.GetBranches.return_value = []

    # GetHeadRevisionId() returns a SHA, it should be used.
    project.GetHeadRevisionId.return_value = "head_sha_12345"
    project.GetRevisionId.return_value = "manifest_sha_54321"

    data = cmd._getProjectData(project)
    assert data["current_revision"] == "head_sha_12345"
    project.GetHeadRevisionId.assert_called_once()

    # GetHeadRevisionId() is None, fall back to GetRevisionId().
    project.GetHeadRevisionId.reset_mock()
    project.GetHeadRevisionId.return_value = None
    data = cmd._getProjectData(project)
    assert data["current_revision"] == "manifest_sha_54321"
