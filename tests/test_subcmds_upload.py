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
