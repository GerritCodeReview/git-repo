# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the project.py module."""

import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple
import unittest
from unittest import mock

import pytest
import utils_for_test

import error
import git_config
import git_trace2_event_log
import manifest_xml
import platform_utils
import project


class FakeProject:
    """A fake for Project for basic functionality."""

    def __init__(self, worktree):
        self.worktree = worktree
        self.gitdir = os.path.join(worktree, ".git")
        self.name = "fakeproject"
        self.work_git = project.Project._GitGetByExec(
            self, bare=False, gitdir=self.gitdir
        )
        self.bare_git = project.Project._GitGetByExec(
            self, bare=True, gitdir=self.gitdir
        )
        self.config = git_config.GitConfig.ForRepository(gitdir=self.gitdir)

    def RelPath(self, local: Optional[bool] = None) -> str:
        return self.name


class ReviewableBranchTests(unittest.TestCase):
    """Check ReviewableBranch behavior."""

    def test_smoke(self):
        """A quick run through everything."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = FakeProject(tempdir)

            # Generate some commits.
            with open(os.path.join(tempdir, "readme"), "w") as fp:
                fp.write("txt")
            fakeproj.work_git.add("readme")
            fakeproj.work_git.commit("-mAdd file")
            fakeproj.work_git.checkout("-b", "work")
            fakeproj.work_git.rm("-f", "readme")
            fakeproj.work_git.commit("-mDel file")

            # Start off with the normal details.
            rb = project.ReviewableBranch(
                fakeproj, fakeproj.config.GetBranch("work"), "main"
            )
            self.assertEqual("work", rb.name)
            self.assertEqual(1, len(rb.commits))
            self.assertIn("Del file", rb.commits[0])
            d = rb.unabbrev_commits
            self.assertEqual(1, len(d))
            short, long = next(iter(d.items()))
            self.assertTrue(long.startswith(short))
            self.assertTrue(rb.base_exists)
            self.assertEqual(["readme"], rb.modified_files)
            # Hard to assert anything useful about this.
            self.assertTrue(rb.date)

            # Now delete the tracking branch!
            fakeproj.work_git.branch("-D", "main")
            rb = project.ReviewableBranch(
                fakeproj, fakeproj.config.GetBranch("work"), "main"
            )
            self.assertEqual(0, len(rb.commits))
            self.assertFalse(rb.base_exists)
            # Hard to assert anything useful about this.
            self.assertTrue(rb.date)

    def test_upload_for_review_forwards_git_event_log(self) -> None:
        """Check UploadForReview passes git_event_log to project."""
        proj = mock.MagicMock(spec=project.Project)
        branch = mock.MagicMock()
        branch.name = "work"
        rb = project.ReviewableBranch(proj, branch, "main")
        mock_event_log = mock.MagicMock()

        rb.UploadForReview(people=([], []), git_event_log=mock_event_log)

        proj.UploadForReview.assert_called_once()
        _, kwargs = proj.UploadForReview.call_args
        self.assertEqual(kwargs.get("git_event_log"), mock_event_log)


class ProjectTests(unittest.TestCase):
    """Check Project behavior."""

    def test_encode_patchset_description(self):
        self.assertEqual(
            project.Project._encode_patchset_description("abcd00!! +"),
            "abcd00%21%21_%2b",
        )

    def test_find_gerrit_urls(self) -> None:
        """Check _FindGerritUrls extracts review URLs from stderr."""
        # Single CL URL from standard push output.
        stderr = (
            "remote:\n"
            "remote: Processing changes: new: 1, refs: 1, done\n"
            "remote:\n"
            "remote: SUCCESS\n"
            "remote:\n"
            "remote:   https://gerrit.example.com/c/git-repo/+/616581"
            " Add telemetry [NEW]\n"
            "remote:\n"
            "To sso://gerrit/git-repo\n"
            " * [new reference]   HEAD -> refs/for/main\n"
        )
        self.assertEqual(
            project.Project._FindGerritUrls(stderr),
            ["https://gerrit.example.com/c/git-repo/+/616581"],
        )

        # Project names containing slashes and nested paths.
        url1 = "https://example.com/c/platform/base/+/12345"
        url2 = "https://example.com/c/vendor/device/raviole/prebuilts/+/987654"
        stderr_nested = f"remote:   {url1}\nremote:   {url2} [NEW]\n"
        self.assertEqual(
            project.Project._FindGerritUrls(stderr_nested),
            [url1, url2],
        )

        # Multiple URLs on same line or custom ports / http schemas.
        stderr_custom = (
            "remote:   https://review.corp:8443/c/platform/manifest/+/4321\n"
            "remote:   http://localhost:8080/c/test-project/+/555\n"
        )
        self.assertEqual(
            project.Project._FindGerritUrls(stderr_custom),
            [
                "https://review.corp:8443/c/platform/manifest/+/4321",
                "http://localhost:8080/c/test-project/+/555",
            ],
        )

        # Non-matching outputs.
        self.assertEqual(project.Project._FindGerritUrls(None), [])
        self.assertEqual(project.Project._FindGerritUrls(""), [])
        self.assertEqual(
            project.Project._FindGerritUrls("Everything up-to-date\n"), []
        )
        self.assertEqual(
            project.Project._FindGerritUrls(
                "https://example.com/not/a/gerrit/url"
            ),
            [],
        )

    def _create_project_for_upload_test(
        self,
    ) -> Tuple[mock.MagicMock, mock.MagicMock]:
        proj = mock.MagicMock(spec=project.Project)
        proj.name = "test-project"
        proj.UserEmail = "test@example.com"
        proj.dest_branch = "refs/heads/main"
        proj.bare_git = mock.MagicMock()
        proj._FindGerritUrls = project.Project._FindGerritUrls

        mock_branch = mock.MagicMock()
        mock_branch.name = "test-branch"
        mock_branch.LocalMerge = "refs/heads/main"
        mock_branch.merge = "refs/heads/main"
        mock_branch.remote.review = "http://review.example.com"
        mock_branch.remote.name = "origin"
        mock_branch.remote.projectname = "test-project"
        mock_branch.remote.ReviewUrl.return_value = (
            "https://review.example.com/test-project"
        )

        proj.GetBranch.return_value = mock_branch
        return proj, mock_branch

    def test_upload_for_review_event_emission(self) -> None:
        """Check UploadForReview emits repo.uploadstate trace2 data events."""
        proj, _ = self._create_project_for_upload_test()

        with mock.patch("project.GitCommand") as mock_git_cmd, mock.patch(
            "project.ReviewableBranch"
        ) as mock_rb_cls:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_cmd.stderr = (
                "remote:   https://example.com/c/test/+/123 [NEW]\n"
                "remote:   https://example.com/c/test/+/124 [NEW]\n"
            )
            mock_git_cmd.return_value = mock_cmd

            mock_rb = mock.MagicMock()
            mock_rb.modified_files = ["file1.txt", "file2.txt"]
            mock_rb_cls.return_value = mock_rb

            mock_event_log = mock.MagicMock()
            project.Project.UploadForReview(
                proj,
                branch="test-branch",
                dryrun=True,
                git_event_log=mock_event_log,
            )

            mock_event_log.LogDataConfigEvents.assert_called_once_with(
                {
                    "cls": (
                        "https://example.com/c/test/+/123,"
                        "https://example.com/c/test/+/124"
                    ),
                    "remote": "origin",
                    "branch": "test-branch",
                    "files": "file1.txt,file2.txt",
                },
                "repo.uploadstate",
            )

    def test_upload_for_review_event_emission_no_cls(self) -> None:
        """Check event emission when stderr contains no review URLs."""
        proj, _ = self._create_project_for_upload_test()

        with mock.patch("project.GitCommand") as mock_git_cmd, mock.patch(
            "project.ReviewableBranch"
        ) as mock_rb_cls:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_cmd.stderr = "Everything up-to-date\n"
            mock_git_cmd.return_value = mock_cmd

            mock_rb = mock.MagicMock()
            mock_rb.modified_files = ["dummy.txt"]
            mock_rb_cls.return_value = mock_rb

            mock_event_log = mock.MagicMock()
            project.Project.UploadForReview(
                proj,
                branch="test-branch",
                dryrun=True,
                git_event_log=mock_event_log,
            )

            mock_event_log.LogDataConfigEvents.assert_called_once_with(
                {
                    "cls": "",
                    "remote": "origin",
                    "branch": "test-branch",
                    "files": "dummy.txt",
                },
                "repo.uploadstate",
            )

    def test_upload_for_review_no_event_log(self) -> None:
        """Check UploadForReview succeeds when git_event_log is None."""
        proj, _ = self._create_project_for_upload_test()

        with mock.patch("project.GitCommand") as mock_git_cmd, mock.patch(
            "project.ReviewableBranch"
        ) as mock_rb_cls:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_cmd.stderr = "remote:   https://example.com/c/test/+/1\n"
            mock_git_cmd.return_value = mock_cmd

            mock_rb = mock.MagicMock()
            mock_rb.modified_files = ["file.txt"]
            mock_rb_cls.return_value = mock_rb

            project.Project.UploadForReview(
                proj,
                branch="test-branch",
                dryrun=True,
                git_event_log=None,
            )

    def test_upload_for_review_tracing_exception_handled(self) -> None:
        """Check exceptions during tracing are caught and do not fail upload."""
        proj, _ = self._create_project_for_upload_test()

        with mock.patch("project.GitCommand") as mock_git_cmd, mock.patch(
            "project.ReviewableBranch"
        ) as mock_rb_cls, mock.patch("project.logger") as mock_logger:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_cmd.stderr = "remote:   https://example.com/c/test/+/1\n"
            mock_git_cmd.return_value = mock_cmd

            mock_rb_cls.side_effect = Exception("failed to inspect branch")

            mock_event_log = mock.MagicMock()
            project.Project.UploadForReview(
                proj,
                branch="test-branch",
                dryrun=True,
                git_event_log=mock_event_log,
            )

            mock_logger.error.assert_called_once()
            mock_event_log.LogDataConfigEvents.assert_not_called()

    def test_upload_for_review_real_event_log(self) -> None:
        """Check integration with real git_trace2_event_log.EventLog."""
        proj, _ = self._create_project_for_upload_test()

        with mock.patch("project.GitCommand") as mock_git_cmd, mock.patch(
            "project.ReviewableBranch"
        ) as mock_rb_cls:
            mock_cmd = mock.MagicMock()
            mock_cmd.Wait.return_value = 0
            mock_cmd.stderr = (
                "remote:   https://example.com/c/test/+/456 [NEW]\n"
            )
            mock_git_cmd.return_value = mock_cmd

            mock_rb = mock.MagicMock()
            mock_rb.modified_files = ["file1.py", "file2.py"]
            mock_rb_cls.return_value = mock_rb

            event_log = git_trace2_event_log.EventLog(env={})
            project.Project.UploadForReview(
                proj,
                branch="test-branch",
                dryrun=True,
                git_event_log=event_log,
            )

            data_events = [
                e for e in event_log._log if e.get("event") == "data"
            ]
            data_map = {e["key"]: e["value"] for e in data_events}
            self.assertEqual(
                data_map.get("repo.uploadstate/cls"),
                "https://example.com/c/test/+/456",
            )
            self.assertEqual(data_map.get("repo.uploadstate/remote"), "origin")
            self.assertEqual(
                data_map.get("repo.uploadstate/branch"), "test-branch"
            )
            self.assertEqual(
                data_map.get("repo.uploadstate/files"), "file1.py,file2.py"
            )

    def test_get_head_revision_id(self):
        """Check GetHeadRevisionId behavior."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)

            # Initially unborn HEAD should return None.
            self.assertIsNone(proj.GetHeadRevisionId())

            # Create a commit.
            with open(os.path.join(tempdir, "readme"), "w") as fp:
                fp.write("hello")
            proj.work_git.add("readme")
            proj.work_git.commit("-m", "initial commit")

            # HEAD should resolve to the commit SHA.
            commit_sha = proj.work_git.rev_parse("HEAD")
            self.assertEqual(commit_sha, proj.GetHeadRevisionId())

            # Even if worktree is detached.
            proj.work_git.checkout("HEAD~0")
            self.assertEqual(commit_sha, proj.GetHeadRevisionId())

    @unittest.skipUnless(
        utils_for_test.supports_reftable(),
        "git reftable support is required for this test",
    )
    def test_get_head_unborn_reftable(self):
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            subprocess.check_call(
                [
                    "git",
                    "-c",
                    "init.defaultRefFormat=reftable",
                    "init",
                    "-q",
                    tempdir,
                ]
            )
            fakeproj = FakeProject(tempdir)
            expected = subprocess.check_output(
                ["git", "-C", tempdir, "symbolic-ref", "-q", "HEAD"],
                encoding="utf-8",
            ).strip()
            self.assertEqual(expected, fakeproj.work_git.GetHead())

    def test_parse_head(self) -> None:
        """Verify _ParseHead parses refs, hashes, whitespace, and invalid
        refs.
        """
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            fakeproj = FakeProject(tempdir)
            work_git = fakeproj.work_git

            # Standard symbolic ref
            self.assertEqual(
                work_git._ParseHead("ref: refs/heads/main\n"),
                "refs/heads/main",
            )

            # Tabs and extra whitespace
            self.assertEqual(
                work_git._ParseHead("ref:\t  refs/heads/branch  \r\n"),
                "refs/heads/branch",
            )

            # Reftables placeholder should return None
            self.assertIsNone(work_git._ParseHead("ref: refs/heads/.invalid\n"))

            # Empty or whitespace-only symbolic refs should return None
            self.assertIsNone(work_git._ParseHead("ref:\n"))
            self.assertIsNone(work_git._ParseHead("ref:   \t  \r\n"))

            # 40-character SHA-1
            sha1 = "0123456789abcdef0123456789abcdef01234567"
            self.assertEqual(work_git._ParseHead(f"{sha1}\n"), sha1)

            # Uppercase SHA-1 normalized to lowercase
            sha_upper = "4B825DC642CB6EB9A060E54BF8D69288FBEE4904"
            self.assertEqual(
                work_git._ParseHead(f"{sha_upper}\r\n"), sha_upper.lower()
            )

            # 64-character SHA-256
            sha256 = "0123456789abcdef" * 4
            self.assertEqual(work_git._ParseHead(f"{sha256}\n"), sha256)

            # 40-character string with invalid hex characters (e.g. 'g'-'z')
            invalid_sha = "0123456789abcdef0123456789abcdef0123456z"
            self.assertIsNone(work_git._ParseHead(f"{invalid_sha}\n"))

            # Empty or unparseable lines
            self.assertIsNone(work_git._ParseHead(""))
            self.assertIsNone(work_git._ParseHead("   \n"))
            self.assertIsNone(work_git._ParseHead("corrupted-not-a-hash"))

    def test_get_head_in_memory_fast_path(self) -> None:
        """Verify GetHead reads HEAD in-memory without spawning subprocesses."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            fakeproj = FakeProject(tempdir)
            os.makedirs(fakeproj.gitdir, exist_ok=True)
            head_file = os.path.join(fakeproj.gitdir, "HEAD")

            # 1. Standard symbolic ref (on a branch)
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write("ref: refs/heads/feature-branch\n")

            with mock.patch.object(
                fakeproj.work_git, "symbolic_ref"
            ) as mock_sym, mock.patch.object(
                fakeproj.work_git, "rev_parse"
            ) as mock_parse:
                self.assertEqual(
                    fakeproj.work_git.GetHead(), "refs/heads/feature-branch"
                )
                mock_sym.assert_not_called()
                mock_parse.assert_not_called()

            # 2. Whitespace, tabs, and CRLF handling
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write("ref:\t refs/heads/feature-branch  \r\n")

            with mock.patch.object(
                fakeproj.work_git, "symbolic_ref"
            ) as mock_sym, mock.patch.object(
                fakeproj.work_git, "rev_parse"
            ) as mock_parse:
                self.assertEqual(
                    fakeproj.work_git.GetHead(), "refs/heads/feature-branch"
                )
                mock_sym.assert_not_called()
                mock_parse.assert_not_called()

            # 3. Detached HEAD with 40-character SHA-1
            fake_sha1 = "0123456789abcdef0123456789abcdef01234567"
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write(f"{fake_sha1}\n")

            with mock.patch.object(
                fakeproj.work_git, "symbolic_ref"
            ) as mock_sym, mock.patch.object(
                fakeproj.work_git, "rev_parse"
            ) as mock_parse:
                self.assertEqual(fakeproj.work_git.GetHead(), fake_sha1)
                mock_sym.assert_not_called()
                mock_parse.assert_not_called()

            # 4. Detached HEAD with 64-character SHA-256
            fake_sha256 = "0123456789abcdef" * 4
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write(f"{fake_sha256}\n")

            with mock.patch.object(
                fakeproj.work_git, "symbolic_ref"
            ) as mock_sym, mock.patch.object(
                fakeproj.work_git, "rev_parse"
            ) as mock_parse:
                self.assertEqual(fakeproj.work_git.GetHead(), fake_sha256)
                mock_sym.assert_not_called()
                mock_parse.assert_not_called()

            # 5. Uppercase SHA normalized to lowercase
            fake_upper = fake_sha1.upper()
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write(f"{fake_upper}\n")

            with mock.patch.object(
                fakeproj.work_git, "symbolic_ref"
            ) as mock_sym, mock.patch.object(
                fakeproj.work_git, "rev_parse"
            ) as mock_parse:
                self.assertEqual(fakeproj.work_git.GetHead(), fake_sha1)
                mock_sym.assert_not_called()
                mock_parse.assert_not_called()

    def test_get_head_symlink_and_fallback(self) -> None:
        """Verify GetHead handles symlinks and invalid files via fallback."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            fakeproj = FakeProject(tempdir)
            os.makedirs(fakeproj.gitdir, exist_ok=True)
            head_file = os.path.join(fakeproj.gitdir, "HEAD")

            # Symlink HEAD should fall back to symbolic_ref
            platform_utils.symlink("refs/heads/main", head_file)
            with mock.patch.object(
                fakeproj.work_git,
                "symbolic_ref",
                return_value="refs/heads/main",
            ) as mock_sym:
                self.assertEqual(fakeproj.work_git.GetHead(), "refs/heads/main")
                mock_sym.assert_called_once()

    def test_get_head_worktree_corrupted_fallback(self) -> None:
        """Verify GetHead raises NoManifestException on corrupted worktrees."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            dotgit = os.path.join(tempdir, ".git")
            with open(dotgit, "w", encoding="utf-8", newline="") as fp:
                fp.write("malformed without gitdir prefix\n")
            fakeproj = FakeProject(tempdir)
            with self.assertRaises(error.NoManifestException) as cm:
                fakeproj.work_git.GetHead()
            self.assertEqual(cm.exception.path, fakeproj.RelPath(local=False))

    def test_get_head_fallback_robustness(self) -> None:
        """Verify GetHead fallback handles CRLF, tabs, and lowercase hashes."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            fakeproj = FakeProject(tempdir)
            os.makedirs(fakeproj.gitdir, exist_ok=True)
            head_file = os.path.join(fakeproj.gitdir, "HEAD")

            # 1. Fallback strips tabs, extra whitespace, and CRLF
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write("ref:\t  refs/heads/fallback-branch\r\n")

            with mock.patch("platform_utils.islink", return_value=True):
                with mock.patch.object(
                    fakeproj.work_git,
                    "symbolic_ref",
                    side_effect=error.GitError("sym error"),
                ), mock.patch.object(
                    fakeproj.work_git,
                    "rev_parse",
                    side_effect=error.GitError("parse error"),
                ):
                    self.assertEqual(
                        fakeproj.work_git.GetHead(),
                        "refs/heads/fallback-branch",
                    )

            # 2. Fallback normalizes uppercase hashes to lowercase
            sha_upper = "4B825DC642CB6EB9A060E54BF8D69288FBEE4904"
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write(f"{sha_upper}\r\n")

            with mock.patch("platform_utils.islink", return_value=True):
                with mock.patch.object(
                    fakeproj.work_git,
                    "symbolic_ref",
                    side_effect=error.GitError("sym error"),
                ), mock.patch.object(
                    fakeproj.work_git,
                    "rev_parse",
                    side_effect=error.GitError("parse error"),
                ):
                    self.assertEqual(
                        fakeproj.work_git.GetHead(), sha_upper.lower()
                    )

            # 3. Fallback raises NoManifestException with RelPath on .invalid
            with open(head_file, "w", encoding="utf-8", newline="") as fp:
                fp.write("ref: refs/heads/.invalid\r\n")

            with mock.patch("platform_utils.islink", return_value=True):
                with mock.patch.object(
                    fakeproj.work_git,
                    "symbolic_ref",
                    side_effect=error.GitError("sym error"),
                ), mock.patch.object(
                    fakeproj.work_git,
                    "rev_parse",
                    side_effect=error.GitError("parse error"),
                ):
                    with self.assertRaises(error.NoManifestException) as cm:
                        fakeproj.work_git.GetHead()
                    self.assertEqual(
                        cm.exception.path, fakeproj.RelPath(local=False)
                    )

    def _get_derived_subproject_url(self, submodule_url):
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:

            class FakeManifest:
                def __init__(self, topdir):
                    self.topdir = topdir
                    self.globalConfig = None
                    self.is_multimanifest = False
                    self.path_prefix = ""
                    self.paths = {}

                def GetSubprojectName(self, parent, path):
                    return path

                def GetSubprojectPaths(self, parent, name, path):
                    relpath = path
                    worktree = os.path.join(self.topdir, path)
                    gitdir = os.path.join(self.topdir, f"{path}.git")
                    objdir = os.path.join(self.topdir, f"{path}.obj")
                    os.makedirs(worktree, exist_ok=True)
                    os.makedirs(gitdir, exist_ok=True)
                    os.makedirs(objdir, exist_ok=True)
                    return relpath, worktree, gitdir, objdir

            manifest = FakeManifest(tempdir)
            worktree = os.path.join(tempdir, "parent")
            gitdir = os.path.join(tempdir, "parent.git")
            objdir = os.path.join(tempdir, "parent.obj")
            os.makedirs(worktree)
            os.makedirs(gitdir)
            os.makedirs(objdir)

            parent = project.Project(
                manifest=manifest,
                name="parent",
                remote=project.RemoteSpec(
                    "origin", url="https://example.com/platform/superproject"
                ),
                gitdir=gitdir,
                objdir=objdir,
                worktree=worktree,
                relpath="parent",
                revisionExpr="refs/heads/main",
                revisionId=None,
            )

            def fake_get_submodules(current):
                if current is parent:
                    return [("subrev", "child", submodule_url, "false")]
                return []

            with mock.patch.object(
                project.Project, "_GetSubmodules", autospec=True
            ) as get_submodules:
                get_submodules.side_effect = fake_get_submodules
                result = parent.GetDerivedSubprojects()

            self.assertEqual(1, len(result))
            return result[0].remote.url

    def test_derived_subproject_joins_only_git_relative_urls(self):
        tests = (
            (
                "./submodule",
                "https://example.com/platform/superproject/submodule",
            ),
            ("../sibling", "https://example.com/platform/sibling"),
        )
        for submodule_url, expected in tests:
            with self.subTest(submodule_url=submodule_url):
                self.assertEqual(
                    expected, self._get_derived_subproject_url(submodule_url)
                )

    def test_derived_subproject_leaves_dot_prefixed_names_unchanged(self):
        for submodule_url in (".foo", "..bar"):
            with self.subTest(submodule_url=submodule_url):
                self.assertEqual(
                    submodule_url,
                    self._get_derived_subproject_url(submodule_url),
                )


class CopyLinkTestCase(unittest.TestCase):
    """TestCase for stub repo client checkouts.

    It'll have a layout like this:
      tempdir/          # self.tempdir
        checkout/       # self.topdir
          git-project/  # self.worktree

    Attributes:
      tempdir: A dedicated temporary directory.
      worktree: The top of the repo client checkout.
      topdir: The top of a project checkout.
    """

    def setUp(self):
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.tempdir = self.tempdirobj.name
        self.topdir = os.path.join(self.tempdir, "checkout")
        self.worktree = os.path.join(self.topdir, "git-project")
        os.makedirs(self.topdir)
        os.makedirs(self.worktree)

    def tearDown(self):
        self.tempdirobj.cleanup()

    @staticmethod
    def touch(path):
        with open(path, "w"):
            pass

    def assertExists(self, path, msg=None):
        """Make sure |path| exists."""
        if os.path.exists(path):
            return

        if msg is None:
            msg = ["path is missing: %s" % path]
            while path != "/":
                path = os.path.dirname(path)
                if not path:
                    # If we're given something like "foo", abort once we get to
                    # "".
                    break
                result = os.path.exists(path)
                msg.append(f"\tos.path.exists({path}): {result}")
                if result:
                    msg.append("\tcontents: %r" % os.listdir(path))
                    break
            msg = "\n".join(msg)

        raise self.failureException(msg)


class CopyFile(CopyLinkTestCase):
    """Check _CopyFile handling."""

    def CopyFile(self, src, dest):
        return project._CopyFile(self.worktree, src, self.topdir, dest)

    def test_basic(self):
        """Basic test of copying a file from a project to the toplevel."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        cf = self.CopyFile("foo.txt", "foo")
        cf._Copy()
        self.assertExists(os.path.join(self.topdir, "foo"))

    def test_src_subdir(self):
        """Copy a file from a subdir of a project."""
        src = os.path.join(self.worktree, "bar", "foo.txt")
        os.makedirs(os.path.dirname(src))
        self.touch(src)
        cf = self.CopyFile("bar/foo.txt", "new.txt")
        cf._Copy()
        self.assertExists(os.path.join(self.topdir, "new.txt"))

    def test_dest_subdir(self):
        """Copy a file to a subdir of a checkout."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        cf = self.CopyFile("foo.txt", "sub/dir/new.txt")
        self.assertFalse(os.path.exists(os.path.join(self.topdir, "sub")))
        cf._Copy()
        self.assertExists(os.path.join(self.topdir, "sub", "dir", "new.txt"))

    def test_update(self):
        """Make sure changed files get copied again."""
        src = os.path.join(self.worktree, "foo.txt")
        dest = os.path.join(self.topdir, "bar")
        with open(src, "w") as f:
            f.write("1st")
        cf = self.CopyFile("foo.txt", "bar")
        cf._Copy()
        self.assertExists(dest)
        with open(dest) as f:
            self.assertEqual(f.read(), "1st")

        with open(src, "w") as f:
            f.write("2nd!")
        cf._Copy()
        with open(dest) as f:
            self.assertEqual(f.read(), "2nd!")

    def test_src_block_symlink(self):
        """Do not allow reading from a symlinked path."""
        src = os.path.join(self.worktree, "foo.txt")
        sym = os.path.join(self.worktree, "sym")
        self.touch(src)
        platform_utils.symlink("foo.txt", sym)
        self.assertExists(sym)
        cf = self.CopyFile("sym", "foo")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_src_block_symlink_traversal(self):
        """Do not allow reading through a symlink dir."""
        realfile = os.path.join(self.tempdir, "file.txt")
        self.touch(realfile)
        src = os.path.join(self.worktree, "bar", "file.txt")
        platform_utils.symlink(self.tempdir, os.path.join(self.worktree, "bar"))
        self.assertExists(src)
        cf = self.CopyFile("bar/file.txt", "foo")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_src_block_copy_from_dir(self):
        """Do not allow copying from a directory."""
        src = os.path.join(self.worktree, "dir")
        os.makedirs(src)
        cf = self.CopyFile("dir", "foo")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_dest_block_symlink(self):
        """Do not allow writing to a symlink."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        platform_utils.symlink("dest", os.path.join(self.topdir, "sym"))
        cf = self.CopyFile("foo.txt", "sym")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_dest_block_symlink_traversal(self):
        """Do not allow writing through a symlink dir."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        platform_utils.symlink(
            tempfile.gettempdir(), os.path.join(self.topdir, "sym")
        )
        cf = self.CopyFile("foo.txt", "sym/foo.txt")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_src_block_copy_to_dir(self):
        """Do not allow copying to a directory."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        os.makedirs(os.path.join(self.topdir, "dir"))
        cf = self.CopyFile("foo.txt", "dir")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)


class LinkFile(CopyLinkTestCase):
    """Check _LinkFile handling."""

    def LinkFile(self, src, dest):
        return project._LinkFile(self.worktree, src, self.topdir, dest)

    def test_basic(self):
        """Basic test of linking a file from a project into the toplevel."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "foo")
        lf._Link()
        dest = os.path.join(self.topdir, "foo")
        self.assertExists(dest)
        self.assertTrue(os.path.islink(dest))
        self.assertEqual(
            os.path.join("git-project", "foo.txt"), os.readlink(dest)
        )

    def test_src_subdir(self):
        """Link to a file in a subdir of a project."""
        src = os.path.join(self.worktree, "bar", "foo.txt")
        os.makedirs(os.path.dirname(src))
        self.touch(src)
        lf = self.LinkFile("bar/foo.txt", "foo")
        lf._Link()
        self.assertExists(os.path.join(self.topdir, "foo"))

    def test_src_self(self):
        """Link to the project itself."""
        dest = os.path.join(self.topdir, "foo", "bar")
        lf = self.LinkFile(".", "foo/bar")
        lf._Link()
        self.assertExists(dest)
        self.assertEqual(os.path.join("..", "git-project"), os.readlink(dest))

    def test_dest_subdir(self):
        """Link a file to a subdir of a checkout."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "sub/dir/foo/bar")
        self.assertFalse(os.path.exists(os.path.join(self.topdir, "sub")))
        lf._Link()
        self.assertExists(os.path.join(self.topdir, "sub", "dir", "foo", "bar"))

    def test_src_block_relative(self):
        """Do not allow relative symlinks."""
        BAD_SOURCES = (
            "./",
            "..",
            "../",
            "foo/.",
            "foo/./bar",
            "foo/..",
            "foo/../foo",
        )
        for src in BAD_SOURCES:
            lf = self.LinkFile(src, "foo")
            self.assertRaises(error.ManifestInvalidPathError, lf._Link)

    def test_update(self):
        """Make sure changed targets get updated."""
        dest = os.path.join(self.topdir, "sym")

        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "sym")
        lf._Link()
        self.assertEqual(
            os.path.join("git-project", "foo.txt"), os.readlink(dest)
        )

        # Point the symlink somewhere else.
        os.unlink(dest)
        platform_utils.symlink(self.tempdir, dest)
        lf._Link()
        self.assertEqual(
            os.path.join("git-project", "foo.txt"), os.readlink(dest)
        )

    def test_replace_empty_dir_with_symlink(self):
        """A linkfile should replace an empty real directory at the dest path.

        This is the common case: the old linkfiles inside the directory were
        already cleaned up by UpdateCopyLinkfileList, leaving an empty parent
        directory behind.
        """
        src_dir = os.path.join(self.worktree, "dot-llms")
        os.makedirs(src_dir)

        dest = os.path.join(self.topdir, "mydir")
        os.makedirs(dest)

        lf = self.LinkFile("dot-llms", "mydir")
        lf._Link()
        self.assertTrue(os.path.islink(dest))
        self.assertEqual(
            os.path.join("git-project", "dot-llms"), os.readlink(dest)
        )

    def test_nonempty_dir_not_clobbered(self):
        """A linkfile must not delete a non-empty directory.

        If the user created files in a directory that a new linkfile wants
        to replace, __linkIt should fail safely rather than deleting content.
        """
        src_dir = os.path.join(self.worktree, "dot-llms")
        os.makedirs(src_dir)

        dest = os.path.join(self.topdir, "mydir")
        os.makedirs(dest)
        user_file = os.path.join(dest, "user-notes.txt")
        self.touch(user_file)

        lf = self.LinkFile("dot-llms", "mydir")
        lf._Link()
        # The directory should NOT be replaced — user content is preserved.
        self.assertFalse(os.path.islink(dest))
        self.assertTrue(os.path.isdir(dest))
        self.assertTrue(os.path.exists(user_file))


class MigrateWorkTreeTests(unittest.TestCase):
    """Check _MigrateOldWorkTreeGitDir handling."""

    _SYMLINKS = {
        # go/keep-sorted start
        "config",
        "description",
        "hooks",
        "info",
        "logs",
        "objects",
        "packed-refs",
        "refs",
        "reftable",
        "rr-cache",
        "shallow",
        "svn",
        # go/keep-sorted end
    }
    _FILES = {
        "COMMIT_EDITMSG",
        "FETCH_HEAD",
        "HEAD",
        "index",
        "ORIG_HEAD",
        "unknown-file-should-be-migrated",
    }
    _CLEAN_FILES = {
        "a-vim-temp-file~",
        "#an-emacs-temp-file#",
    }

    @classmethod
    @contextlib.contextmanager
    def _simple_layout(cls):
        """Create a simple repo client checkout to test against."""
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir = Path(tempdir)

            gitdir = tempdir / ".repo/projects/src/test.git"
            gitdir.mkdir(parents=True)
            cmd = ["git", "init", "--bare", str(gitdir)]
            subprocess.check_call(cmd)

            dotgit = tempdir / "src/test/.git"
            dotgit.mkdir(parents=True)
            for name in cls._SYMLINKS:
                (dotgit / name).symlink_to(
                    f"../../../.repo/projects/src/test.git/{name}"
                )
            for name in cls._FILES | cls._CLEAN_FILES:
                (dotgit / name).write_text(name)

            yield tempdir

    def test_standard(self):
        """Migrate a standard checkout that we expect."""
        with self._simple_layout() as tempdir:
            dotgit = tempdir / "src/test/.git"
            project.Project._MigrateOldWorkTreeGitDir(str(dotgit))

            # Make sure the dir was transformed into a symlink.
            self.assertTrue(dotgit.is_symlink())
            self.assertEqual(
                os.readlink(dotgit),
                os.path.normpath("../../.repo/projects/src/test.git"),
            )

            # Make sure files were moved over.
            gitdir = tempdir / ".repo/projects/src/test.git"
            for name in self._FILES:
                self.assertEqual(name, (gitdir / name).read_text())
            # Make sure files were removed.
            for name in self._CLEAN_FILES:
                self.assertFalse((gitdir / name).exists())

    def test_unknown(self):
        """A checkout with unknown files should abort."""
        with self._simple_layout() as tempdir:
            dotgit = tempdir / "src/test/.git"
            (tempdir / ".repo/projects/src/test.git/random-file").write_text(
                "one"
            )
            (dotgit / "random-file").write_text("two")
            with self.assertRaises(error.GitError):
                project.Project._MigrateOldWorkTreeGitDir(str(dotgit))

            # Make sure no content was actually changed.
            self.assertTrue(dotgit.is_dir())
            for name in self._FILES:
                self.assertTrue((dotgit / name).is_file())
            for name in self._CLEAN_FILES:
                self.assertTrue((dotgit / name).is_file())
            for name in self._SYMLINKS:
                self.assertTrue((dotgit / name).is_symlink())

    def test_reftable_anchor_with_refs_dir(self):
        """Migrate when reftable/ and refs/ are directories."""
        with self._simple_layout() as tempdir:
            dotgit = tempdir / "src/test/.git"
            (dotgit / "refs").unlink()
            (dotgit / "refs").mkdir()
            (dotgit / "refs" / "heads").write_text("dummy")

            (dotgit / "reftable").unlink()
            (dotgit / "reftable").mkdir()
            (dotgit / "reftable" / "tables.list").write_text("dummy")
            project.Project._MigrateOldWorkTreeGitDir(str(dotgit))

            self.assertTrue(dotgit.is_symlink())
            self.assertEqual(
                os.readlink(dotgit),
                os.path.normpath("../../.repo/projects/src/test.git"),
            )


class ManifestPropertiesFetchedCorrectly(unittest.TestCase):
    """Ensure properties are fetched properly."""

    def setUpManifest(self, tempdir):
        repodir = os.path.join(tempdir, ".repo")
        manifest_dir = os.path.join(repodir, "manifests")
        manifest_file = os.path.join(repodir, manifest_xml.MANIFEST_FILE_NAME)
        os.mkdir(repodir)
        os.mkdir(manifest_dir)
        manifest = manifest_xml.XmlManifest(repodir, manifest_file)

        return project.ManifestProject(
            manifest, "test/manifest", os.path.join(tempdir, ".git"), tempdir
        )

    def test_manifest_config_properties(self):
        """Test we are fetching the manifest config properties correctly."""

        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)

            # Set property using the expected Set method, then ensure
            # the porperty functions are using the correct Get methods.
            fakeproj.config.SetString(
                "manifest.standalone", "https://chicken/manifest.git"
            )
            self.assertEqual(
                fakeproj.standalone_manifest_url, "https://chicken/manifest.git"
            )

            fakeproj.config.SetString(
                "manifest.groups", "test-group, admin-group"
            )
            self.assertEqual(
                fakeproj.manifest_groups, "test-group, admin-group"
            )

            fakeproj.config.SetString("repo.reference", "mirror/ref")
            self.assertEqual(fakeproj.reference, "mirror/ref")

            fakeproj.config.SetBoolean("repo.dissociate", False)
            self.assertFalse(fakeproj.dissociate)

            fakeproj.config.SetBoolean("repo.archive", False)
            self.assertFalse(fakeproj.archive)

            fakeproj.config.SetBoolean("repo.mirror", False)
            self.assertFalse(fakeproj.mirror)

            fakeproj.config.SetBoolean("repo.worktree", False)
            self.assertFalse(fakeproj.use_worktree)

            fakeproj.config.SetBoolean("repo.uselocalgitdirs", False)
            self.assertFalse(fakeproj.use_local_gitdirs)

            fakeproj.config.SetBoolean("repo.clonebundle", False)
            self.assertFalse(fakeproj.clone_bundle)

            fakeproj.config.SetBoolean("repo.submodules", False)
            self.assertFalse(fakeproj.submodules)

            fakeproj.config.SetBoolean("repo.git-lfs", False)
            self.assertFalse(fakeproj.git_lfs)

            fakeproj.config.SetBoolean("repo.superproject", False)
            self.assertFalse(fakeproj.use_superproject)

            fakeproj.config.SetBoolean("repo.partialclone", False)
            self.assertFalse(fakeproj.partial_clone)

            fakeproj.config.SetString("repo.depth", "48")
            self.assertEqual(fakeproj.depth, 48)

            fakeproj.config.SetString("repo.depth", "invalid_depth")
            self.assertEqual(fakeproj.depth, None)

            fakeproj.config.SetString("repo.clonefilter", "blob:limit=10M")
            self.assertEqual(fakeproj.clone_filter, "blob:limit=10M")

            fakeproj.config.SetString(
                "repo.partialcloneexclude", "third_party/big_repo"
            )
            self.assertEqual(
                fakeproj.partial_clone_exclude, "third_party/big_repo"
            )

            fakeproj.config.SetString("manifest.platform", "auto")
            self.assertEqual(fakeproj.manifest_platform, "auto")

    def test_check_immutable_revision_metaproject_skips_manifest_load(self):
        """MetaProjects must not parse manifest.xml during immutable check.

        During `repo init` the manifestProject's own Sync_NetworkHalf runs
        before manifest.xml has been linked into .repo/, so
        _CheckForImmutableRevision must not touch it.
        """

        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)
            manifest_path = os.path.join(
                tempdir, ".repo", manifest_xml.MANIFEST_FILE_NAME
            )
            self.assertFalse(os.path.exists(manifest_path))

            fakeproj.revisionExpr = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
            fakeproj.upstream = "refs/heads/main"

            # Must return False without raising ManifestParseError, and
            # must leave the absent manifest.xml untouched.
            self.assertFalse(
                fakeproj._CheckForImmutableRevision(use_superproject=None)
            )
            self.assertFalse(os.path.exists(manifest_path))

    def test_get_upstream_fallback_metaproject_skips_manifest_load(
        self,
    ) -> None:
        """MetaProjects must not parse manifest.xml during upstream fallback."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)
            manifest_path = os.path.join(
                tempdir, ".repo", manifest_xml.MANIFEST_FILE_NAME
            )
            self.assertFalse(os.path.exists(manifest_path))

            self.assertIsNone(fakeproj._GetUpstreamFallback())
            self.assertFalse(os.path.exists(manifest_path))

    def test_sharing_project_has_shallow_metaproject_skips_manifest_load(
        self,
    ) -> None:
        """MetaProjects must not parse manifest.xml during sharing shallow
        check."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)
            manifest_path = os.path.join(
                tempdir, ".repo", manifest_xml.MANIFEST_FILE_NAME
            )
            self.assertFalse(os.path.exists(manifest_path))

            self.assertFalse(fakeproj._SharingProjectHasShallow())
            self.assertFalse(os.path.exists(manifest_path))

    def test_sync_use_local_gitdirs_worktree_conflict(self):
        """Test that --use-local-gitdirs conflicts with --worktree."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)

            class DummyManifest:
                is_submanifest = False

                def GetDefaultGroupsStr(self, with_platform=False):
                    return ""

            fakeproj.manifest = DummyManifest()

            result = fakeproj.Sync(use_local_gitdirs=True, worktree=True)
            self.assertFalse(result)

    def test_sync_use_local_gitdirs_archive_conflict(self):
        """Test that --use-local-gitdirs conflicts with --archive."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)

            class DummyManifest:
                is_submanifest = False

                def GetDefaultGroupsStr(self, with_platform=False):
                    return ""

            fakeproj.manifest = DummyManifest()

            result = fakeproj.Sync(use_local_gitdirs=True, archive=True)
            self.assertFalse(result)

    def test_sync_use_local_gitdirs_mirror_conflict(self):
        """Test that --use-local-gitdirs conflicts with --mirror."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)

            class DummyManifest:
                is_submanifest = False

                def GetDefaultGroupsStr(self, with_platform=False):
                    return ""

            fakeproj.manifest = DummyManifest()

            result = fakeproj.Sync(use_local_gitdirs=True, mirror=True)
            self.assertFalse(result)

    def test_delete_worktree_corrupted(self):
        """Test DeleteWorktree gracefully handles corrupted projects."""
        for use_git_worktrees in (False, True):
            with self.subTest(use_git_worktrees=use_git_worktrees):
                with utils_for_test.TempGitTree() as tempdir:
                    proj = _create_mock_project(tempdir)
                    os.makedirs(os.path.join(tempdir, "worktree"))
                    os.makedirs(os.path.join(tempdir, "gitdir"))
                    proj.worktree = os.path.join(tempdir, "worktree")
                    proj.gitdir = os.path.join(tempdir, "gitdir")
                    proj.use_git_worktrees = use_git_worktrees

                    with mock.patch.object(
                        proj,
                        "IsDirty",
                        side_effect=error.GitError("mock error"),
                    ):
                        with self.assertRaises(project.DeleteWorktreeError):
                            proj.DeleteWorktree(force=False)

                        self.assertTrue(proj.DeleteWorktree(force=True))
                        self.assertFalse(os.path.exists(proj.worktree))
                        self.assertFalse(os.path.exists(proj.gitdir))


_VAR_CMD: List[str] = ["var", "GIT_DEFAULT_BRANCH"]
_CONFIG_CMD: List[str] = ["config", "--get", "init.defaultBranch"]


@pytest.mark.parametrize(
    "responses, expected_ref, expected_calls",
    (
        # git >= 2.35 answers `git var GIT_DEFAULT_BRANCH`.
        ({"var": (0, "jellybean\n")}, "refs/heads/jellybean", [_VAR_CMD]),
        # Older git: `git var` fails, so read init.defaultBranch instead.
        (
            {"var": (1, ""), "config": (0, "custom\n")},
            "refs/heads/custom",
            [_VAR_CMD, _CONFIG_CMD],
        ),
        # Nothing configured anywhere: git's historical built-in default.
        (
            {"var": (1, ""), "config": (1, "")},
            "refs/heads/master",
            [_VAR_CMD, _CONFIG_CMD],
        ),
    ),
    ids=("git_var", "old_git_reads_config", "unconfigured_defaults_to_master"),
)
def test_default_branch_fallback(
    responses: Dict[str, Tuple[int, str]],
    expected_ref: str,
    expected_calls: List[List[str]],
) -> None:
    """_DefaultBranchFallback resolves the default branch via git."""
    seen: List[List[str]] = []

    class FakeGitCommand:
        # Emulate git by returning the canned response for the subcommand.
        def __init__(
            self, project_: Optional[project.Project], cmdv: List[str], **kwargs
        ) -> None:
            self.returncode, self.stdout = responses[cmdv[0]]
            seen.append(cmdv)

        def Wait(self) -> int:
            return self.returncode

    # The result is memoized, so clear it before (to bypass any cached real
    # value) and after (so the mocked value doesn't leak to other tests).
    project._DefaultBranchFallback.cache_clear()
    try:
        with mock.patch.object(project, "GitCommand", FakeGitCommand):
            assert project._DefaultBranchFallback() == expected_ref
        assert seen == expected_calls
    finally:
        project._DefaultBranchFallback.cache_clear()


def _create_mock_project(
    tempdir,
    use_local_gitdirs=False,
    fetch_cmd=None,
    depth=None,
    gitdir=None,
    objdir=None,
    revisionExpr="main",
    sync_strategy=None,
):
    manifest = mock.MagicMock()
    manifest.manifestProject.use_local_gitdirs = use_local_gitdirs
    manifest.manifestProject.fetch_cmd = fetch_cmd
    manifest.manifestProject.depth = depth
    manifest.manifestProject.dissociate = False
    manifest.manifestProject.clone_filter = None
    manifest.manifestProject.config.GetBoolean.return_value = False
    manifest.is_multimanifest = False
    manifest.IsMirror = False
    manifest.topdir = tempdir

    remote = mock.MagicMock()
    remote.name = "origin"
    remote.url = "http://example.com/repo"

    if gitdir is None:
        gitdir = os.path.join(tempdir, ".git")
    if objdir is None:
        objdir = os.path.join(tempdir, ".git")

    proj = project.Project(
        manifest=manifest,
        name="test-project",
        remote=remote,
        gitdir=gitdir,
        objdir=objdir,
        worktree=tempdir,
        relpath="test-project",
        revisionExpr=revisionExpr,
        revisionId=None,
        sync_strategy=sync_strategy,
    )

    proj.bare_git = mock.MagicMock()
    proj._LsRemote = mock.MagicMock(return_value="1234abcd\trefs/heads/main\n")
    manifest.GetProjectsWithName.return_value = [proj]

    return proj


class GetSubmoduleRevisions(unittest.TestCase):
    """Tests for Project.GetSubmoduleRevisions."""

    def test_gitlinks_are_keyed_by_their_path(self) -> None:
        with utils_for_test.TempGitTree() as tempdir:
            parent = _create_mock_project(tempdir)
            parent.GetRevisionId = mock.MagicMock(return_value="cafe1234")
            parent._GetSubmodules = mock.MagicMock(
                return_value=[("1234abcd", "sub", "http://example.com/sub", "")]
            )

            self.assertEqual(
                parent.GetSubmoduleRevisions(), {"sub": "1234abcd"}
            )

    def test_none_when_the_revision_is_not_fetched(self) -> None:
        with utils_for_test.TempGitTree() as tempdir:
            parent = _create_mock_project(tempdir)
            parent.GetRevisionId = mock.MagicMock(return_value="cafe1234")
            parent.bare_git.rev_list = mock.MagicMock(
                side_effect=error.GitError("missing object")
            )
            parent._GetSubmodules = mock.MagicMock()

            self.assertIsNone(parent.GetSubmoduleRevisions())
            parent._GetSubmodules.assert_not_called()

    def test_none_without_a_revision(self) -> None:
        with utils_for_test.TempGitTree() as tempdir:
            parent = _create_mock_project(tempdir)
            parent.GetRevisionId = mock.MagicMock(
                side_effect=error.ManifestInvalidRevisionError("no revision")
            )
            parent._GetSubmodules = mock.MagicMock()

            self.assertIsNone(parent.GetSubmoduleRevisions())
            parent._GetSubmodules.assert_not_called()


class StatelessSyncTests(unittest.TestCase):
    """Tests for stateless sync strategy."""

    def _get_project(self, tempdir):
        proj = _create_mock_project(
            tempdir, revisionExpr="1234abcd", sync_strategy="stateless"
        )
        proj._CheckForImmutableRevision = mock.MagicMock(return_value=False)
        proj.bare_git.rev_parse.return_value = "5678abcd"
        proj.bare_git.rev_list.return_value = ["0"]
        proj.IsDirty = mock.MagicMock(return_value=False)
        proj.GetBranches = mock.MagicMock(return_value=[])
        proj.DeleteWorktree = mock.MagicMock()
        proj._InitGitDir = mock.MagicMock()
        proj._RemoteFetch = mock.MagicMock(return_value=True)
        proj._InitRemote = mock.MagicMock()
        proj._InitMRef = mock.MagicMock()
        return proj

    def test_sync_network_half_stateless_prune_needed(self):
        """Test stateless sync queues prune when needed."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            res = proj.Sync_NetworkHalf()

            self.assertTrue(res.success)
            proj.DeleteWorktree.assert_not_called()
            self.assertTrue(proj.stateless_prune_needed)
            proj._RemoteFetch.assert_called_once()

    def test_sync_local_half_stateless_prune(self):
        """Test stateless GC pruning is queued in Sync_LocalHalf."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.stateless_prune_needed = True

            proj._Checkout = mock.MagicMock()
            proj._InitWorkTree = mock.MagicMock()
            proj.IsRebaseInProgress = mock.MagicMock(return_value=False)
            proj.IsCherryPickInProgress = mock.MagicMock(return_value=False)
            proj.bare_ref = mock.MagicMock()
            proj.bare_ref.all = {}
            proj.GetRevisionId = mock.MagicMock(return_value="1234abcd")
            proj._CopyAndLinkFiles = mock.MagicMock()

            proj.work_git = mock.MagicMock()
            proj.work_git.GetHead.return_value = "5678abcd"

            syncbuf = project.SyncBuffer(proj.config)

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                proj.Sync_LocalHalf(syncbuf)
                syncbuf.Finish()

            self.assertEqual(mock_git_cmd.call_count, 2)
            mock_git_cmd.assert_any_call(
                proj, ["reflog", "expire", "--expire=all", "--all"], bare=True
            )
            mock_git_cmd.assert_any_call(
                proj,
                ["gc", "--prune=now"],
                bare=True,
                capture_stdout=True,
                capture_stderr=True,
            )

    def test_sync_local_half_no_upstream_propagates_force_checkout(self):
        """Test Sync_LocalHalf forwards force_checkout when detaching."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)

            proj._InitWorkTree = mock.MagicMock()
            proj.CleanPublishedCache = mock.MagicMock()
            proj.GetRevisionId = mock.MagicMock(return_value="1234abcd")
            proj._Checkout = mock.MagicMock()
            proj._CopyAndLinkFiles = mock.MagicMock()

            proj.work_git = mock.MagicMock()
            proj.work_git.GetHead.return_value = "refs/heads/topic"

            proj.bare_ref = mock.MagicMock()
            proj.bare_ref.all = {"refs/heads/topic": "5678abcd"}

            branch = mock.MagicMock()
            branch.name = "topic"
            branch.LocalMerge = False
            proj.GetBranch = mock.MagicMock(return_value=branch)

            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf, force_checkout=True)

            proj._Checkout.assert_called_once_with(
                "1234abcd", force_checkout=True, quiet=True
            )
            proj._CopyAndLinkFiles.assert_called_once_with()

    def test_sync_network_half_stateless_skips_if_stash(self):
        """Test stateless sync skips if stash exists."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.HasStash = mock.MagicMock(return_value=True)

            res = proj.Sync_NetworkHalf()

            self.assertTrue(res.success)
            self.assertFalse(getattr(proj, "stateless_prune_needed", False))

    def test_sync_network_half_stateless_skips_if_local_commits(self):
        """Test stateless sync skips if there are local-only commits."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.bare_git.rev_list.return_value = ["1"]

            res = proj.Sync_NetworkHalf()

            self.assertTrue(res.success)
            self.assertFalse(getattr(proj, "stateless_prune_needed", False))


class SyncOptimizationTests(unittest.TestCase):
    """Tests for sync optimization logic involving shallow clones."""

    def _get_project(
        self,
        tempdir: str,
        depth: Optional[int] = None,
        revisionExpr: Optional[str] = None,
    ) -> project.Project:
        if revisionExpr is None:
            revisionExpr = "0123456789abcdef0123456789abcdef01234567"
        proj = _create_mock_project(
            tempdir,
            depth=depth,
            gitdir=os.path.join(tempdir, "gitdir"),
            objdir=os.path.join(tempdir, "objdir"),
            revisionExpr=revisionExpr,
        )
        proj._CheckForImmutableRevision = mock.MagicMock(return_value=True)
        proj.DeleteWorktree = mock.MagicMock()
        proj._InitGitDir = mock.MagicMock()
        proj._InitRemote = mock.MagicMock()
        proj._InitMRef = mock.MagicMock()
        return proj

    def _create_sharing_project(self, tempdir, proj, share_objdir=True):
        """Create another project with the same name but a different gitdir.

        Args:
            share_objdir: a boolean, if True - the new project shares the same
                objdir, if False - the new project has a different objdir.
        """
        if share_objdir:
            other_objdir = proj.objdir
        else:
            other_objdir = os.path.join(tempdir, "other_objdir")
        other = project.Project(
            manifest=proj.manifest,
            name=proj.name,
            remote=proj.remote,
            gitdir=os.path.join(tempdir, "other_gitdir"),
            objdir=other_objdir,
            worktree=os.path.join(tempdir, "other_worktree"),
            relpath="other-test-project",
            revisionExpr=proj.revisionExpr,
            revisionId=None,
        )
        proj.manifest.GetProjectsWithName.return_value.append(other)
        return other

    def test_sync_network_half_shallow_missing_fetches(self):
        """Test Sync_NetworkHalf fetches if shallow file is missing."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            # Ensure gitdir does not exist to simulate new project
            if os.path.exists(proj.gitdir):
                shutil.rmtree(proj.gitdir)
            shallow_path = os.path.join(proj.gitdir, "shallow")
            if os.path.exists(shallow_path):
                os.unlink(shallow_path)

            proj._RemoteFetch = mock.MagicMock(return_value=True)

            res = proj.Sync_NetworkHalf(optimized_fetch=True)

            self.assertTrue(res.success)
            proj._RemoteFetch.assert_called_once()

    def test_sync_network_half_shallow_exists_skips(self):
        """Test Sync_NetworkHalf skips fetch if shallow file exists."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)
            with open(os.path.join(proj.gitdir, "shallow"), "w") as f:
                f.write("")

            proj._RemoteFetch = mock.MagicMock()

            res = proj.Sync_NetworkHalf(optimized_fetch=True)

            self.assertTrue(res.success)
            proj._RemoteFetch.assert_not_called()

    def test_sync_network_half_sharing_project_shallow_missing_fetches(
        self,
    ):
        """Test Sync_NetworkHalf fetches when sharing project has shallow
        file but this project does not."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)

            other = self._create_sharing_project(tempdir, proj)
            os.makedirs(other.gitdir, exist_ok=True)
            with open(os.path.join(other.gitdir, "shallow"), "w") as f:
                f.write("")

            proj._RemoteFetch = mock.MagicMock(return_value=True)

            res = proj.Sync_NetworkHalf(optimized_fetch=True)

            self.assertTrue(res.success)
            proj._RemoteFetch.assert_called_once()

    def test_sync_network_half_different_objdir_shallow_exists_skips(self):
        """Test Sync_NetworkHalf skips when same-name project has shallow file
        but different objdir (like in a multi-manifest setup)."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)

            other = self._create_sharing_project(
                tempdir, proj, share_objdir=False
            )
            os.makedirs(other.gitdir, exist_ok=True)
            with open(os.path.join(other.gitdir, "shallow"), "w") as f:
                f.write("")

            proj._RemoteFetch = mock.MagicMock()

            res = proj.Sync_NetworkHalf(optimized_fetch=True)

            self.assertTrue(res.success)
            proj._RemoteFetch.assert_not_called()

    def test_sync_network_half_sharing_project_both_shallow_skips(self):
        """Test Sync_NetworkHalf skips when both this project and the sharing
        project have shallow files."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)
            with open(os.path.join(proj.gitdir, "shallow"), "w") as f:
                f.write("")

            other = self._create_sharing_project(tempdir, proj)
            os.makedirs(other.gitdir, exist_ok=True)
            with open(os.path.join(other.gitdir, "shallow"), "w") as f:
                f.write("")

            proj._RemoteFetch = mock.MagicMock()

            res = proj.Sync_NetworkHalf(optimized_fetch=True)

            self.assertTrue(res.success)
            proj._RemoteFetch.assert_not_called()

    def test_remote_fetch_shallow_missing_fetches(self):
        """Test _RemoteFetch fetches if shallow file is missing."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            shallow_path = os.path.join(proj.gitdir, "shallow")
            if os.path.exists(shallow_path):
                os.unlink(shallow_path)

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                res = proj._RemoteFetch(
                    current_branch_only=True,
                    depth=1,
                    use_superproject=False,
                )

                self.assertTrue(res)
                mock_git_cmd.assert_called()

    def test_remote_fetch_shallow_exists_skips(self):
        """Test _RemoteFetch skips fetch if shallow file exists."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)
            with open(os.path.join(proj.gitdir, "shallow"), "w") as f:
                f.write("")

            with mock.patch("project.GitCommand") as mock_git_cmd:
                res = proj._RemoteFetch(
                    current_branch_only=True,
                    depth=1,
                    use_superproject=False,
                )

                self.assertTrue(res)
                mock_git_cmd.assert_not_called()

    def test_remote_fetch_sharing_project_shallow_missing_fetches(self):
        """Test _RemoteFetch fetches when sharing project has shallow file
        but this project does not."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)

            other = self._create_sharing_project(tempdir, proj)
            os.makedirs(other.gitdir, exist_ok=True)
            with open(os.path.join(other.gitdir, "shallow"), "w") as f:
                f.write("")

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                res = proj._RemoteFetch(
                    current_branch_only=True,
                    depth=1,
                    use_superproject=False,
                )

                self.assertTrue(res)
                mock_git_cmd.assert_called()

    def test_remote_fetch_sharing_project_both_shallow_skips(self):
        """Test _RemoteFetch skips when both this project and the sharing
        project have shallow files."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, depth=1)
            os.makedirs(proj.gitdir, exist_ok=True)
            os.makedirs(proj.objdir, exist_ok=True)
            with open(os.path.join(proj.gitdir, "shallow"), "w") as f:
                f.write("")

            other = self._create_sharing_project(tempdir, proj)
            os.makedirs(other.gitdir, exist_ok=True)
            with open(os.path.join(other.gitdir, "shallow"), "w") as f:
                f.write("")

            with mock.patch("project.GitCommand") as mock_git_cmd:
                res = proj._RemoteFetch(
                    current_branch_only=True,
                    depth=1,
                    use_superproject=False,
                )

                self.assertTrue(res)
                mock_git_cmd.assert_not_called()

    def test_remote_fetch_sha1_dest_branch_not_fetched(self) -> None:
        """Test _RemoteFetch ignores dest-branch for SHA-1 revisions."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, revisionExpr=sha)
            proj._CheckForImmutableRevision.return_value = False
            proj.upstream = None
            proj.dest_branch = "my-dest-branch"
            proj.manifest.default.upstreamExpr = None
            proj.manifest.default.revisionExpr = None

            mock_remote = mock.MagicMock()
            mock_remote.name = "origin"

            def _to_local(r: str) -> str:
                if r.startswith("refs/heads/"):
                    return "refs/remotes/origin/" + r[11:]
                return r

            mock_remote.ToLocal.side_effect = _to_local
            mock_remote.PreConnectFetch.return_value = True
            proj.GetRemote = mock.MagicMock(return_value=mock_remote)

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                res = proj._RemoteFetch(current_branch_only=True)

                self.assertTrue(res)
                mock_git_cmd.assert_called_once()
                cmd_args = mock_git_cmd.call_args[0][1]
                self.assertIn("+refs/heads/*:refs/remotes/origin/*", cmd_args)
                self.assertNotIn(
                    "+refs/heads/my-dest-branch:"
                    "refs/remotes/origin/my-dest-branch",
                    cmd_args,
                )

    def test_remote_fetch_sha1_manifest_default_fallback(self) -> None:
        """Test _RemoteFetch upstream fallback from manifest defaults."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, revisionExpr=sha)
            proj._CheckForImmutableRevision.side_effect = [False, True]
            proj.upstream = None
            proj.dest_branch = None
            proj.manifest.default.upstreamExpr = "manifest-upstream"

            mock_remote = mock.MagicMock()
            mock_remote.name = "origin"

            def _to_local(r: str) -> str:
                if r.startswith("refs/heads/"):
                    return "refs/remotes/origin/" + r[11:]
                return r

            mock_remote.ToLocal.side_effect = _to_local
            mock_remote.PreConnectFetch.return_value = True
            proj.GetRemote = mock.MagicMock(return_value=mock_remote)

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                res = proj._RemoteFetch(current_branch_only=True)

                self.assertTrue(res)
                mock_git_cmd.assert_called_once()
                cmd_args = mock_git_cmd.call_args[0][1]
                self.assertIn(
                    "+refs/heads/manifest-upstream:"
                    "refs/remotes/origin/manifest-upstream",
                    cmd_args,
                )
                self.assertNotIn(
                    "+refs/heads/*:refs/remotes/origin/*", cmd_args
                )

    def test_remote_fetch_sha1_tag_not_fetched(self) -> None:
        """Test _RemoteFetch ignores tag defaults for SHA-1 revisions."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, revisionExpr=sha)
            proj._CheckForImmutableRevision.return_value = False
            proj.upstream = None
            proj.dest_branch = None
            proj.manifest.default.upstreamExpr = None
            proj.manifest.default.revisionExpr = "refs/tags/v1.0"

            mock_remote = mock.MagicMock()
            mock_remote.name = "origin"

            def _to_local(r: str) -> str:
                if r.startswith("refs/heads/"):
                    return "refs/remotes/origin/" + r[11:]
                return r

            mock_remote.ToLocal.side_effect = _to_local
            mock_remote.PreConnectFetch.return_value = True
            proj.GetRemote = mock.MagicMock(return_value=mock_remote)

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                res = proj._RemoteFetch(current_branch_only=True)

                self.assertTrue(res)
                mock_git_cmd.assert_called_once()
                cmd_args = mock_git_cmd.call_args[0][1]
                self.assertIn("+refs/heads/*:refs/remotes/origin/*", cmd_args)
                self.assertNotIn("tag", cmd_args)
                self.assertNotIn("v1.0", cmd_args)

    def test_remote_fetch_sha1_metaproject_without_manifest_xml(self) -> None:
        """Test MetaProject _RemoteFetch with SHA-1 fetches all branches."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            repodir = os.path.join(tempdir, ".repo")
            manifest_dir = os.path.join(repodir, "manifests")
            manifest_file = os.path.join(
                repodir, manifest_xml.MANIFEST_FILE_NAME
            )
            os.mkdir(repodir)
            os.mkdir(manifest_dir)
            manifest = manifest_xml.XmlManifest(repodir, manifest_file)
            proj = project.ManifestProject(
                manifest,
                "test/manifest",
                os.path.join(tempdir, ".git"),
                tempdir,
            )
            proj.revisionExpr = sha
            proj.upstream = None
            proj._CheckForImmutableRevision = mock.MagicMock(return_value=False)

            mock_remote = mock.MagicMock()
            mock_remote.name = "origin"

            def _to_local(r: str) -> str:
                if r.startswith("refs/heads/"):
                    return "refs/remotes/origin/" + r[11:]
                return r

            mock_remote.ToLocal.side_effect = _to_local
            mock_remote.PreConnectFetch.return_value = True
            proj.GetRemote = mock.MagicMock(return_value=mock_remote)

            with mock.patch("project.GitCommand") as mock_git_cmd:
                mock_cmd_instance = mock.MagicMock()
                mock_cmd_instance.Wait.return_value = 0
                mock_git_cmd.return_value = mock_cmd_instance

                res = proj._RemoteFetch(current_branch_only=True)

                self.assertTrue(res)
                mock_git_cmd.assert_called_once()
                cmd_args = mock_git_cmd.call_args[0][1]
                self.assertIn("+refs/heads/*:refs/remotes/origin/*", cmd_args)

    def test_remote_fetch_sha1_none_manifest_default(self) -> None:
        """Test _GetUpstreamFallback when manifest.default is None."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, revisionExpr=sha)
            proj.dest_branch = None
            proj.manifest.default = None
            self.assertIsNone(proj._GetUpstreamFallback())

    def test_get_upstream_fallback_ignores_dest_branch(self) -> None:
        """dest_branch alone yields no fallback upstream."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(
                tempdir,
                revisionExpr="0123456789abcdef0123456789abcdef01234567",
            )
            proj.dest_branch = "main"
            proj.manifest.default.upstreamExpr = None
            proj.manifest.default.revisionExpr = None
            self.assertIsNone(proj._GetUpstreamFallback())

    def test_get_upstream_fallback_ignores_tag(self) -> None:
        """A tag default is not returned as a fallback upstream."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(
                tempdir,
                revisionExpr="0123456789abcdef0123456789abcdef01234567",
            )
            proj.dest_branch = None
            proj.manifest.default.upstreamExpr = None
            proj.manifest.default.revisionExpr = "refs/tags/v1.0"
            self.assertIsNone(proj._GetUpstreamFallback())

    def test_get_upstream_fallback_uses_revision_branch(self) -> None:
        """A branch revision default is a valid fallback upstream."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(
                tempdir,
                revisionExpr="0123456789abcdef0123456789abcdef01234567",
            )
            proj.dest_branch = "dest-should-be-ignored"
            proj.manifest.default.upstreamExpr = None
            proj.manifest.default.revisionExpr = "main"
            self.assertEqual(proj._GetUpstreamFallback(), "main")

    def test_remote_fetch_sha1_missing_upstream_falls_back_to_all_heads(
        self,
    ) -> None:
        """A missing upstream remote branch falls back to fetching all heads."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, revisionExpr=sha)
            proj._CheckForImmutableRevision = mock.MagicMock(return_value=False)
            proj.upstream = None
            proj.dest_branch = None
            proj.manifest.default.upstreamExpr = None
            proj.manifest.default.revisionExpr = "master"

            mock_remote = mock.MagicMock()
            mock_remote.name = "origin"

            def _to_local(r: str) -> str:
                if r.startswith("refs/heads/"):
                    return "refs/remotes/origin/" + r[11:]
                return r

            mock_remote.ToLocal.side_effect = _to_local
            mock_remote.PreConnectFetch.return_value = True
            proj.GetRemote = mock.MagicMock(return_value=mock_remote)

            fetched_specs: List[List[str]] = []

            def _fake_git_command(
                _proj: Optional[project.Project],
                cmd: List[str],
                **kwargs,
            ) -> mock.MagicMock:
                fetched_specs.append(cmd)
                inst = mock.MagicMock()
                if "+refs/heads/master:refs/remotes/origin/master" in cmd:
                    inst.Wait.return_value = 128
                    inst.stdout = (
                        "fatal: couldn't find remote ref refs/heads/master\n"
                    )
                else:
                    inst.Wait.return_value = 0
                    inst.stdout = ""
                return inst

            with mock.patch(
                "project.GitCommand", side_effect=_fake_git_command
            ):
                res = proj._RemoteFetch(current_branch_only=True)

            self.assertTrue(res)
            self.assertTrue(
                any(
                    "+refs/heads/master:refs/remotes/origin/master" in c
                    for c in fetched_specs
                )
            )
            self.assertTrue(
                any(
                    "+refs/heads/*:refs/remotes/origin/*" in c
                    for c in fetched_specs
                )
            )


class GetEnvVarsTests(unittest.TestCase):
    """Tests for GetEnvVars project environment variable generation."""

    def _get_project(self, tempdir, revisionExpr="main"):
        proj = _create_mock_project(tempdir, revisionExpr=revisionExpr)
        proj.GetRevisionId = mock.MagicMock(return_value="1234abcd")
        return proj

    def test_get_env_vars_basic(self):
        """Test that all basic environment variables are set correctly."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.manifest.path_prefix = "sub-manifest"
            proj.upstream = "upstream-branch"
            proj.dest_branch = "dest-branch"

            env = proj.GetEnvVars(local=True)

            self.assertEqual(env["REPO_PROJECT"], "test-project")
            self.assertEqual(env["REPO_OUTERPATH"], "sub-manifest")
            self.assertEqual(env["REPO_INNERPATH"], "test-project")
            self.assertEqual(env["REPO_PATH"], "test-project")
            self.assertEqual(env["REPO_REMOTE"], "origin")
            self.assertEqual(env["REPO_LREV"], "1234abcd")
            self.assertEqual(env["REPO_RREV"], "main")
            self.assertEqual(env["REPO_UPSTREAM"], "upstream-branch")
            self.assertEqual(env["REPO_DEST_BRANCH"], "dest-branch")
            self.assertEqual(
                env["REPO_PROJECT_FETCH_URL"], "http://example.com/repo"
            )

    def test_get_env_vars_non_local(self):
        """Test environment variables generation with local=False."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.manifest.path_prefix = "sub-manifest"

            env = proj.GetEnvVars(local=False)

            # REPO_PATH should be relative to outermost manifest
            # (sub-manifest/test-project)
            self.assertEqual(env["REPO_PATH"], "sub-manifest/test-project")

    def test_get_env_vars_mirror(self):
        """Test environment variables generation in mirror mode."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.manifest.IsMirror = True

            env = proj.GetEnvVars()

            # In mirror mode, REPO_LREV should be empty, and GetRevisionId must
            # not be called
            self.assertEqual(env["REPO_LREV"], "")
            proj.GetRevisionId.assert_not_called()

    def test_get_env_vars_annotations(self):
        """Test that project annotations are added correctly."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)

            annotation1 = mock.MagicMock()
            annotation1.name = "key1"
            annotation1.value = "value1"

            annotation2 = mock.MagicMock()
            annotation2.name = "key2"
            annotation2.value = "value2"

            proj.annotations = [annotation1, annotation2]

            env = proj.GetEnvVars()

            self.assertEqual(env["REPO__key1"], "value1")
            self.assertEqual(env["REPO__key2"], "value2")

    def test_get_env_vars_invalid_revision_graceful(self):
        """Test that invalid revision error is handled gracefully."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.GetRevisionId.side_effect = error.ManifestInvalidRevisionError(
                "revision not found"
            )

            env = proj.GetEnvVars()

            self.assertEqual(env["REPO_LREV"], "")


class FetchCmdTests(unittest.TestCase):
    """Tests for fetch_cmd feature."""

    def setUpManifest(self, tempdir):
        repodir = os.path.join(tempdir, ".repo")
        manifest_dir = os.path.join(repodir, "manifests")
        manifest_file = os.path.join(repodir, manifest_xml.MANIFEST_FILE_NAME)
        os.mkdir(repodir)
        os.mkdir(manifest_dir)
        manifest = manifest_xml.XmlManifest(repodir, manifest_file)

        return project.ManifestProject(
            manifest, "test/manifest", os.path.join(tempdir, ".git"), tempdir
        )

    def _get_project(self, tempdir):
        proj = _create_mock_project(
            tempdir, use_local_gitdirs=True, fetch_cmd="echo hi"
        )
        proj.GetRevisionId = mock.MagicMock(return_value="1234abcd")
        return proj

    def test_fetch_cmd_execution(self):
        """Test that fetch_cmd is executed with correct environment."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)

            proj.bare_git.rev_parse.return_value = "1234abcd"
            mock_remote = mock.MagicMock()
            mock_remote.ToLocal.return_value = "refs/remotes/origin/main"
            proj.GetRemote = mock.MagicMock(return_value=mock_remote)

            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
                res = proj._CustomFetch()

                self.assertTrue(res)
                mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(args[0], "echo hi")
            self.assertEqual(kwargs["shell"], True)
            self.assertEqual(kwargs["cwd"], tempdir)
            self.assertEqual(kwargs["env"]["REPO_TREV"], "1234abcd")
            self.assertEqual(
                kwargs["env"]["REPO_PROJECT_FETCH_URL"],
                "http://example.com/repo",
            )

    def test_sync_fetch_cmd_requires_use_local_gitdirs(self):
        """Test that fetch_cmd requires use_local_gitdirs."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)

            class DummyManifest:
                is_submanifest = False

                def GetDefaultGroupsStr(self, with_platform=False):
                    return ""

            fakeproj.manifest = DummyManifest()

            fakeproj.config.SetString("repo.fetchcmd", "echo hi")
            fakeproj.config.SetBoolean("repo.uselocalgitdirs", False)

            result = fakeproj.Sync(use_local_gitdirs=False)
            self.assertFalse(result)
