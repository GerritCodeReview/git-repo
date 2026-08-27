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


def _create_mock_branch(
    name: str = "main",
    commits: Optional[List[str]] = None,
    project_relpath: str = "project-a",
    review_url: str = "https://review.example.com",
    autoupload: Optional[bool] = None,
    threshold: Optional[int] = None,
) -> mock.MagicMock:
    """Helper to construct a mock ReviewableBranch."""
    branch = mock.MagicMock()
    branch.name = name
    branch.commits = commits if commits is not None else ["commit1"]
    branch.date = "2026-08-26"
    branch.uploaded = False
    branch.error = None

    project = mock.MagicMock()
    project.RelPath.return_value = project_relpath
    project.dest_branch = None
    project.revisionExpr = "refs/heads/main"

    remote = mock.MagicMock()
    remote.review = review_url

    branch_config = mock.MagicMock()
    branch_config.remote = remote
    project.GetBranch.return_value = branch_config

    def config_get_boolean(key: str) -> Optional[bool]:
        if "autoupload" in key:
            return autoupload
        return None

    def config_get_int(key: str) -> Optional[int]:
        if "uploadwarningthreshold" in key:
            return threshold
        return None

    project.config.GetBoolean.side_effect = config_get_boolean
    project.config.GetInt.side_effect = config_get_int
    branch.project = project
    return branch


def test_VerifyPendingCommits_normal_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify user can confirm many commits when interactive."""
    monkeypatch.delenv("REPO_AGENT_MODE", raising=False)
    monkeypatch.delenv("GEMINI_CLI", raising=False)
    branch = _create_mock_branch(commits=["c%d" % i for i in range(10)])
    with mock.patch("builtins.input", return_value="yes"):
        assert upload._VerifyPendingCommits([branch]) is True


def test_VerifyPendingCommits_normal_aborted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify user can abort many commits when interactive."""
    monkeypatch.delenv("REPO_AGENT_MODE", raising=False)
    monkeypatch.delenv("GEMINI_CLI", raising=False)
    branch = _create_mock_branch(commits=["c%d" % i for i in range(10)])
    with mock.patch("builtins.input", return_value="no"):
        assert upload._VerifyPendingCommits([branch]) is False


def test_VerifyPendingCommits_agentic_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify agentic environment fails fast without prompt on many commits."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    branch = _create_mock_branch(commits=["c%d" % i for i in range(10)])
    with mock.patch("builtins.input") as mock_input:
        assert upload._VerifyPendingCommits([branch]) is False
        mock_input.assert_not_called()


def test_SingleBranch_agentic_no_yes_fails_fast(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_SingleBranch fails fast in agent environment without --yes."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args([])
    branch = _create_mock_branch()

    with pytest.raises(
        upload.UploadExitError, match="blocked in agentic environment"
    ):
        cmd._SingleBranch(opt, branch, _STUB_PEOPLE)


def test_SingleBranch_agentic_with_yes_proceeds(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_SingleBranch proceeds directly in agentic environment with --yes."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args(["-y"])
    branch = _create_mock_branch()

    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload:
        cmd._SingleBranch(opt, branch, _STUB_PEOPLE)
        mock_upload.assert_called_once_with(opt, [branch], _STUB_PEOPLE)


def test_MultipleBranches_yes_unambiguous_bypasses_editor(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_MultipleBranches with --yes and 1 branch per project bypasses editor."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args(["-y"])
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


def test_MultipleBranches_agentic_ambiguous_fails_fast(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_MultipleBranches in agent mode with ambiguous branches fails fast."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args(["-y"])
    branch1 = _create_mock_branch("b1", project_relpath="p1")
    branch2 = _create_mock_branch("b2", project_relpath="p1")
    pending = [(branch1.project, [branch1, branch2])]

    with pytest.raises(
        upload.UploadExitError, match="blocked in agentic environment"
    ):
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)


def test_MultipleBranches_agentic_no_yes_unambiguous_fails_fast(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_MultipleBranches in agentic environment without --yes fails fast."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args([])
    branch1 = _create_mock_branch("b1", project_relpath="p1")
    pending = [(branch1.project, [branch1])]

    with pytest.raises(
        upload.UploadExitError, match="blocked in agentic environment"
    ):
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)


def test_MultipleBranches_normal_interactive(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_MultipleBranches in normal mode opens editor and processes edits."""
    monkeypatch.delenv("REPO_AGENT_MODE", raising=False)
    monkeypatch.delenv("GEMINI_CLI", raising=False)
    opt, _ = cmd.OptionParser.parse_args([])
    branch1 = _create_mock_branch("b1", project_relpath="p1")
    pending = [(branch1.project, [branch1])]

    edited_script = (
        "project p1/:\n"
        "  branch b1 ( 1 commit, 2026-08-26) to remote branch "
        "refs/heads/main:\n"
    )
    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload, mock.patch(
        "editor.Editor.EditString", return_value=edited_script
    ):
        cmd._MultipleBranches(opt, pending, _STUB_PEOPLE)
        mock_upload.assert_called_once_with(opt, [branch1], _STUB_PEOPLE)


def test_SingleBranch_agentic_autoupload_true_proceeds_without_yes(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_SingleBranch proceeds in agent environment if autoupload=true."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args([])
    branch = _create_mock_branch(autoupload=True)

    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload:
        cmd._SingleBranch(opt, branch, _STUB_PEOPLE)
        mock_upload.assert_called_once_with(opt, [branch], _STUB_PEOPLE)


def test_SingleBranch_agentic_autoupload_false_aborts(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_SingleBranch aborts in agent environment if autoupload=false."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args(["-y"])
    branch = _create_mock_branch(autoupload=False)

    with pytest.raises(upload.UploadExitError, match="upload blocked by"):
        cmd._SingleBranch(opt, branch, _STUB_PEOPLE)


def test_SingleBranch_yes_with_many_commits_bypasses_prompt(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_SingleBranch with --yes does not prompt even with many commits."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
    opt, _ = cmd.OptionParser.parse_args(["-y"])
    branch = _create_mock_branch(commits=["c%d" % i for i in range(10)])

    with mock.patch.object(cmd, "_UploadAndReport") as mock_upload:
        cmd._SingleBranch(opt, branch, _STUB_PEOPLE)
        mock_upload.assert_called_once_with(opt, [branch], _STUB_PEOPLE)


def test_MultipleBranches_yes_with_branch_flag_bypasses_editor(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_MultipleBranches with --yes and --br flag bypasses editor."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
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


def test_MultipleBranches_yes_with_current_branch_flag_bypasses_editor(
    cmd: upload.Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_MultipleBranches with --yes and -c flag bypasses editor."""
    monkeypatch.setenv("REPO_AGENT_MODE", "1")
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
