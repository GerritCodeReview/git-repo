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

"""Unittests for subcmds/cherry_pick.py."""

from unittest import mock

import pytest

from error import GitError
from subcmds import cherry_pick


def test_resolve_reference_uses_one_typed_batch_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oid = b"1" * 40
    commit = b"tree " + b"2" * 40 + b"\n\nSubject\n\nBody\n"
    output = oid + b" commit " + str(len(commit)).encode() + b"\n"
    output += commit + b"\n"
    command = mock.MagicMock(stdout=output, stderr="")
    command.Wait.return_value = 0
    run_git = mock.MagicMock(return_value=command)
    monkeypatch.setattr(cherry_pick, "GitCommand", run_git)

    resolved, contents = cherry_pick.CherryPick()._ResolveReference("topic")

    assert resolved == oid.decode()
    assert contents == commit.decode()
    run_git.assert_called_once_with(
        None,
        ["cat-file", "--batch"],
        input="topic^{commit}\n",
        capture_stdout=True,
        capture_stdout_bytes=True,
        capture_stderr=True,
        verify_command=True,
    )


def test_resolve_reference_rejects_missing_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = mock.MagicMock(stdout=b"topic^{commit} missing\n", stderr="")
    command.Wait.return_value = 0
    monkeypatch.setattr(
        cherry_pick, "GitCommand", mock.MagicMock(return_value=command)
    )

    with pytest.raises(GitError):
        cherry_pick.CherryPick()._ResolveReference("topic")
