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

"""Unittests for the git_status.py module."""

import os
from typing import Any, List
from unittest import mock

import pytest

import git_status


def test_parse_porcelain_v2_branch_and_paths() -> None:
    output = (
        b"# branch.oid " + b"1" * 40 + b"\0"
        b"# branch.head topic\0"
        b"# branch.upstream origin/main\0"
        b"# branch.ab +2 -3\0"
        b"# stash 1\0"
        b"1 M. N... 100644 100644 100644 "
        + b"1" * 40
        + b" "
        + b"2" * 40
        + b" staged name\0"
        b"1 .M N... 100644 100644 100644 "
        + b"1" * 40
        + b" "
        + b"2" * 40
        + b" worktree name\0"
        b"2 R. N... 100644 100644 100644 "
        + b"1" * 40
        + b" "
        + b"2" * 40
        + b" R075 renamed\0old name\0"
        b"? untracked\0"
    )

    status = git_status.ParsePorcelainV2(output)

    assert status.current_branch == "topic"
    assert status.upstream == "origin/main"
    assert (status.ahead, status.behind, status.stash_count) == (2, 3, 1)
    assert status.index_changes["staged name"].status == "M"
    assert status.worktree_changes["worktree name"].status == "M"
    renamed = status.index_changes["renamed"]
    assert (renamed.src_path, renamed.level) == ("old name", "75")
    assert status.untracked == ["untracked"]


def test_parse_porcelain_v2_unmerged_and_non_utf8_path() -> None:
    path = b"bad-\xff-name"
    output = (
        b"u UU N... 100644 100644 100644 100644 "
        + b"1" * 40
        + b" "
        + b"2" * 40
        + b" "
        + b"3" * 40
        + b" "
        + path
        + b"\0"
    )

    status = git_status.ParsePorcelainV2(output)
    decoded = os.fsdecode(path)

    assert status.index_changes[decoded].status == "U"
    assert status.worktree_changes[decoded].status == "U"
    assert os.fsencode(status.index_changes[decoded].path) == path


def test_untracked_only_respects_consider_untracked() -> None:
    status = git_status.ParsePorcelainV2(b"? new file\0")

    assert status.is_dirty()
    assert not status.is_dirty(consider_untracked=False)


def test_branch_headers_preserve_non_ascii_names() -> None:
    branch = "tópico"
    status = git_status.ParsePorcelainV2(
        b"# branch.oid " + b"1" * 40 + b"\0"
        b"# branch.head " + os.fsencode(branch) + b"\0"
    )

    assert status.current_branch == branch


def test_quick_ahead_behind_is_recorded_as_unknown() -> None:
    status = git_status.ParsePorcelainV2(b"# branch.ab +? -?\0")

    assert (status.ahead, status.behind) == (0, 0)
    assert not status.has_ahead_behind


def test_unknown_head_is_not_a_current_branch() -> None:
    status = git_status.ParsePorcelainV2(b"# branch.head (unknown)\0")

    assert status.current_branch is None


def test_malformed_output_is_rejected() -> None:
    with pytest.raises(git_status.StatusParseError):
        git_status.ParsePorcelainV2(b"2 R. truncated\0")


def test_malformed_branch_ab_is_rejected() -> None:
    with pytest.raises(git_status.StatusParseError):
        git_status.ParsePorcelainV2(b"# branch.ab not-a-valid-ab\0")


def test_ignored_records_are_skipped() -> None:
    status = git_status.ParsePorcelainV2(b"! ignored_file\0")
    assert not status.is_dirty()
    assert status.untracked == []


def test_get_status_uses_versioned_machine_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []

    class FakeGitCommand:
        def __init__(
            self, _project: Any, cmdv: List[str], **kwargs: Any
        ) -> None:
            commands.append((cmdv, kwargs))
            self.stdout = b""

        def Wait(self) -> int:
            return 0

    monkeypatch.setattr(git_status, "GitCommand", FakeGitCommand)
    monkeypatch.setattr(git_status, "git_require", lambda _version: True)

    git_status.GetStatus(
        mock.sentinel.project,
        mock.sentinel.gitdir,
        untracked_files="no",
        branch=True,
        ahead_behind=True,
        show_stash=True,
    )

    cmd, kwargs = commands[0]
    assert cmd == [
        "status",
        "--porcelain=v2",
        "-z",
        "--ignore-submodules=all",
        "--untracked-files=no",
        "--branch",
        "--ahead-behind",
        "--renames",
        "--show-stash",
    ]
    assert kwargs["capture_stdout_bytes"]


def test_get_status_rejects_git_before_2_11(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(git_status, "git_require", lambda _version: False)

    with pytest.raises(git_status.UnsupportedStatusError):
        git_status.GetStatus(mock.sentinel.project, mock.sentinel.gitdir)


def test_get_status_omits_stash_header_before_2_35(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []

    class FakeGitCommand:
        def __init__(
            self, _project: Any, cmdv: List[str], **_kwargs: Any
        ) -> None:
            commands.append(cmdv)
            self.stdout = b""

        def Wait(self) -> int:
            return 0

    monkeypatch.setattr(git_status, "GitCommand", FakeGitCommand)
    monkeypatch.setattr(
        git_status,
        "git_require",
        lambda version: version <= (2, 34, 0),
    )

    git_status.GetStatus(
        mock.sentinel.project,
        mock.sentinel.gitdir,
        show_stash=True,
    )

    assert "--show-stash" not in commands[0]
