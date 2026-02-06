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

import functools
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import git_refs


@functools.lru_cache(maxsize=None)
def _supports_reftable():
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        repo = os.path.join(tempdir, "repo")
        proc = subprocess.run(
            ["git", "-c", "init.defaultRefFormat=reftable", "init", "-q", repo],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    return proc.returncode == 0


@functools.lru_cache(maxsize=None)
def _supports_refs_migrate():
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        repo = os.path.join(tempdir, "repo")
        subprocess.check_call(
            ["git", "-c", "init.defaultRefFormat=files", "init", "-q", repo]
        )
        proc = subprocess.run(
            [
                "git",
                "-C",
                repo,
                "refs",
                "migrate",
                "--ref-format=reftable",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    return proc.returncode == 0


class GitRefsTest(unittest.TestCase):
    def _run(self, repo, *args):
        return subprocess.run(
            ["git", "-C", repo, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            check=True,
        ).stdout.strip()

    def _init_repo(self, reftable=False):
        tempdir = tempfile.TemporaryDirectory(prefix="repo-tests")
        self.addCleanup(tempdir.cleanup)
        repo = os.path.join(tempdir.name, "repo")
        if reftable:
            subprocess.check_call(
                [
                    "git",
                    "-c",
                    "init.defaultRefFormat=reftable",
                    "init",
                    "-q",
                    repo,
                ]
            )
        else:
            subprocess.check_call(
                ["git", "-c", "init.defaultRefFormat=files", "init", "-q", repo]
            )

        Path(os.path.join(repo, "a")).write_text("1")
        self._run(repo, "add", "a")
        self._run(
            repo,
            "-c",
            "user.name=Repo",
            "-c",
            "user.email=repo@example.com",
            "commit",
            "-q",
            "-m",
            "init",
        )
        return repo

    def test_reads_refs(self):
        for reftable in (False, True):
            if reftable and not _supports_reftable():
                continue
            with self.subTest(reftable=reftable):
                repo = self._init_repo(reftable=reftable)
                gitdir = os.path.join(repo, ".git")
                refs = git_refs.GitRefs(gitdir)

                branch = self._run(repo, "symbolic-ref", "--short", "HEAD")
                head = self._run(repo, "rev-parse", "HEAD")
                self.assertEqual(f"refs/heads/{branch}", refs.symref("HEAD"))
                self.assertEqual(head, refs.get("HEAD"))
                self.assertEqual(head, refs.get(f"refs/heads/{branch}"))

    def test_updates_when_refs_change(self):
        for reftable in (False, True):
            if reftable and not _supports_reftable():
                continue
            with self.subTest(reftable=reftable):
                repo = self._init_repo(reftable=reftable)
                gitdir = os.path.join(repo, ".git")
                refs = git_refs.GitRefs(gitdir)

                head = self._run(repo, "rev-parse", "HEAD")
                self.assertEqual("", refs.get("refs/heads/topic"))
                self._run(repo, "branch", "topic")
                self.assertEqual(head, refs.get("refs/heads/topic"))
                self._run(repo, "branch", "-D", "topic")
                self.assertEqual("", refs.get("refs/heads/topic"))

    @unittest.skipUnless(
        _supports_refs_migrate(),
        "git refs migrate reftable support is required for this test",
    )
    def test_updates_when_storage_backend_toggles(self):
        repo = self._init_repo(reftable=False)
        gitdir = os.path.join(repo, ".git")
        refs = git_refs.GitRefs(gitdir)

        head = self._run(repo, "rev-parse", "HEAD")
        self.assertEqual("", refs.get("refs/heads/reftable-branch"))
        self._run(repo, "refs", "migrate", "--ref-format=reftable")
        self._run(repo, "branch", "reftable-branch")
        self.assertEqual(head, refs.get("refs/heads/reftable-branch"))

        self.assertEqual("", refs.get("refs/heads/files-branch"))
        self._run(repo, "refs", "migrate", "--ref-format=files")
        self._run(repo, "branch", "files-branch")
        self.assertEqual(head, refs.get("refs/heads/files-branch"))
