# Copyright (C) 2023 The Android Open Source Project
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

"""Unittests for the subcmds/upload.py module."""

from typing import List, Optional
from unittest import mock

import pytest

from error import GitError
from error import UploadError
from subcmds import upload


class UnexpectedError(Exception):
    """An exception not expected by upload command."""


# A stub people list (reviewers, cc).
_STUB_PEOPLE = ([], [])


@pytest.fixture
def cmd() -> upload.Upload:
    """Fixture to provide an Upload command instance with mocked methods."""
    cmd = upload.Upload()
    with mock.patch.object(
        cmd, "_AppendAutoList", return_value=None
    ), mock.patch.object(cmd, "git_event_log"):
        yield cmd


def test_UploadAndReport_UploadError(cmd: upload.Upload) -> None:
    """Check UploadExitError raised when UploadError encountered."""
    opt, _ = cmd.OptionParser.parse_args([])
    with mock.patch.object(cmd, "_UploadBranch", side_effect=UploadError("")):
        with pytest.raises(upload.UploadExitError):
            cmd._UploadAndReport(opt, [mock.MagicMock()], _STUB_PEOPLE)


def test_UploadAndReport_GitError(cmd: upload.Upload) -> None:
    """Check UploadExitError raised when GitError encountered."""
    opt, _ = cmd.OptionParser.parse_args([])
    with mock.patch.object(cmd, "_UploadBranch", side_effect=GitError("")):
        with pytest.raises(upload.UploadExitError):
            cmd._UploadAndReport(opt, [mock.MagicMock()], _STUB_PEOPLE)


def test_UploadAndReport_UnhandledError(cmd: upload.Upload) -> None:
    """Check UnexpectedError passed through."""
    opt, _ = cmd.OptionParser.parse_args([])
    with mock.patch.object(cmd, "_UploadBranch", side_effect=UnexpectedError):
        with pytest.raises(UnexpectedError):
            cmd._UploadAndReport(opt, [mock.MagicMock()], _STUB_PEOPLE)


def test_GetMergeBranch_explicit_branch(cmd: upload.Upload) -> None:
    """Verify _GetMergeBranch reads branch.merge for explicit local_branch."""
    mock_project = mock.MagicMock()
    mock_branch = mock.MagicMock()
    mock_branch.merge = "refs/heads/main"
    mock_project.GetBranch.return_value = mock_branch

    res = cmd._GetMergeBranch(mock_project, local_branch="feature")
    assert res == "refs/heads/main"
    mock_project.GetBranch.assert_called_once_with("feature")


def test_GetMergeBranch_current_branch(cmd: upload.Upload) -> None:
    """Verify _GetMergeBranch falls back to project.CurrentBranch."""
    mock_project = mock.MagicMock()
    mock_project.CurrentBranch = "auto-cbr"
    mock_branch = mock.MagicMock()
    mock_branch.merge = "refs/heads/upstream-main"
    mock_project.GetBranch.return_value = mock_branch

    res = cmd._GetMergeBranch(mock_project, local_branch=None)
    assert res == "refs/heads/upstream-main"
    mock_project.GetBranch.assert_called_once_with("auto-cbr")


def test_GetMergeBranch_none_when_no_branch(cmd: upload.Upload) -> None:
    """Verify _GetMergeBranch returns empty string when detached HEAD."""
    mock_project = mock.MagicMock()
    mock_project.CurrentBranch = None

    res = cmd._GetMergeBranch(mock_project, local_branch=None)
    assert res == ""


def test_GatherOne_returns_resolved_current_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload error reporting reuses the branch gathered by the worker."""
    project = mock.MagicMock()
    project.CurrentBranch = "topic"
    branch = mock.sentinel.branch
    project.GetUploadableBranch.return_value = branch
    monkeypatch.setattr(
        upload.Upload,
        "get_parallel_context",
        lambda: {"projects": [project]},
    )
    opt = mock.MagicMock(current_branch=True)

    assert upload.Upload._GatherOne(opt, 0) == (0, [branch], "topic")

    project.GetUploadableBranch.assert_called_once_with("topic")


def _create_mock_branch(
    name: str = "main",
    commits: Optional[List[str]] = None,
    project_relpath: str = "project-a",
) -> mock.MagicMock:
    """Helper to construct a mock ReviewableBranch."""
    branch = mock.MagicMock()
    branch.name = name
    branch.commits = commits if commits is not None else ["commit1"]

    project = mock.MagicMock()
    project.RelPath.return_value = project_relpath
    branch.project = project
    return branch


def test_MultipleBranches_yes_with_current_branch_flag_bypasses_editor(
    cmd: upload.Upload,
) -> None:
    """_MultipleBranches with --yes and -c flag bypasses editor."""
    opt, _ = cmd.OptionParser.parse_args(["-c", "-y"])
    branch1 = _create_mock_branch("b1", project_relpath="p1")
    branch2 = _create_mock_branch("b2", project_relpath="p2")
    pending = [(branch1.project, [branch1]), (branch2.project, [branch2])]

    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload, mock.patch(
        "editor.Editor.EditString"
    ) as mock_edit:
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)
        mock_edit.assert_not_called()
        mock_upload.assert_called_once_with(
            opt, [branch1, branch2], _STUB_PEOPLE
        )


def test_MultipleBranches_yes_with_branch_flag_bypasses_editor(
    cmd: upload.Upload,
) -> None:
    """_MultipleBranches with --yes and --br flag bypasses editor."""
    opt, _ = cmd.OptionParser.parse_args(["--br", "feature", "-y"])
    branch1 = _create_mock_branch("feature", project_relpath="p1")
    branch2 = _create_mock_branch("feature", project_relpath="p2")
    pending = [(branch1.project, [branch1]), (branch2.project, [branch2])]

    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload, mock.patch(
        "editor.Editor.EditString"
    ) as mock_edit:
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)
        mock_edit.assert_not_called()
        mock_upload.assert_called_once_with(
            opt, [branch1, branch2], _STUB_PEOPLE
        )


def test_MultipleBranches_yes_with_branch_flag_empty_pending_dies(
    cmd: upload.Upload,
) -> None:
    """_MultipleBranches with --yes and empty pending branches dies."""
    opt, _ = cmd.OptionParser.parse_args(["--br", "feature", "-y"])
    mock_project = mock.MagicMock()
    pending = [(mock_project, [])]

    with pytest.raises(
        upload.UploadExitError, match="nothing ready for upload"
    ):
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)


def test_MultipleBranches_yes_without_branch_or_cbr_uses_editor(
    cmd: upload.Upload,
) -> None:
    """_MultipleBranches with -y but no -c/--br falls back to editor."""
    opt, _ = cmd.OptionParser.parse_args(["-y"])
    branch1 = _create_mock_branch("b1", project_relpath="p1")
    branch1.date = "2026-08-26"
    mock_remote = mock.MagicMock()
    branch1.project.dest_branch = None
    branch1.project.revisionExpr = "refs/heads/main"
    branch_config = mock.MagicMock()
    branch_config.remote = mock_remote
    branch1.project.GetBranch.return_value = branch_config
    pending = [(branch1.project, [branch1])]

    edited_script = (
        "project p1/:\n"
        "  branch b1 ( 1 commit, 2026-08-26) to remote branch "
        "refs/heads/main:\n"
    )
    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload, mock.patch(
        "editor.Editor.EditString", return_value=edited_script
    ) as mock_edit:
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)
        mock_edit.assert_called_once()
        mock_upload.assert_called_once_with(opt, [branch1], _STUB_PEOPLE)
