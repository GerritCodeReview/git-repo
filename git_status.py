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

"""Read a worktree's state from one machine-readable git status snapshot."""

from collections import OrderedDict
import os
from typing import Iterator, List, Optional, TYPE_CHECKING

from git_command import git_require
from git_command import GitCommand


if TYPE_CHECKING:
    from project import Project


class StatusEntry:
    """The state of one path on one side of the index."""

    def __init__(
        self,
        path: str,
        status: str,
        src_path: Optional[str] = None,
        level: Optional[str] = None,
    ) -> None:
        self.path = path
        self.status = status
        self.src_path = src_path
        self.level = level


class StatusSnapshot:
    """A consistent view of worktree, index, and branch state."""

    def __init__(self) -> None:
        self.index_changes = OrderedDict()
        self.worktree_changes = OrderedDict()
        self.untracked = []
        self.branch_oid = None
        self.branch_head = None
        self.upstream = None
        self.ahead = 0
        self.behind = 0
        self.has_ahead_behind = False
        self.stash_count = 0

    @property
    def current_branch(self) -> Optional[str]:
        if self.branch_head in (None, "(detached)", "(unknown)"):
            return None
        return self.branch_head

    def is_dirty(self, consider_untracked: bool = True) -> bool:
        return bool(
            self.index_changes
            or self.worktree_changes
            or (consider_untracked and self.untracked)
        )


def GetStatus(
    project: "Project",
    gitdir: str,
    untracked_files: str = "all",
    branch: bool = False,
    ahead_behind: bool = False,
    show_stash: bool = False,
) -> StatusSnapshot:
    """Return one machine-readable status snapshot for |project|."""
    if not git_require((2, 11, 0)):
        raise UnsupportedStatusError("porcelain v2 requires Git 2.11")
    cmd = [
        "status",
        "--porcelain=v2",
        "-z",
        "--ignore-submodules=all",
        f"--untracked-files={untracked_files}",
    ]
    if branch:
        cmd.append("--branch")
        if git_require((2, 17, 0)):
            cmd.append(
                "--ahead-behind" if ahead_behind else "--no-ahead-behind"
            )
    if git_require((2, 18, 0)):
        # Match the existing staged diff's explicit rename detection even if
        # status.renames is disabled in the user's config.
        cmd.append("--renames")
    if show_stash and git_require((2, 35, 0)):
        cmd.append("--show-stash")

    p = GitCommand(
        project,
        cmd,
        bare=False,
        gitdir=gitdir,
        capture_stdout=True,
        capture_stdout_bytes=True,
        capture_stderr=True,
        verify_command=True,
    )
    p.Wait()
    return ParsePorcelainV2(p.stdout)


def _Path(value: bytes) -> str:
    """Decode a Git pathname without losing undecodable bytes."""
    return os.fsdecode(value)


def _Status(value: int) -> str:
    """Normalize Git's unchanged markers for repo's status display."""
    char = chr(value)
    return "" if char == "." else char


def _Records(output: bytes) -> Iterator[bytes]:
    if not output:
        return iter(())
    if not output.endswith(b"\0"):
        raise StatusParseError("porcelain v2 output is not NUL terminated")
    records = output.split(b"\0")
    if not records[-1]:
        records.pop()
    return iter(records)


class StatusParseError(ValueError):
    """Raised when machine-readable status output is malformed."""


class UnsupportedStatusError(RuntimeError):
    """Raised when the Git client cannot produce porcelain v2."""


def _Fields(record: bytes, count: int) -> List[bytes]:
    fields = record.split(b" ", count - 1)
    if len(fields) != count:
        raise StatusParseError(f"malformed porcelain v2 record: {record!r}")
    return fields


def _AddTracked(
    status: StatusSnapshot,
    path: str,
    xy: bytes,
    src_path: Optional[str] = None,
    level: Optional[str] = None,
) -> None:
    index_status = _Status(xy[0])
    worktree_status = _Status(xy[1])
    if index_status:
        status.index_changes[path] = StatusEntry(
            path,
            index_status,
            src_path=src_path if index_status in ("R", "C") else None,
            level=level if index_status in ("R", "C") else None,
        )
    if worktree_status:
        status.worktree_changes[path] = StatusEntry(
            path,
            worktree_status,
            src_path=src_path if worktree_status in ("R", "C") else None,
            level=level if worktree_status in ("R", "C") else None,
        )


def ParsePorcelainV2(output: bytes) -> StatusSnapshot:
    """Parse ``git status --porcelain=v2 -z --branch`` output."""
    status = StatusSnapshot()
    records = _Records(output)
    for record in records:
        kind = record[:1]
        if kind == b"#":
            try:
                key, value = record[2:].split(b" ", 1)
            except ValueError as e:
                raise StatusParseError(
                    f"malformed porcelain v2 header: {record!r}"
                ) from e
            if key == b"branch.oid":
                value = value.decode("ascii")
                status.branch_oid = None if value == "(initial)" else value
            elif key == b"branch.head":
                status.branch_head = _Path(value)
            elif key == b"branch.upstream":
                status.upstream = _Path(value)
            elif key == b"branch.ab":
                try:
                    value = value.decode("ascii")
                    ahead, behind = value.split()
                    if ahead != "+?" and behind != "-?":
                        status.ahead = int(ahead)
                        status.behind = -int(behind)
                        status.has_ahead_behind = True
                except ValueError as e:
                    raise StatusParseError(
                        f"malformed porcelain v2 branch.ab record: {record!r}"
                    ) from e
            elif key == b"stash":
                status.stash_count = int(value.decode("ascii"))
            continue

        if kind == b"1":
            fields = _Fields(record, 9)
            xy = fields[1]
            if len(xy) != 2:
                raise StatusParseError(f"invalid status pair: {xy!r}")
            path = _Path(fields[8])
            _AddTracked(status, path, xy)
        elif kind == b"2":
            fields = _Fields(record, 10)
            xy = fields[1]
            if len(xy) != 2:
                raise StatusParseError(f"invalid status pair: {xy!r}")
            score = fields[8][1:].lstrip(b"0") or b"0"
            try:
                src_path = _Path(next(records))
            except StopIteration as e:
                raise StatusParseError(
                    "rename record has no source path"
                ) from e
            path = _Path(fields[9])
            _AddTracked(
                status,
                path,
                xy,
                src_path=src_path,
                level=score.decode("ascii"),
            )
        elif kind == b"u":
            fields = _Fields(record, 11)
            path = _Path(fields[10])
            # The old diff-index/diff-files pair reported unmerged paths on
            # both sides, regardless of porcelain's more specific XY pair.
            status.index_changes[path] = StatusEntry(path, "U")
            status.worktree_changes[path] = StatusEntry(path, "U")
        elif kind == b"?":
            status.untracked.append(_Path(record[2:]))
        elif kind == b"!":
            continue
        else:
            raise StatusParseError(
                f"unknown porcelain v2 record type: {record!r}"
            )
    return status
