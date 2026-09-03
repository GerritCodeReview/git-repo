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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
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

    def test_current_comes_from_branch_snapshot(self) -> None:
        """Reviewable branches carry current state into report consumers."""
        branch = mock.MagicMock()
        branch.current = True

        rb = project.ReviewableBranch(mock.MagicMock(), branch, "main")

        self.assertTrue(rb.current)


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

    def test_resolve_commit_uses_end_of_options_when_supported(self) -> None:
        """Commit resolution separates user revisions from options."""
        proj = mock.MagicMock(name="project")
        proj.name = "project"
        git = project.Project._GitGetByExec(proj, bare=True, gitdir="gitdir")
        command = mock.MagicMock()
        command.stdout = "1" * 40 + "\n"
        command.Wait.return_value = 0

        with mock.patch.object(
            project, "git_require", return_value=True
        ), mock.patch.object(
            project, "GitCommand", return_value=command
        ) as cmd:
            self.assertEqual("1" * 40, git.ResolveCommit("topic"))

        cmd.assert_called_once_with(
            proj,
            [
                "rev-parse",
                "--verify",
                "--quiet",
                "--end-of-options",
                "topic^{commit}",
            ],
            bare=True,
            gitdir="gitdir",
            capture_stdout=True,
            capture_stderr=True,
            verify_command=True,
            log_as_error=False,
        )

    def test_resolve_commit_rejects_option_on_old_git(self) -> None:
        """Old Git never receives a revision that looks like an option."""
        proj = mock.MagicMock(name="project")
        proj.name = "project"
        git = project.Project._GitGetByExec(proj, bare=True, gitdir="gitdir")

        with mock.patch.object(project, "git_require", return_value=False):
            with self.assertRaises(error.GitError):
                git.ResolveCommit("--not-a-revision")

    def test_get_branches_reuses_ref_snapshot_for_current_branch(self) -> None:
        """GetBranches derives the current branch from the loaded refs."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.work_git = mock.MagicMock()
            proj.bare_ref = mock.MagicMock()
            proj.bare_ref.all = {
                "HEAD": "1" * 40,
                "refs/heads/topic": "1" * 40,
            }
            proj.bare_ref.head = "refs/heads/topic"

            branches = proj.GetBranches()

            self.assertTrue(branches["topic"].current)
            proj.work_git.GetHead.assert_not_called()

    def test_get_branches_reads_worktree_head_for_git_worktrees(self) -> None:
        """A shared repository HEAD is not a linked worktree's HEAD."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.use_git_worktrees = True
            proj.work_git = mock.MagicMock()
            proj.work_git.GetHead.return_value = "refs/heads/worktree"
            proj.bare_ref = mock.MagicMock()
            proj.bare_ref.all = {
                "HEAD": "1" * 40,
                "refs/heads/common": "1" * 40,
                "refs/heads/worktree": "1" * 40,
            }
            proj.bare_ref.head = "refs/heads/common"

            branches = proj.GetBranches()

            self.assertFalse(branches["common"].current)
            self.assertTrue(branches["worktree"].current)
            proj.work_git.GetHead.assert_called_once_with()

    def test_get_branches_tolerates_unreadable_head(self) -> None:
        """An incomplete checkout still reports its local branches."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.bare_ref = mock.MagicMock()
            proj.bare_ref.all = {"refs/heads/topic": "1" * 40}

            with mock.patch.object(
                proj,
                "_GetHead",
                side_effect=error.NoManifestException("HEAD", "unreadable"),
            ):
                branches = proj.GetBranches()

            self.assertFalse(branches["topic"].current)

    def test_get_head_returns_none_when_work_git_is_none(self) -> None:
        """Bare and mirror checkouts without work_git do not crash."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.work_git = None

            self.assertIsNone(proj._GetHead())
            self.assertIsNone(proj.CurrentBranch)

    def test_current_branch_returns_none_when_get_head_returns_none(
        self,
    ) -> None:
        """CurrentBranch safely returns None when _GetHead returns None."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            with mock.patch.object(proj, "_GetHead", return_value=None):
                self.assertIsNone(proj.CurrentBranch)

    def test_prune_heads_reuses_refs_and_avoids_revision_walk(self) -> None:
        """Pruning uses snapshot OIDs to recognize an exact manifest HEAD."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            Path(tempdir, "tracked").write_text("initial")
            proj.work_git.add("tracked")
            proj.work_git.commit("-m", "initial")
            revision = proj.work_git.rev_parse("HEAD")
            proj.work_git.branch("merged")
            proj.work_git.checkout("-b", "unmerged")
            Path(tempdir, "tracked").write_text("topic")
            proj.work_git.commit("-am", "topic")
            proj.work_git.checkout("main")
            proj.work_git.config("branch.unmerged.remote", ".")
            proj.work_git.config("branch.unmerged.merge", "refs/heads/main")
            proj.revisionId = revision
            proj.bare_git = project.Project._GitGetByExec(
                proj, bare=True, gitdir=proj.gitdir
            )
            proj._revlist = mock.MagicMock(
                side_effect=AssertionError("unexpected revision walk")
            )

            kept = proj.PruneHeads()

            self.assertEqual(["unmerged"], [branch.name for branch in kept])
            self.assertEqual("", proj.bare_ref.get("refs/heads/merged"))
            proj._revlist.assert_not_called()

    def test_prune_heads_compares_peeled_tag_commit(self) -> None:
        """A branch at an annotated manifest tag can be pruned."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(
                tempdir, revisionExpr="refs/tags/release"
            )
            Path(tempdir, "tracked").write_text("initial")
            proj.work_git.add("tracked")
            proj.work_git.commit("-m", "initial")
            proj.work_git.tag("-a", "release", "-m", "release")
            proj.bare_git = project.Project._GitGetByExec(
                proj, bare=True, gitdir=proj.gitdir
            )

            kept = proj.PruneHeads()

            self.assertEqual([], kept)
            self.assertIsNone(proj.CurrentBranch)
            self.assertEqual("", proj.bare_ref.get("refs/heads/main"))

    def test_prune_heads_preserves_detached_head_when_current_branch_pruned(
        self,
    ) -> None:
        """Pruning current branch keeps HEAD detached at target commit."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            Path(tempdir, "tracked").write_text("initial")
            proj.work_git.add("tracked")
            proj.work_git.commit("-m", "initial")
            revision = proj.work_git.rev_parse("HEAD")
            proj.revisionId = revision
            proj.bare_git = project.Project._GitGetByExec(
                proj, bare=True, gitdir=proj.gitdir
            )
            proj.bare_ref.head

            kept = proj.PruneHeads()

            self.assertEqual([], kept)
            self.assertIsNone(proj.CurrentBranch)
            self.assertEqual("", proj.bare_ref.get("refs/heads/main"))
            self.assertEqual(revision, proj.bare_git.rev_parse("HEAD"))

    def test_prune_heads_with_git_worktrees_preserves_bare_head(self) -> None:
        """Worktree pruning does not detach the shared bare repository HEAD."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            Path(tempdir, "tracked").write_text("initial")
            proj.work_git.add("tracked")
            proj.work_git.commit("-m", "initial")
            revision = proj.work_git.rev_parse("HEAD")
            proj.revisionId = revision
            proj.use_git_worktrees = True
            proj.bare_git = mock.MagicMock()
            proj.bare_git.GetHead.return_value = "refs/heads/manifest"

            kept = proj.PruneHeads()

            self.assertEqual([], kept)
            proj.bare_git.SetHead.assert_called_once_with("refs/heads/manifest")
            proj.bare_git.DetachHead.assert_called_once_with(revision)

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

    def test_get_uploadable_branches_pruned_when_no_configured_branches(
        self,
    ) -> None:
        """Verify GetUploadableBranches returns [] without reading all refs when
        no branches are configured in .git/config."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            proj = _create_mock_project(tempdir)
            with mock.patch.object(
                project.Project, "_allrefs", new_callable=mock.PropertyMock
            ) as mock_allrefs:
                res = proj.GetUploadableBranches()
                self.assertEqual(res, [])
                mock_allrefs.assert_not_called()

    def test_get_uploadable_branches_pruned_when_only_2part_branch_keys(
        self,
    ) -> None:
        """Verify GetUploadableBranches returns [] without reading all refs when
        config contains 2-part keys like branch.autosetupmerge."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            proj = _create_mock_project(tempdir)
            with mock.patch.object(
                proj.config, "GetSubSections", return_value={""}
            ), mock.patch.object(
                project.Project, "_allrefs", new_callable=mock.PropertyMock
            ) as mock_allrefs:
                res = proj.GetUploadableBranches()
                self.assertEqual(res, [])
                mock_allrefs.assert_not_called()

    def test_get_uploadable_branches_selected_branch_pruned_when_not_configured(
        self,
    ) -> None:
        """Verify GetUploadableBranches(selected_branch) returns [] without
        reading all refs when selected branch has no LocalMerge."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            proj = _create_mock_project(tempdir)
            fake_branch = mock.MagicMock()
            fake_branch.LocalMerge = None
            with mock.patch.object(
                proj, "GetBranch", return_value=fake_branch
            ), mock.patch.object(
                project.Project, "_allrefs", new_callable=mock.PropertyMock
            ) as mock_allrefs:
                res = proj.GetUploadableBranches("nonexistent-branch")
                self.assertEqual(res, [])
                mock_allrefs.assert_not_called()

    def test_get_uploadable_branches_selected_branch_already_published(
        self,
    ) -> None:
        """Verify GetUploadableBranches(selected_branch) returns [] when the
        branch tip matches refs/published/<branch>."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            proj = _create_mock_project(tempdir)
            fake_branch = mock.MagicMock()
            fake_branch.LocalMerge = "refs/remotes/origin/main"
            fake_branch.name = "feature"

            sha1 = "0123456789abcdef0123456789abcdef01234567"

            def get_ref(name: str) -> str:
                if name in ("refs/heads/feature", "refs/published/feature"):
                    return sha1
                return ""

            with mock.patch.object(
                proj, "GetBranch", return_value=fake_branch
            ), mock.patch.object(
                proj.bare_ref, "get", side_effect=get_ref
            ), mock.patch.object(
                proj, "GetUploadableBranch"
            ) as mock_get_up:
                res = proj.GetUploadableBranches("feature")
                self.assertEqual(res, [])
                mock_get_up.assert_not_called()

    def test_get_uploadable_branches_selected_branch_uploadable(
        self,
    ) -> None:
        """Verify GetUploadableBranches(selected_branch) returns the uploadable
        branch when new commits exist."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
            proj = _create_mock_project(tempdir)
            fake_branch = mock.MagicMock()
            fake_branch.LocalMerge = "refs/remotes/origin/main"
            fake_branch.name = "feature"

            head_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            pub_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            mock_rb = mock.MagicMock()
            mock_rb.name = "feature"

            def get_ref(name: str) -> str:
                if name == "refs/heads/feature":
                    return head_sha
                if name == "refs/published/feature":
                    return pub_sha
                return ""

            with mock.patch.object(
                proj, "GetBranch", return_value=fake_branch
            ), mock.patch.object(
                proj.bare_ref, "get", side_effect=get_ref
            ), mock.patch.object(
                proj, "GetUploadableBranch", return_value=mock_rb
            ) as mock_get_up:
                res = proj.GetUploadableBranches("feature")
                self.assertEqual(res, [mock_rb])
                mock_get_up.assert_called_once_with("feature")

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

    def test_set_revision_object_id_lengths(self) -> None:
        """SetRevision only treats exact 40- or 64-char hex as immutable IDs."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)

            # SHA-1 (40 hex chars) is recorded as revisionId directly.
            sha1 = "a" * 40
            proj.SetRevision(sha1)
            self.assertEqual(proj.revisionId, sha1)

            # SHA-256 (64 hex chars) is recorded as revisionId directly.
            sha256 = "b" * 64
            proj.SetRevision(sha256)
            self.assertEqual(proj.revisionId, sha256)

            # Intermediate hex strings (41-63 chars) must not be treated
            # as commit IDs.
            for length in (41, 48, 63):
                proj.SetRevision("c" * length)
                self.assertIsNone(proj.revisionId)

    def test_remote_fetch_intermediate_hex_not_fetched_as_commit_id(
        self,
    ) -> None:
        """41-char hex revisions are not fetched as raw commit IDs on shallow
        fetch."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.config.GetRemote("origin").ResetFetch()
            hex41 = "a" * 41
            proj.SetRevision(hex41)

            with mock.patch("project.GitCommand") as mock_git:
                mock_cmd = mock.MagicMock()
                mock_cmd.Wait.return_value = 0
                mock_git.return_value = mock_cmd

                proj._RemoteFetch(depth=1, current_branch_only=True)

                fetch_args = mock_git.call_args[0][1]
                # When depth is set, commit IDs are passed directly to
                # git fetch.
                # Since 41 hex chars is not an ID, it must not appear as a
                # standalone argument.
                self.assertNotIn(hex41, fetch_args)
                # Instead, it is treated as a branch ref and formatted
                # as a refspec.
                self.assertIn(
                    f"+refs/heads/{hex41}:refs/remotes/origin/{hex41}",
                    fetch_args,
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

    def test_should_verify_upstream_metaproject_returns_false(
        self,
    ) -> None:
        """MetaProjects never verify upstream ancestry."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)
            fakeproj.revisionExpr = "4f8a3c0000000000000000000000000000000000"
            fakeproj.upstream = "refs/heads/main"
            self.assertFalse(
                fakeproj._ShouldVerifyUpstream(use_superproject=False)
            )

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
    "supports_git_var, responses, expected_ref, expected_calls",
    (
        # git >= 2.35 answers `git var GIT_DEFAULT_BRANCH`.
        (
            True,
            {"var": (0, "jellybean\n")},
            "refs/heads/jellybean",
            [_VAR_CMD],
        ),
        # Older git: `git var` fails, so read init.defaultBranch instead.
        (
            False,
            {"config": (0, "custom\n")},
            "refs/heads/custom",
            [_CONFIG_CMD],
        ),
        # Nothing configured anywhere: git's historical built-in default.
        (
            False,
            {"config": (1, "")},
            "refs/heads/master",
            [_CONFIG_CMD],
        ),
    ),
    ids=("git_var", "old_git_reads_config", "unconfigured_defaults_to_master"),
)
def test_default_branch_fallback(
    supports_git_var: bool,
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
        with mock.patch.object(
            project, "git_require", return_value=supports_git_var
        ), mock.patch.object(project, "GitCommand", FakeGitCommand):
            assert project._DefaultBranchFallback() == expected_ref
        assert seen == expected_calls
    finally:
        project._DefaultBranchFallback.cache_clear()


def test_metaproject_has_changes_bounds_revision_walk() -> None:
    """MetaProject only asks whether one remote-only commit exists."""
    meta = mock.MagicMock()
    meta.remote = mock.sentinel.remote
    meta.revisionExpr = "refs/remotes/origin/main"
    meta.bare_ref.all = {"HEAD": "local"}
    meta.GetRevisionId.return_value = "remote"
    meta._GetHead.return_value = "local"
    meta._revlist.return_value = ["remote"]

    assert project.MetaProject.HasChanges.fget(meta)

    meta._revlist.assert_called_once_with("-1", "^HEAD", "remote")


def _create_mock_project(
    tempdir,
    use_local_gitdirs=False,
    fetch_cmd=None,
    reproject_cmd: Optional[str] = None,
    depth=None,
    gitdir=None,
    objdir=None,
    revisionExpr="main",
    sync_strategy=None,
):
    manifest = mock.MagicMock()
    manifest.manifestProject.use_local_gitdirs = use_local_gitdirs
    manifest.manifestProject.fetch_cmd = fetch_cmd
    manifest.manifestProject.reproject_cmd = reproject_cmd
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
            proj.bare_ref.head = "5678abcd"
            proj.GetRevisionId = mock.MagicMock(return_value="1234abcd")
            proj._CopyAndLinkFiles = mock.MagicMock()

            proj.work_git = mock.MagicMock()
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

    def test_check_immutable_revision_plain_project_upstream_ancestor(
        self,
    ) -> None:
        """Non-shallow projects verify upstream ancestry for immutable
        revisions."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.bare_git = project.Project._GitGetByExec(
                proj, bare=True, gitdir=proj.gitdir
            )
            proj.upstream = "refs/heads/main"
            proj.work_git.config("remote.origin.url", "http://example.com/repo")
            proj.work_git.config(
                "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"
            )

            test_file = os.path.join(tempdir, "file.txt")
            with open(test_file, "w") as f:
                f.write("commit1")
            proj.work_git.add("file.txt")
            proj.work_git.commit("-m", "commit 1")
            commit1 = proj.work_git.rev_parse("HEAD")

            proj.work_git.update_ref("refs/remotes/origin/main", commit1)

            with open(test_file, "w") as f:
                f.write("commit2")
            proj.work_git.add("file.txt")
            proj.work_git.commit("-m", "commit 2")
            commit2 = proj.work_git.rev_parse("HEAD")

            # 1. When revision is commit1 and upstream tracking ref is at
            # commit2: commit1 is ancestor of origin/main -> True.
            proj.revisionExpr = commit1
            proj.work_git.update_ref("refs/remotes/origin/main", commit2)
            self.assertTrue(
                proj._CheckForImmutableRevision(use_superproject=False)
            )

            # 2. When revision is commit2 and upstream tracking ref is at
            # commit1 (behind): commit2 is NOT an ancestor -> False.
            proj.revisionExpr = commit2
            proj.work_git.update_ref("refs/remotes/origin/main", commit1)
            self.assertFalse(
                proj._CheckForImmutableRevision(use_superproject=False)
            )

            # 3. In shallow mode (depth passed), upstream ancestry is skipped:
            # commit2 exists in ODB, so shallow returns True even if upstream
            # is behind.
            self.assertTrue(
                proj._CheckForImmutableRevision(use_superproject=False, depth=1)
            )

            # 4. If gitdir has shallow file, shallow check also skips upstream
            # ancestry.
            shallow_file = os.path.join(proj.gitdir, "shallow")
            with open(shallow_file, "w") as f:
                f.write("")
            self.assertTrue(
                proj._CheckForImmutableRevision(use_superproject=False)
            )
            os.unlink(shallow_file)

            # 5. Tag revisions skip upstream ancestry verification: tag
            # commits are immutable and do not track an upstream branch.
            proj.revisionExpr = "refs/tags/v1.0"
            proj.work_git.tag("-a", "v1.0", "-m", "tag v1.0", commit2)
            self.assertTrue(
                proj._CheckForImmutableRevision(use_superproject=False)
            )

    def test_sync_network_half_stale_upstream_fetches(self) -> None:
        """Sync_NetworkHalf does not skip fetch when upstream ref is behind."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = _create_mock_project(tempdir)
            proj.bare_git = project.Project._GitGetByExec(
                proj, bare=True, gitdir=proj.gitdir
            )
            proj.upstream = "refs/heads/main"
            proj.work_git.config("remote.origin.url", "http://example.com/repo")
            proj.work_git.config(
                "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"
            )

            test_file = os.path.join(tempdir, "file.txt")
            with open(test_file, "w") as f:
                f.write("commit1")
            proj.work_git.add("file.txt")
            proj.work_git.commit("-m", "commit 1")
            commit1 = proj.work_git.rev_parse("HEAD")

            with open(test_file, "w") as f:
                f.write("commit2")
            proj.work_git.add("file.txt")
            proj.work_git.commit("-m", "commit 2")
            commit2 = proj.work_git.rev_parse("HEAD")

            # Upstream ref is at commit1 (behind commit2).
            proj.work_git.update_ref("refs/remotes/origin/main", commit1)
            proj.revisionExpr = commit2

            proj._InitRemote = mock.MagicMock()
            proj._InitMRef = mock.MagicMock()
            proj._RemoteFetch = mock.MagicMock(
                return_value=project.SyncNetworkHalfResult(True)
            )

            res = proj.Sync_NetworkHalf(optimized_fetch=True)
            self.assertTrue(res.success)
            proj._RemoteFetch.assert_called_once()

    def test_should_verify_upstream(self) -> None:
        """Test _ShouldVerifyUpstream conditions."""
        sha = "4f8a3c0000000000000000000000000000000000"
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir, revisionExpr=sha)
            proj.upstream = "refs/heads/main"

            # SHA revision with upstream on non-shallow project -> True.
            self.assertTrue(proj._ShouldVerifyUpstream(use_superproject=False))

            # Not a SHA (e.g. tag or branch name) -> False.
            proj.revisionExpr = "refs/tags/v1.0"
            self.assertFalse(proj._ShouldVerifyUpstream(use_superproject=False))

            # SHA revision but no upstream -> False.
            proj.revisionExpr = sha
            proj.upstream = None
            self.assertFalse(proj._ShouldVerifyUpstream(use_superproject=False))

            # Shallow with depth -> False.
            proj.upstream = "refs/heads/main"
            self.assertFalse(
                proj._ShouldVerifyUpstream(use_superproject=False, depth=1)
            )

            # Shallow with .git/shallow file -> False.
            os.makedirs(proj.gitdir, exist_ok=True)
            with open(os.path.join(proj.gitdir, "shallow"), "w") as f:
                f.write("")
            self.assertFalse(proj._ShouldVerifyUpstream(use_superproject=False))

    def test_is_shallow_and_has_shallow(self) -> None:
        """Test _HasShallow and _IsShallow helpers."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            self.assertFalse(proj._HasShallow())
            self.assertFalse(proj._IsShallow())

            # depth makes _IsShallow True.
            self.assertTrue(proj._IsShallow(depth=1))
            self.assertFalse(proj._HasShallow())

            # shallow file in gitdir makes both True.
            os.makedirs(proj.gitdir, exist_ok=True)
            with open(os.path.join(proj.gitdir, "shallow"), "w") as f:
                f.write("")
            self.assertTrue(proj._HasShallow())
            self.assertTrue(proj._IsShallow())

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


def _create_manifest_project(tempdir: str) -> project.ManifestProject:
    """Return a ManifestProject for a new .repo/ under |tempdir|."""
    repodir = os.path.join(tempdir, ".repo")
    manifest_dir = os.path.join(repodir, "manifests")
    manifest_file = os.path.join(repodir, manifest_xml.MANIFEST_FILE_NAME)
    os.mkdir(repodir)
    os.mkdir(manifest_dir)
    manifest = manifest_xml.XmlManifest(repodir, manifest_file)

    return project.ManifestProject(
        manifest, "test/manifest", os.path.join(tempdir, ".git"), tempdir
    )


class FetchCmdTests(unittest.TestCase):
    """Tests for fetch_cmd feature."""

    def setUpManifest(self, tempdir):
        return _create_manifest_project(tempdir)

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


class ReprojectCmdTests(unittest.TestCase):
    """Tests for the repo.reprojectcmd feature."""

    REVID = "1234abcd" * 5
    HEAD_ID = "5678abcd" * 5
    HEAD_TREE = "cafe0000" * 5
    OTHER_ID = "9abcdef0" * 5
    PUB_ID = "0fedcba9" * 5

    def _get_project(self, tempdir: str) -> project.Project:
        proj = _create_mock_project(
            tempdir, use_local_gitdirs=True, reproject_cmd="echo reproject"
        )
        proj.manifest.path_prefix = ""
        proj.GetRevisionId = mock.MagicMock(return_value=self.REVID)
        proj.IsRebaseInProgress = mock.MagicMock(return_value=False)
        proj.IsCherryPickInProgress = mock.MagicMock(return_value=False)
        proj.work_git = mock.MagicMock()
        proj.work_git.GetHead.return_value = self.HEAD_ID
        proj.work_git.rev_parse.return_value = self.HEAD_TREE
        proj.work_git.GetDotgitPath.side_effect = lambda subpath: os.path.join(
            tempdir, ".git", subpath
        )
        return proj

    @staticmethod
    def _z(*items: str) -> str:
        """Return |items| as NUL-delimited Git output."""
        return "".join(item + "\0" for item in items)

    @staticmethod
    def _git_command(
        staged: str = "", diff: str = "", returncode: int = 0
    ) -> Callable[..., mock.MagicMock]:
        """Return a GitCommand stand-in answering the reproject queries.

        Args:
            staged: `git diff-index -z --cached` or `git ls-files -z` output.
            diff: `git diff-index --cached` postcondition output.
            returncode: exit code of GitCommand.
        """

        def make(
            project: project.Project, cmdv: List[str], **kwargs: Any
        ) -> mock.MagicMock:
            cmd = mock.MagicMock()
            cmd.stderr = ""
            if cmdv[0] == "diff-index":
                if any("^{tree}" in arg for arg in cmdv):
                    cmd.stdout = diff
                else:
                    cmd.stdout = staged
            elif cmdv[0] == "ls-files":
                cmd.stdout = staged
            else:
                cmd.stdout = ""
            cmd.Wait.return_value = returncode
            return cmd

        return make

    def _reproject(
        self, proj: project.Project, **outputs: Any
    ) -> mock.MagicMock:
        """Run _Reproject against mocked Git; return the subprocess mock."""
        with mock.patch(
            "project.GitCommand", side_effect=self._git_command(**outputs)
        ), mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="")
            proj._Reproject(self.REVID)
        return mock_run

    def test_reproject_runs_the_command_with_project_env(self) -> None:
        """Test the command runs from the client root with REPO_TREV set."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            with mock.patch(
                "project.GitCommand", side_effect=self._git_command()
            ), mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="")
                proj._Reproject(self.REVID)

            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(args[0], "echo reproject")
            self.assertTrue(kwargs["shell"])
            self.assertEqual(kwargs["cwd"], tempdir)
            self.assertEqual(kwargs["env"]["REPO_TREV"], self.REVID)
            self.assertEqual(kwargs["env"]["REPO_PATH"], "test-project")

    def test_reproject_rejects_a_staged_change(self) -> None:
        """Test a staged change fails before the command runs."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            with self.assertRaises(project.LocalSyncFail) as e:
                self._reproject(proj, staged=self._z("lib/a.c"))
            self.assertIn(
                "reprojectcmd cannot run with staged changes", str(e.exception)
            )
            self.assertIn("lib/a.c", str(e.exception))

    def test_reproject_unborn_head_rejects_a_staged_change(self) -> None:
        """Test a staged change on unborn HEAD fails before command runs."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.work_git.rev_parse.side_effect = error.GitError("unborn")
            with self.assertRaises(project.LocalSyncFail) as e:
                self._reproject(proj, staged=self._z("lib/a.c"))
            self.assertIn(
                "reprojectcmd cannot run with staged changes", str(e.exception)
            )
            self.assertIn("lib/a.c", str(e.exception))

    def test_reproject_unborn_head_runs_clean(self) -> None:
        """Test a clean unborn HEAD allows the command to run."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.work_git.rev_parse.side_effect = error.GitError("unborn")
            mock_run = self._reproject(proj)
            mock_run.assert_called_once()

    def test_reproject_rejects_an_operation_in_progress(self) -> None:
        """Test an unfinished rebase fails the sync before the command runs."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.IsRebaseInProgress.return_value = True
            with mock.patch("subprocess.run") as mock_run:
                with self.assertRaises(project.LocalSyncFail) as e:
                    proj._Reproject(self.REVID)
            self.assertIn("rebase in progress", str(e.exception))
            mock_run.assert_not_called()

    def test_reproject_surfaces_a_failed_command(self) -> None:
        """Test a non-zero exit fails the sync with the command's output."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            with mock.patch(
                "project.GitCommand", side_effect=self._git_command()
            ), mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(
                    returncode=3, stdout="disk on fire\n"
                )
                with self.assertRaises(project.LocalSyncFail) as e:
                    proj._Reproject(self.REVID)
            self.assertIn("exited with 3", str(e.exception))
            self.assertIn("disk on fire", str(e.exception))

    def test_reproject_rejects_a_moved_head_ref(self) -> None:
        """Test a command that wrote HEAD fails the sync."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.work_git.GetHead.side_effect = [self.HEAD_ID, self.REVID]
            with mock.patch(
                "project.GitCommand", side_effect=self._git_command()
            ), mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="")
                with self.assertRaises(project.LocalSyncFail) as e:
                    proj._Reproject(self.REVID)
            self.assertIn("moved HEAD", str(e.exception))

    def test_reproject_rejects_a_moved_head_oid_on_branch(self) -> None:
        """Test a command that moved a branch pointer fails the sync."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            proj.work_git.GetHead.return_value = "refs/heads/main"
            proj.work_git.rev_parse.side_effect = [
                "tree123",  # HEAD^{tree}
                self.HEAD_ID,  # HEAD before command
                self.REVID,  # HEAD after command
            ]
            with mock.patch(
                "project.GitCommand", side_effect=self._git_command()
            ), mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="")
                with self.assertRaises(project.LocalSyncFail) as e:
                    proj._Reproject(self.REVID)
            self.assertIn("moved HEAD", str(e.exception))

    def test_reproject_rejects_an_index_mismatch(self) -> None:
        """Test a command that left the index off the target fails the sync."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_project(tempdir)
            with mock.patch(
                "project.GitCommand",
                side_effect=self._git_command(diff="lib/a.c\n"),
            ), mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="")
                with self.assertRaises(project.LocalSyncFail) as e:
                    proj._Reproject(self.REVID)
            self.assertIn(self.REVID, str(e.exception))
            self.assertIn("lib/a.c", str(e.exception))

    def _get_synced_project(
        self,
        tempdir: str,
        head: Optional[str],
        branch: Optional[str] = None,
        upstream_gain: Sequence[str] = (),
        local_changes: Sequence[str] = (),
    ) -> project.Project:
        """Return a project ready for Sync_LocalHalf with Git mocked out.

        Args:
            head: The commit HEAD is at, or None for an unborn branch.
            branch: The name of the checked out branch, or None if detached.
            upstream_gain: The commits the target has that HEAD lacks.
            local_changes: The "<sha> <email>" lines HEAD has that the target
                lacks.
        """
        proj = self._get_project(tempdir)
        for name in (
            "_InitWorkTree",
            "CleanPublishedCache",
            "_CopyAndLinkFiles",
            "_Reproject",
            "_Checkout",
            "_FastForward",
            "_ResetHard",
            "_Rebase",
        ):
            setattr(proj, name, mock.MagicMock())
        proj.IsDirty = mock.MagicMock(return_value=False)
        proj._userident_name = "Me"
        proj._userident_email = "me@example.com"

        proj.bare_ref = mock.MagicMock()
        if branch:
            proj.bare_ref.head = project.R_HEADS + branch
            proj.bare_ref.all = {project.R_HEADS + branch: head} if head else {}
            # A branch that does not track upstream; tests that need one
            # tracking upstream replace this with _tracking_branch().
            proj.GetBranch = mock.MagicMock(
                return_value=self._tracking_branch(branch, merge=None)
            )
        else:
            proj.bare_ref.head = head
            proj.bare_ref.all = {}

        def _revlist(*args: Any, **kwargs: Any) -> List[str]:
            if kwargs.get("format"):
                return list(local_changes)
            if args[0] == project.not_rev(project.HEAD):
                return list(upstream_gain)
            if args[1] == self.PUB_ID:
                return [self.PUB_ID]
            return []

        proj._revlist = mock.MagicMock(side_effect=_revlist)
        return proj

    @staticmethod
    def _tracking_branch(
        name: str = "topic", merge: Optional[str] = "main"
    ) -> mock.MagicMock:
        """Return a branch tracking |merge| upstream, or nothing if None."""
        branch = mock.MagicMock()
        branch.name = name
        branch.merge = merge
        branch.LocalMerge = f"refs/remotes/origin/{merge}" if merge else None
        return branch

    def test_sync_local_half_materializes_a_fresh_project(self) -> None:
        """Test a project with an unborn HEAD is checked out by the command."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(tempdir, head=None, branch="main")
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Reproject.assert_called_once_with(self.REVID, verbose=False)
            proj.work_git.DetachHead.assert_called_once_with(
                self.REVID,
                message=f"checkout: moving from main to {self.REVID}",
            )
            proj._Checkout.assert_not_called()
            proj._CopyAndLinkFiles.assert_called_once_with()

    def test_sync_local_half_detached_head_uses_the_command(self) -> None:
        """Test a detached HEAD is moved to the target by the command."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(tempdir, head=self.HEAD_ID)
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Reproject.assert_called_once_with(self.REVID, verbose=False)
            proj.work_git.DetachHead.assert_called_once_with(
                self.REVID,
                message=f"checkout: moving from {self.HEAD_ID} to {self.REVID}",
            )
            proj._Checkout.assert_not_called()

    def test_sync_local_half_head_at_target_skips_the_command(self) -> None:
        """Test `repo sync -d` at the target only detaches HEAD."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(
                tempdir, head=self.REVID, branch="topic"
            )
            syncbuf = project.SyncBuffer(proj.config, detach_head=True)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Reproject.assert_not_called()
            proj.work_git.DetachHead.assert_called_once()
            self.assertEqual(
                proj.work_git.DetachHead.call_args[0][0], self.REVID
            )

    def test_sync_local_half_command_failure_fails_the_project(self) -> None:
        """Test a failed command is reported and leaves the ref alone."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(tempdir, head=self.HEAD_ID)
            proj._Reproject.side_effect = project.LocalSyncFail(
                "reprojectcmd exited with 1", project=proj.name
            )
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertFalse(syncbuf.Finish())
            self.assertEqual(len(syncbuf.errors), 1)
            self.assertIn("exited with 1", str(syncbuf.errors[0]))
            proj.work_git.DetachHead.assert_not_called()
            proj._CopyAndLinkFiles.assert_not_called()

    def test_sync_local_half_fast_forward_uses_the_command(self) -> None:
        """Test a branch behind the target is fast-forwarded by the command."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(
                tempdir,
                head=self.HEAD_ID,
                branch="topic",
                upstream_gain=[self.REVID],
            )
            proj.GetBranch = mock.MagicMock(
                return_value=self._tracking_branch()
            )
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Reproject.assert_called_once_with(self.REVID, verbose=False)
            proj.work_git.UpdateRef.assert_called_once_with(
                project.HEAD,
                self.REVID,
                old=self.HEAD_ID,
                message=f"merge {self.REVID}: Fast-forward",
            )
            proj._FastForward.assert_not_called()
            proj._CopyAndLinkFiles.assert_called_once_with()

    def test_sync_local_half_head_ahead_skips_the_command(self) -> None:
        """Test a published branch ahead of the target is left alone."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(
                tempdir, head=self.HEAD_ID, branch="topic"
            )
            proj.GetBranch = mock.MagicMock(
                return_value=self._tracking_branch()
            )
            proj.work_git.merge_base.side_effect = error.GitError("no")
            proj.WasPublished = mock.MagicMock(return_value=self.PUB_ID)
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Reproject.assert_not_called()
            proj.work_git.UpdateRef.assert_not_called()
            proj._FastForward.assert_not_called()
            proj._CopyAndLinkFiles.assert_called_once_with()

    def test_sync_local_half_hard_reset_uses_the_command(self) -> None:
        """Test a branch whose commits upstream dropped is reset by it."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(
                tempdir,
                head=self.HEAD_ID,
                branch="topic",
                upstream_gain=[self.REVID],
                local_changes=[f"{self.OTHER_ID} other@example.com"],
            )
            proj.GetBranch = mock.MagicMock(
                return_value=self._tracking_branch()
            )
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Reproject.assert_called_once_with(self.REVID, verbose=False)
            proj.work_git.UpdateRef.assert_called_once_with(
                project.HEAD,
                self.REVID,
                old=self.HEAD_ID,
                message=f"reset: moving to {self.REVID}",
            )
            proj._ResetHard.assert_not_called()

    def test_sync_local_half_rebase_is_not_delegated(self) -> None:
        """Test a branch carrying the user's commits is rebased by Git."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(
                tempdir,
                head=self.HEAD_ID,
                branch="topic",
                upstream_gain=[self.REVID],
                local_changes=[f"{self.OTHER_ID} me@example.com"],
            )
            proj.GetBranch = mock.MagicMock(
                return_value=self._tracking_branch()
            )
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Rebase.assert_called_once_with(
                upstream=f"{self.OTHER_ID}^1", onto=self.REVID
            )
            proj._Reproject.assert_not_called()
            proj.work_git.UpdateRef.assert_not_called()

    def test_sync_local_half_rejects_a_nested_project(self) -> None:
        """Test a submodule or nested project fails before any checkout."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(tempdir, head=self.HEAD_ID)
            proj.parent = mock.MagicMock()
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertFalse(syncbuf.Finish())
            self.assertIn("nested", str(syncbuf.errors[0]))
            proj._InitWorkTree.assert_not_called()
            proj._Reproject.assert_not_called()

    def test_sync_local_half_without_the_command_uses_git(self) -> None:
        """Test Git keeps doing the checkout when the command is not set."""
        with utils_for_test.TempGitTree() as tempdir:
            proj = self._get_synced_project(tempdir, head=self.HEAD_ID)
            proj.manifest.manifestProject.reproject_cmd = None
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)

            self.assertTrue(syncbuf.Finish())
            proj._Checkout.assert_called_once_with(
                self.REVID, force_checkout=False, quiet=True
            )
            proj._Reproject.assert_not_called()
            proj.work_git.DetachHead.assert_not_called()

    def test_metaproject_never_uses_the_command(self) -> None:
        """Test .repo/manifests and .repo/repo are checked out by Git."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = _create_manifest_project(tempdir)
            fakeproj.config.SetString("repo.reprojectcmd", "echo hi")
            fakeproj.config.SetBoolean("repo.uselocalgitdirs", True)
            self.assertFalse(fakeproj.UseReprojectCmd)

    def test_sync_reproject_cmd_requires_use_local_gitdirs(self) -> None:
        """Test that repo.reprojectcmd requires repo.uselocalgitdirs."""
        with utils_for_test.TempGitTree() as tempdir:
            fakeproj = _create_manifest_project(tempdir)

            class DummyManifest:
                is_submanifest = False

                def GetDefaultGroupsStr(
                    self, with_platform: bool = False
                ) -> str:
                    return ""

            fakeproj.manifest = DummyManifest()

            fakeproj.config.SetString("repo.reprojectcmd", "echo hi")
            fakeproj.config.SetBoolean("repo.uselocalgitdirs", False)

            result = fakeproj.Sync(use_local_gitdirs=False)
            self.assertFalse(result)


class ReprojectCmdGitTests(unittest.TestCase):
    """Tests running the reprojectcmd contract against a real Git checkout."""

    READ_TREE = "git -C $REPO_PATH read-tree -m -u $REPO_TREV"

    @staticmethod
    def _git(cwd: str, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", cwd] + list(args),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        ).stdout.rstrip("\n")

    def _make_client(
        self, topdir: str, reproject_cmd: Optional[str]
    ) -> Tuple[project.Project, str]:
        """Set up a fetched, never checked out project under |topdir|.

        Returns:
            The project and the commit its manifest revision names.
        """
        # A remote holding the history the project fetches.
        remote = os.path.join(topdir, "remote")
        os.mkdir(remote)
        self._git(remote, "init", "-q")
        self._git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
        for msg, files in (
            ("one", {"one.txt": "one\n", "keep.txt": "keep\n"}),
            ("two", {"one.txt": "one, revised\n", "two.txt": "two\n"}),
        ):
            for name, content in files.items():
                with open(os.path.join(remote, name), "w") as fp:
                    fp.write(content)
                self._git(remote, "add", name)
            self._git(
                remote,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-q",
                "-m",
                msg,
            )
        revid = self._git(remote, "rev-parse", "HEAD")

        # The project as repo.fetchcmd leaves it: objects fetched, HEAD on an
        # unborn branch, nothing in the index or the worktree.
        worktree = os.path.join(topdir, "proj")
        os.mkdir(worktree)
        self._git(worktree, "init", "-q")
        self._git(worktree, "symbolic-ref", "HEAD", "refs/heads/main")
        self._git(worktree, "fetch", "-q", remote, "refs/heads/main")

        manifest = mock.MagicMock()
        manifest.manifestProject.use_local_gitdirs = True
        manifest.manifestProject.reproject_cmd = reproject_cmd
        manifest.UseLocalGitDirs = True
        manifest.IsMirror = False
        manifest.is_multimanifest = False
        manifest.topdir = topdir
        manifest.path_prefix = ""
        manifest.globalConfig = None

        remote_spec = mock.MagicMock()
        remote_spec.name = "origin"
        remote_spec.url = remote

        proj = project.Project(
            manifest=manifest,
            name="proj",
            remote=remote_spec,
            gitdir=os.path.join(worktree, ".git"),
            objdir=os.path.join(worktree, ".git"),
            worktree=worktree,
            relpath="proj",
            revisionExpr="main",
            revisionId=revid,
        )
        proj._Checkout = mock.MagicMock(
            side_effect=AssertionError("Git must not do the checkout")
        )
        return proj, revid

    def _sync(self, proj: project.Project) -> Tuple[bool, List[Any]]:
        """Run Sync_LocalHalf; return whether it succeeded and its errors."""
        syncbuf = project.SyncBuffer(proj.config)
        proj.Sync_LocalHalf(syncbuf)
        return syncbuf.Finish(), syncbuf.errors

    def _step_back(self, proj: project.Project, revid: str) -> str:
        """Put the project cleanly at the commit before |revid|, with Git."""
        parent = self._git(proj.worktree, "rev-parse", revid + "~1")
        self._git(proj.worktree, "update-ref", "--no-deref", "HEAD", parent)
        self._git(proj.worktree, "read-tree", "-u", "--reset", "HEAD")
        return parent

    def test_sync_local_half_checks_out_a_fresh_project(self) -> None:
        """Test the read-tree command materializes a project like Git would."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            marker = os.path.join(topdir, "ran")
            proj, revid = self._make_client(
                topdir, f"{self.READ_TREE} && touch {marker}"
            )
            worktree = proj.worktree

            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)
            self.assertTrue(syncbuf.Finish(), syncbuf.errors)

            self.assertTrue(os.path.exists(marker))
            self.assertEqual(self._git(worktree, "rev-parse", "HEAD"), revid)
            with self.assertRaises(subprocess.CalledProcessError):
                self._git(worktree, "symbolic-ref", "-q", "HEAD")
            self.assertEqual(self._git(worktree, "status", "--porcelain"), "")
            with open(os.path.join(worktree, "one.txt")) as fp:
                self.assertEqual(fp.read(), "one, revised\n")
            with open(os.path.join(worktree, "two.txt")) as fp:
                self.assertEqual(fp.read(), "two\n")

            # Syncing again finds HEAD at the target and leaves it alone.
            os.remove(marker)
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)
            self.assertTrue(syncbuf.Finish(), syncbuf.errors)
            self.assertFalse(os.path.exists(marker))
            self.assertEqual(self._git(worktree, "rev-parse", "HEAD"), revid)

    def test_sync_local_half_leaves_an_untracked_file_in_the_way_alone(
        self,
    ) -> None:
        """Test an untracked file the target adds fails without any change."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(topdir, self.READ_TREE)
            worktree = proj.worktree
            with open(os.path.join(worktree, "two.txt"), "w") as fp:
                fp.write("mine\n")

            clean, errors = self._sync(proj)
            self.assertFalse(clean)
            self.assertIn("two.txt", str(errors[0]))

            self.assertEqual(
                self._git(worktree, "symbolic-ref", "HEAD"), "refs/heads/main"
            )
            self.assertEqual(sorted(os.listdir(worktree)), [".git", "two.txt"])
            with open(os.path.join(worktree, "two.txt")) as fp:
                self.assertEqual(fp.read(), "mine\n")

    def test_sync_local_half_keeps_local_changes_out_of_the_way(self) -> None:
        """Test edits and untracked files the target leaves alone survive."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(topdir, self.READ_TREE)
            worktree = proj.worktree
            self.assertTrue(self._sync(proj)[0])
            self._step_back(proj, revid)
            with open(os.path.join(worktree, "keep.txt"), "w") as fp:
                fp.write("edited\n")
            with open(os.path.join(worktree, "junk"), "w") as fp:
                fp.write("junk\n")

            clean, errors = self._sync(proj)
            self.assertTrue(clean, errors)

            self.assertEqual(self._git(worktree, "rev-parse", "HEAD"), revid)
            with open(os.path.join(worktree, "one.txt")) as fp:
                self.assertEqual(fp.read(), "one, revised\n")
            with open(os.path.join(worktree, "keep.txt")) as fp:
                self.assertEqual(fp.read(), "edited\n")
            self.assertEqual(
                self._git(worktree, "status", "--porcelain").splitlines(),
                [" M keep.txt", "?? junk"],
            )

    def test_sync_local_half_rejects_a_local_change_in_the_way(self) -> None:
        """Test an edit to a file the target changes fails without a change."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(topdir, self.READ_TREE)
            worktree = proj.worktree
            self.assertTrue(self._sync(proj)[0])
            parent = self._step_back(proj, revid)
            with open(os.path.join(worktree, "one.txt"), "w") as fp:
                fp.write("edited\n")

            clean, errors = self._sync(proj)
            self.assertFalse(clean)
            self.assertIn("one.txt", str(errors[0]))

            self.assertEqual(self._git(worktree, "rev-parse", "HEAD"), parent)
            with open(os.path.join(worktree, "one.txt")) as fp:
                self.assertEqual(fp.read(), "edited\n")
            self.assertNotIn("two.txt", os.listdir(worktree))

    def test_sync_local_half_rejects_a_command_that_moves_head(self) -> None:
        """Test a command that writes HEAD fails the postcondition."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(
                topdir,
                f"{self.READ_TREE} && git -C $REPO_PATH update-ref "
                "--no-deref HEAD $REPO_TREV",
            )
            syncbuf = project.SyncBuffer(proj.config)
            proj.Sync_LocalHalf(syncbuf)
            self.assertFalse(syncbuf.Finish())
            self.assertIn("moved HEAD", str(syncbuf.errors[0]))

    def test_sync_local_half_rejects_staged_changes(self) -> None:
        """Test a staged change fails before the command runs."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(topdir, self.READ_TREE)
            worktree = proj.worktree
            self.assertTrue(self._sync(proj)[0])
            self._step_back(proj, revid)
            with open(os.path.join(worktree, "keep.txt"), "w") as fp:
                fp.write("staged\n")
            self._git(worktree, "add", "keep.txt")

            clean, errors = self._sync(proj)
            self.assertFalse(clean)
            self.assertIn("staged changes", str(errors[0]))
            self.assertIn("keep.txt", str(errors[0]))

    def test_sync_local_half_rejects_a_command_that_moves_branch_tip(
        self,
    ) -> None:
        """Test a command that moves the branch commit fails postcondition."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(
                topdir,
                f"{self.READ_TREE} && git -C $REPO_PATH update-ref "
                "refs/heads/main $REPO_TREV",
            )
            clean, errors = self._sync(proj)
            self.assertFalse(clean)
            self.assertIn("moved HEAD", str(errors[0]))

    def test_sync_local_half_keeps_local_changes_on_tracking_branch(
        self,
    ) -> None:
        """Test benign edits survive fast-forward on a tracking branch."""
        with tempfile.TemporaryDirectory(prefix="repo-tests") as topdir:
            proj, revid = self._make_client(topdir, self.READ_TREE)
            worktree = proj.worktree
            self.assertTrue(self._sync(proj)[0])
            parent = self._step_back(proj, revid)
            self._git(worktree, "checkout", "-q", "-b", "main", parent)
            self._git(worktree, "config", "branch.main.remote", "origin")
            self._git(
                worktree, "config", "branch.main.merge", "refs/heads/main"
            )
            with open(os.path.join(worktree, "keep.txt"), "w") as fp:
                fp.write("edited\n")
            with open(os.path.join(worktree, "junk"), "w") as fp:
                fp.write("junk\n")

            clean, errors = self._sync(proj)
            self.assertTrue(clean, errors)

            self.assertEqual(self._git(worktree, "rev-parse", "HEAD"), revid)
            with open(os.path.join(worktree, "one.txt")) as fp:
                self.assertEqual(fp.read(), "one, revised\n")
            with open(os.path.join(worktree, "keep.txt")) as fp:
                self.assertEqual(fp.read(), "edited\n")
            self.assertEqual(
                self._git(worktree, "status", "--porcelain").splitlines(),
                [" M keep.txt", "?? junk"],
            )
