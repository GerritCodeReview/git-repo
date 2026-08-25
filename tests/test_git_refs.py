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

"""Unittests for the git_refs.py module."""

import os
from pathlib import Path
import subprocess
from unittest import mock

import pytest
import utils_for_test

import git_refs


def _run(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def _init_repo(tmp_path, reftable=False):
    repo = os.path.join(tmp_path, "repo")
    ref_format = "reftable" if reftable else "files"
    utils_for_test.init_git_tree(repo, ref_format=ref_format)

    Path(os.path.join(repo, "a")).write_text("1")
    _run(repo, "add", "a")
    _run(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.mark.parametrize("reftable", [False, True])
def test_reads_refs(tmp_path, reftable):
    if reftable and not utils_for_test.supports_reftable():
        pytest.skip("reftable not supported")

    repo = _init_repo(tmp_path, reftable=reftable)
    gitdir = os.path.join(repo, ".git")
    refs = git_refs.GitRefs(gitdir)

    branch = _run(repo, "symbolic-ref", "--short", "HEAD")
    head = _run(repo, "rev-parse", "HEAD")
    assert refs.symref("HEAD") == f"refs/heads/{branch}"
    assert refs.get("HEAD") == head
    assert refs.get(f"refs/heads/{branch}") == head


@pytest.mark.parametrize("reftable", [False, True])
def test_reads_detached_head(tmp_path, reftable):
    if reftable and not utils_for_test.supports_reftable():
        pytest.skip("reftable not supported")

    repo = _init_repo(tmp_path, reftable=reftable)
    head = _run(repo, "rev-parse", "HEAD")
    _run(repo, "checkout", "--detach", head)
    refs = git_refs.GitRefs(os.path.join(repo, ".git"))

    assert refs.symref("HEAD") == ""
    assert refs.head == head
    assert refs.get("HEAD") == head


def test_reads_head_with_root_refs_in_one_command(monkeypatch):
    """Git 2.45 and newer include HEAD in the ref snapshot."""
    head = "1" * 40
    commands = []

    class FakeGitCommand:
        def __init__(self, _project, cmdv, **_kwargs):
            commands.append(cmdv)
            self.stdout = (
                f"{head}\0HEAD\0refs/heads/main\n"
                f"{head}\0refs/heads/main\0\n"
            )

        def Wait(self):
            return 0

    monkeypatch.setattr(git_refs, "GitCommand", FakeGitCommand)
    monkeypatch.setattr(git_refs, "git_require", lambda _version: True)
    refs = git_refs.GitRefs("/nonexistent")
    with mock.patch.object(refs, "_ReadSymbolicRef") as read_head:
        assert refs.get("HEAD") == head

    assert commands == [
        [
            "for-each-ref",
            "--include-root-refs",
            "--format=%(objectname)%00%(refname)%00%(symref)",
            "HEAD",
            "refs",
        ]
    ]
    read_head.assert_not_called()


def test_root_ref_snapshot_falls_back_for_unborn_head(monkeypatch):
    """An unborn HEAD still uses symbolic-ref after the ref snapshot."""

    class FakeGitCommand:
        def __init__(self, _project, _cmdv, **_kwargs):
            self.stdout = ""

        def Wait(self):
            return 0

    monkeypatch.setattr(git_refs, "GitCommand", FakeGitCommand)
    monkeypatch.setattr(git_refs, "git_require", lambda _version: True)
    refs = git_refs.GitRefs("/nonexistent")

    def read_head(name):
        assert name == "HEAD"
        refs._symref[name] = "refs/heads/main"

    monkeypatch.setattr(refs, "_ReadSymbolicRef", read_head)

    assert refs.symref("HEAD") == "refs/heads/main"


def test_old_git_keeps_separate_head_fallback(monkeypatch):
    """Git before 2.45 uses the original for-each-ref and HEAD calls."""
    head = "1" * 40
    commands = []

    class FakeGitCommand:
        def __init__(self, _project, cmdv, **_kwargs):
            commands.append(cmdv)
            self.stdout = f"{head}\0refs/heads/main\0\n"

        def Wait(self):
            return 0

    monkeypatch.setattr(git_refs, "GitCommand", FakeGitCommand)
    monkeypatch.setattr(git_refs, "git_require", lambda _version: False)
    refs = git_refs.GitRefs("/nonexistent")

    def read_head(name):
        assert name == "HEAD"
        refs._symref[name] = "refs/heads/main"

    monkeypatch.setattr(refs, "_ReadSymbolicRef", read_head)

    assert refs.get("HEAD") == head
    assert commands == [
        [
            "for-each-ref",
            "--format=%(objectname)%00%(refname)%00%(symref)",
        ]
    ]


@pytest.mark.parametrize("reftable", [False, True])
def test_updates_when_refs_change(tmp_path, reftable):
    if reftable and not utils_for_test.supports_reftable():
        pytest.skip("reftable not supported")

    repo = _init_repo(tmp_path, reftable=reftable)
    gitdir = os.path.join(repo, ".git")
    refs = git_refs.GitRefs(gitdir)

    head = _run(repo, "rev-parse", "HEAD")
    assert refs.get("refs/heads/topic") == ""
    _run(repo, "branch", "topic")
    assert refs.get("refs/heads/topic") == head
    _run(repo, "branch", "-D", "topic")
    assert refs.get("refs/heads/topic") == ""


@pytest.mark.skipif(
    not utils_for_test.supports_refs_migrate(),
    reason="git refs migrate reftable support is required for this test",
)
def test_updates_when_storage_backend_toggles(tmp_path):
    repo = _init_repo(tmp_path, reftable=False)
    gitdir = os.path.join(repo, ".git")
    refs = git_refs.GitRefs(gitdir)

    head = _run(repo, "rev-parse", "HEAD")
    assert refs.get("refs/heads/reftable-branch") == ""
    _run(repo, "refs", "migrate", "--ref-format=reftable")
    _run(repo, "branch", "reftable-branch")
    assert refs.get("refs/heads/reftable-branch") == head

    assert refs.get("refs/heads/files-branch") == ""
    _run(repo, "refs", "migrate", "--ref-format=files")
    _run(repo, "branch", "files-branch")
    assert refs.get("refs/heads/files-branch") == head
