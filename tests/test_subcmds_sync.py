# Copyright (C) 2022 The Android Open Source Project
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
"""Unittests for the subcmds/sync.py module."""

import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import pytest

import command
from error import GitError
from error import RepoExitError
from project import SyncNetworkHalfResult
from subcmds import sync


@pytest.mark.parametrize(
    "use_superproject, cli_args, result",
    [
        (True, ["--current-branch"], True),
        (True, ["--no-current-branch"], True),
        (True, [], True),
        (False, ["--current-branch"], True),
        (False, ["--no-current-branch"], False),
        (False, [], None),
    ],
)
def test_get_current_branch_only(use_superproject, cli_args, result):
    """Test Sync._GetCurrentBranchOnly logic.

    Sync._GetCurrentBranchOnly should return True if a superproject is
    requested, and otherwise the value of the current_branch_only option.
    """
    cmd = sync.Sync()
    opts, _ = cmd.OptionParser.parse_args(cli_args)

    with mock.patch(
        "git_superproject.UseSuperproject", return_value=use_superproject
    ):
        assert cmd._GetCurrentBranchOnly(opts, cmd.manifest) == result


# Used to patch os.cpu_count() for reliable results.
OS_CPU_COUNT = 24


@pytest.mark.parametrize(
    "argv, jobs_manifest, jobs, jobs_net, jobs_check",
    [
        # No user or manifest settings.
        ([], None, OS_CPU_COUNT, 1, command.DEFAULT_LOCAL_JOBS),
        # No user settings, so manifest settings control.
        ([], 3, 3, 3, 3),
        # User settings, but no manifest.
        (["--jobs=4"], None, 4, 4, 4),
        (["--jobs=4", "--jobs-network=5"], None, 4, 5, 4),
        (["--jobs=4", "--jobs-checkout=6"], None, 4, 4, 6),
        (["--jobs=4", "--jobs-network=5", "--jobs-checkout=6"], None, 4, 5, 6),
        (
            ["--jobs-network=5"],
            None,
            OS_CPU_COUNT,
            5,
            command.DEFAULT_LOCAL_JOBS,
        ),
        (["--jobs-checkout=6"], None, OS_CPU_COUNT, 1, 6),
        (["--jobs-network=5", "--jobs-checkout=6"], None, OS_CPU_COUNT, 5, 6),
        # User settings with manifest settings.
        (["--jobs=4"], 3, 4, 4, 4),
        (["--jobs=4", "--jobs-network=5"], 3, 4, 5, 4),
        (["--jobs=4", "--jobs-checkout=6"], 3, 4, 4, 6),
        (["--jobs=4", "--jobs-network=5", "--jobs-checkout=6"], 3, 4, 5, 6),
        (["--jobs-network=5"], 3, 3, 5, 3),
        (["--jobs-checkout=6"], 3, 3, 3, 6),
        (["--jobs-network=5", "--jobs-checkout=6"], 3, 3, 5, 6),
        # Settings that exceed rlimits get capped.
        (["--jobs=1000000"], None, 83, 83, 83),
        ([], 1000000, 83, 83, 83),
    ],
)
def test_cli_jobs(argv, jobs_manifest, jobs, jobs_net, jobs_check):
    """Tests --jobs option behavior."""
    mp = mock.MagicMock()
    mp.manifest.default.sync_j = jobs_manifest

    cmd = sync.Sync()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)

    with mock.patch.object(sync, "_rlimit_nofile", return_value=(256, 256)):
        with mock.patch.object(os, "cpu_count", return_value=OS_CPU_COUNT):
            cmd._ValidateOptionsWithManifest(opts, mp)
            assert opts.jobs == jobs
            assert opts.jobs_network == jobs_net
            assert opts.jobs_checkout == jobs_check


class LocalSyncState(unittest.TestCase):
    """Tests for LocalSyncState."""

    _TIME = 10

    def setUp(self):
        """Common setup."""
        self.topdir = tempfile.mkdtemp("LocalSyncState")
        self.repodir = os.path.join(self.topdir, ".repo")
        os.makedirs(self.repodir)

        self.manifest = mock.MagicMock(
            topdir=self.topdir,
            repodir=self.repodir,
            repoProject=mock.MagicMock(relpath=".repo/repo"),
        )
        self.state = self._new_state()

    def tearDown(self):
        """Common teardown."""
        shutil.rmtree(self.topdir)

    def _new_state(self, time=_TIME):
        with mock.patch("time.time", return_value=time):
            return sync.LocalSyncState(self.manifest)

    def test_set(self):
        """Times are set."""
        p = mock.MagicMock(relpath="projA")
        self.state.SetFetchTime(p)
        self.state.SetCheckoutTime(p)
        self.assertEqual(self.state.GetFetchTime(p), self._TIME)
        self.assertEqual(self.state.GetCheckoutTime(p), self._TIME)

    def test_update(self):
        """Times are updated."""
        with open(self.state._path, "w") as f:
            f.write(
                """
            {
              "projB": {
                "last_fetch": 5,
                "last_checkout": 7
              }
            }
            """
            )

        # Initialize state to read from the new file.
        self.state = self._new_state()
        projA = mock.MagicMock(relpath="projA")
        projB = mock.MagicMock(relpath="projB")
        self.assertEqual(self.state.GetFetchTime(projA), None)
        self.assertEqual(self.state.GetFetchTime(projB), 5)
        self.assertEqual(self.state.GetCheckoutTime(projB), 7)

        self.state.SetFetchTime(projA)
        self.state.SetFetchTime(projB)
        self.assertEqual(self.state.GetFetchTime(projA), self._TIME)
        self.assertEqual(self.state.GetFetchTime(projB), self._TIME)
        self.assertEqual(self.state.GetCheckoutTime(projB), 7)

    def test_save_to_file(self):
        """Data is saved under repodir."""
        p = mock.MagicMock(relpath="projA")
        self.state.SetFetchTime(p)
        self.state.Save()
        self.assertEqual(
            os.listdir(self.repodir), [".repo_localsyncstate.json"]
        )

    def test_partial_sync(self):
        """Partial sync state is detected."""
        with open(self.state._path, "w") as f:
            f.write(
                """
            {
              "projA": {
                "last_fetch": 5,
                "last_checkout": 5
              },
              "projB": {
                "last_fetch": 5,
                "last_checkout": 5
              }
            }
            """
            )

        # Initialize state to read from the new file.
        self.state = self._new_state()
        projB = mock.MagicMock(relpath="projB")
        self.assertEqual(self.state.IsPartiallySynced(), False)

        self.state.SetFetchTime(projB)
        self.state.SetCheckoutTime(projB)
        self.assertEqual(self.state.IsPartiallySynced(), True)

    def test_ignore_repo_project(self):
        """Sync data for repo project is ignored when checking partial sync."""
        p = mock.MagicMock(relpath="projA")
        self.state.SetFetchTime(p)
        self.state.SetCheckoutTime(p)
        self.state.SetFetchTime(self.manifest.repoProject)
        self.state.Save()
        self.assertEqual(self.state.IsPartiallySynced(), False)

        self.state = self._new_state(self._TIME + 1)
        self.state.SetFetchTime(self.manifest.repoProject)
        self.assertEqual(
            self.state.GetFetchTime(self.manifest.repoProject), self._TIME + 1
        )
        self.assertEqual(self.state.GetFetchTime(p), self._TIME)
        self.assertEqual(self.state.IsPartiallySynced(), False)

    def test_nonexistent_project(self):
        """Unsaved projects don't have data."""
        p = mock.MagicMock(relpath="projC")
        self.assertEqual(self.state.GetFetchTime(p), None)
        self.assertEqual(self.state.GetCheckoutTime(p), None)

    def test_prune_removed_projects(self):
        """Removed projects are pruned."""
        with open(self.state._path, "w") as f:
            f.write(
                """
            {
              "projA": {
                "last_fetch": 5
              },
              "projB": {
                "last_fetch": 7
              }
            }
            """
            )

        def mock_exists(path):
            if "projA" in path:
                return False
            return True

        projA = mock.MagicMock(relpath="projA")
        projB = mock.MagicMock(relpath="projB")
        self.state = self._new_state()
        self.assertEqual(self.state.GetFetchTime(projA), 5)
        self.assertEqual(self.state.GetFetchTime(projB), 7)
        with mock.patch("os.path.exists", side_effect=mock_exists):
            self.state.PruneRemovedProjects()
        self.assertIsNone(self.state.GetFetchTime(projA))

        self.state = self._new_state()
        self.assertIsNone(self.state.GetFetchTime(projA))
        self.assertEqual(self.state.GetFetchTime(projB), 7)

    def test_prune_removed_and_symlinked_projects(self):
        """Removed projects that still exists on disk as symlink are pruned."""
        with open(self.state._path, "w") as f:
            f.write(
                """
            {
              "projA": {
                "last_fetch": 5
              },
              "projB": {
                "last_fetch": 7
              }
            }
            """
            )

        def mock_exists(path):
            return True

        def mock_islink(path):
            if "projB" in path:
                return True
            return False

        projA = mock.MagicMock(relpath="projA")
        projB = mock.MagicMock(relpath="projB")
        self.state = self._new_state()
        self.assertEqual(self.state.GetFetchTime(projA), 5)
        self.assertEqual(self.state.GetFetchTime(projB), 7)
        with mock.patch("os.path.exists", side_effect=mock_exists):
            with mock.patch("os.path.islink", side_effect=mock_islink):
                self.state.PruneRemovedProjects()
        self.assertIsNone(self.state.GetFetchTime(projB))

        self.state = self._new_state()
        self.assertIsNone(self.state.GetFetchTime(projB))
        self.assertEqual(self.state.GetFetchTime(projA), 5)


class FakeProject:
    def __init__(self, relpath, name=None, objdir=None):
        self.relpath = relpath
        self.name = name or relpath
        self.objdir = objdir or relpath
        self.worktree = relpath

        self.use_git_worktrees = False
        self.UseAlternates = False
        self.manifest = mock.MagicMock()
        self.manifest.GetProjectsWithName.return_value = [self]
        self.config = mock.MagicMock()
        self.EnableRepositoryExtension = mock.MagicMock()

    def RelPath(self, local=None):
        return self.relpath

    def __str__(self):
        return f"project: {self.relpath}"

    def __repr__(self):
        return str(self)


class SafeCheckoutOrder(unittest.TestCase):
    def test_no_nested(self):
        p_f = FakeProject("f")
        p_foo = FakeProject("foo")
        out = sync._SafeCheckoutOrder([p_f, p_foo])
        self.assertEqual(out, [[p_f, p_foo]])

    def test_basic_nested(self):
        p_foo = p_foo = FakeProject("foo")
        p_foo_bar = FakeProject("foo/bar")
        out = sync._SafeCheckoutOrder([p_foo, p_foo_bar])
        self.assertEqual(out, [[p_foo], [p_foo_bar]])

    def test_complex_nested(self):
        p_foo = FakeProject("foo")
        p_foobar = FakeProject("foobar")
        p_foo_dash_bar = FakeProject("foo-bar")
        p_foo_bar = FakeProject("foo/bar")
        p_foo_bar_baz_baq = FakeProject("foo/bar/baz/baq")
        p_bar = FakeProject("bar")
        out = sync._SafeCheckoutOrder(
            [
                p_foo_bar_baz_baq,
                p_foo,
                p_foobar,
                p_foo_dash_bar,
                p_foo_bar,
                p_bar,
            ]
        )
        self.assertEqual(
            out,
            [
                [p_bar, p_foo, p_foo_dash_bar, p_foobar],
                [p_foo_bar],
                [p_foo_bar_baz_baq],
            ],
        )


class Chunksize(unittest.TestCase):
    """Tests for _chunksize."""

    def test_single_project(self):
        """Single project."""
        self.assertEqual(sync._chunksize(1, 1), 1)

    def test_low_project_count(self):
        """Multiple projects, low number of projects to sync."""
        self.assertEqual(sync._chunksize(10, 1), 10)
        self.assertEqual(sync._chunksize(10, 2), 5)
        self.assertEqual(sync._chunksize(10, 4), 2)
        self.assertEqual(sync._chunksize(10, 8), 1)
        self.assertEqual(sync._chunksize(10, 16), 1)

    def test_high_project_count(self):
        """Multiple projects, high number of projects to sync."""
        self.assertEqual(sync._chunksize(2800, 1), 32)
        self.assertEqual(sync._chunksize(2800, 16), 32)
        self.assertEqual(sync._chunksize(2800, 32), 32)
        self.assertEqual(sync._chunksize(2800, 64), 32)
        self.assertEqual(sync._chunksize(2800, 128), 21)


class GetPreciousObjectsState(unittest.TestCase):
    """Tests for _GetPreciousObjectsState."""

    def setUp(self):
        """Common setup."""
        self.cmd = sync.Sync()
        self.project = p = mock.MagicMock(
            use_git_worktrees=False, UseAlternates=False
        )
        p.manifest.GetProjectsWithName.return_value = [p]

        self.opt = mock.Mock(spec_set=["this_manifest_only"])
        self.opt.this_manifest_only = False

    def test_worktrees(self):
        """False for worktrees."""
        self.project.use_git_worktrees = True
        self.assertFalse(
            self.cmd._GetPreciousObjectsState(self.project, self.opt)
        )

    def test_not_shared(self):
        """Singleton project."""
        self.assertFalse(
            self.cmd._GetPreciousObjectsState(self.project, self.opt)
        )

    def test_shared(self):
        """Shared project."""
        self.project.manifest.GetProjectsWithName.return_value = [
            self.project,
            self.project,
        ]
        self.assertTrue(
            self.cmd._GetPreciousObjectsState(self.project, self.opt)
        )

    def test_shared_with_alternates(self):
        """Shared project, with alternates."""
        self.project.manifest.GetProjectsWithName.return_value = [
            self.project,
            self.project,
        ]
        self.project.UseAlternates = True
        self.assertFalse(
            self.cmd._GetPreciousObjectsState(self.project, self.opt)
        )

    def test_not_found(self):
        """Project not found in manifest."""
        self.project.manifest.GetProjectsWithName.return_value = []
        self.assertFalse(
            self.cmd._GetPreciousObjectsState(self.project, self.opt)
        )


class SyncCommand(unittest.TestCase):
    """Tests for cmd.Execute."""

    def setUp(self):
        """Common setup."""
        self.repodir = tempfile.mkdtemp(".repo")
        self.manifest = manifest = mock.MagicMock(
            repodir=self.repodir,
        )

        git_event_log = mock.MagicMock(ErrorEvent=mock.Mock(return_value=None))
        self.outer_client = outer_client = mock.MagicMock()
        outer_client.manifest.IsArchive = True
        manifest.manifestProject.worktree = "worktree_path/"
        manifest.repoProject.LastFetch = time.time()
        self.sync_network_half_error = None
        self.sync_local_half_error = None
        self.cmd = sync.Sync(
            manifest=manifest,
            outer_client=outer_client,
            git_event_log=git_event_log,
        )

        def Sync_NetworkHalf(*args, **kwargs):
            return SyncNetworkHalfResult(True, self.sync_network_half_error)

        def Sync_LocalHalf(*args, **kwargs):
            if self.sync_local_half_error:
                raise self.sync_local_half_error

        self.project = p = mock.MagicMock(
            use_git_worktrees=False,
            UseAlternates=False,
            name="project",
            Sync_NetworkHalf=Sync_NetworkHalf,
            Sync_LocalHalf=Sync_LocalHalf,
            RelPath=mock.Mock(return_value="rel_path"),
        )
        p.manifest.GetProjectsWithName.return_value = [p]

        mock.patch.object(
            sync,
            "_PostRepoFetch",
            return_value=None,
        ).start()

        mock.patch.object(
            self.cmd, "GetProjects", return_value=[self.project]
        ).start()

        opt, _ = self.cmd.OptionParser.parse_args([])
        opt.clone_bundle = False
        opt.jobs = 4
        opt.quiet = True
        opt.use_superproject = False
        opt.current_branch_only = True
        opt.optimized_fetch = True
        opt.retry_fetches = 1
        opt.prune = False
        opt.auto_gc = False
        opt.repo_verify = False
        self.opt = opt

    def tearDown(self):
        mock.patch.stopall()

    def test_command_exit_error(self):
        """Ensure unsuccessful commands raise expected errors."""
        self.sync_network_half_error = GitError(
            "sync_network_half_error error", project=self.project
        )
        self.sync_local_half_error = GitError(
            "sync_local_half_error", project=self.project
        )
        with self.assertRaises(RepoExitError) as e:
            self.cmd.Execute(self.opt, [])
            self.assertIn(self.sync_local_half_error, e.aggregate_errors)
            self.assertIn(self.sync_network_half_error, e.aggregate_errors)


class SyncUpdateRepoProject(unittest.TestCase):
    """Tests for Sync._UpdateRepoProject."""

    def setUp(self):
        """Common setup."""
        self.repodir = tempfile.mkdtemp(".repo")
        self.manifest = manifest = mock.MagicMock(repodir=self.repodir)
        # Create a repoProject with a mock Sync_NetworkHalf.
        repoProject = mock.MagicMock(name="repo")
        repoProject.Sync_NetworkHalf = mock.Mock(
            return_value=SyncNetworkHalfResult(True, None)
        )
        manifest.repoProject = repoProject
        manifest.IsArchive = False
        manifest.CloneFilter = None
        manifest.PartialCloneExclude = None
        manifest.CloneFilterForDepth = None

        git_event_log = mock.MagicMock(ErrorEvent=mock.Mock(return_value=None))
        self.cmd = sync.Sync(manifest=manifest, git_event_log=git_event_log)

        opt, _ = self.cmd.OptionParser.parse_args([])
        opt.local_only = False
        opt.repo_verify = False
        opt.verbose = False
        opt.quiet = True
        opt.force_sync = False
        opt.clone_bundle = False
        opt.tags = False
        opt.optimized_fetch = False
        opt.retry_fetches = 0
        opt.prune = False
        self.opt = opt
        self.errors = []

        mock.patch.object(sync.Sync, "_GetCurrentBranchOnly").start()

    def tearDown(self):
        shutil.rmtree(self.repodir)
        mock.patch.stopall()

    def test_fetches_when_stale(self):
        """Test it fetches when the repo project is stale."""
        self.manifest.repoProject.LastFetch = time.time() - (
            sync._ONE_DAY_S + 1
        )

        with mock.patch.object(sync, "_PostRepoFetch") as mock_post_fetch:
            self.cmd._UpdateRepoProject(self.opt, self.manifest, self.errors)
            self.manifest.repoProject.Sync_NetworkHalf.assert_called_once()
            mock_post_fetch.assert_called_once()
            self.assertEqual(self.errors, [])

    def test_skips_when_fresh(self):
        """Test it skips fetch when repo project is fresh."""
        self.manifest.repoProject.LastFetch = time.time()

        with mock.patch.object(sync, "_PostRepoFetch") as mock_post_fetch:
            self.cmd._UpdateRepoProject(self.opt, self.manifest, self.errors)
            self.manifest.repoProject.Sync_NetworkHalf.assert_not_called()
            mock_post_fetch.assert_not_called()

    def test_skips_local_only(self):
        """Test it does nothing with --local-only."""
        self.opt.local_only = True
        self.manifest.repoProject.LastFetch = time.time() - (
            sync._ONE_DAY_S + 1
        )

        with mock.patch.object(sync, "_PostRepoFetch") as mock_post_fetch:
            self.cmd._UpdateRepoProject(self.opt, self.manifest, self.errors)
            self.manifest.repoProject.Sync_NetworkHalf.assert_not_called()
            mock_post_fetch.assert_not_called()

    def test_post_repo_fetch_skipped_on_env_var(self):
        """Test _PostRepoFetch is skipped when REPO_SKIP_SELF_UPDATE is set."""
        self.manifest.repoProject.LastFetch = time.time()

        with mock.patch.dict(os.environ, {"REPO_SKIP_SELF_UPDATE": "1"}):
            with mock.patch.object(sync, "_PostRepoFetch") as mock_post_fetch:
                self.cmd._UpdateRepoProject(
                    self.opt, self.manifest, self.errors
                )
                mock_post_fetch.assert_not_called()

    def test_fetch_failure_is_handled(self):
        """Test that a fetch failure is recorded and doesn't crash."""
        self.manifest.repoProject.LastFetch = time.time() - (
            sync._ONE_DAY_S + 1
        )
        fetch_error = GitError("Fetch failed")
        self.manifest.repoProject.Sync_NetworkHalf.return_value = (
            SyncNetworkHalfResult(False, fetch_error)
        )

        with mock.patch.object(sync, "_PostRepoFetch") as mock_post_fetch:
            self.cmd._UpdateRepoProject(self.opt, self.manifest, self.errors)
            self.manifest.repoProject.Sync_NetworkHalf.assert_called_once()
            mock_post_fetch.assert_not_called()
            self.assertEqual(self.errors, [fetch_error])


class InterleavedSyncTest(unittest.TestCase):
    """Tests for interleaved sync."""

    def setUp(self):
        """Set up a sync command with mocks."""
        self.repodir = tempfile.mkdtemp(".repo")
        self.manifest = mock.MagicMock(repodir=self.repodir)
        self.manifest.repoProject.LastFetch = time.time()
        self.manifest.repoProject.worktree = self.repodir
        self.manifest.manifestProject.worktree = self.repodir
        self.manifest.IsArchive = False
        self.manifest.CloneBundle = False
        self.manifest.default.sync_j = 1

        self.outer_client = mock.MagicMock()
        self.outer_client.manifest.IsArchive = False
        self.cmd = sync.Sync(
            manifest=self.manifest, outer_client=self.outer_client
        )
        self.cmd.outer_manifest = self.manifest

        # Mock projects.
        self.projA = FakeProject("projA", objdir="objA")
        self.projB = FakeProject("projB", objdir="objB")
        self.projA_sub = FakeProject(
            "projA/sub", name="projA_sub", objdir="objA_sub"
        )
        self.projC = FakeProject("projC", objdir="objC")

        # Mock methods that are not part of the core interleaved sync logic.
        mock.patch.object(self.cmd, "_UpdateAllManifestProjects").start()
        mock.patch.object(self.cmd, "_UpdateProjectsRevisionId").start()
        mock.patch.object(self.cmd, "_ValidateOptionsWithManifest").start()
        mock.patch.object(sync, "_PostRepoUpgrade").start()
        mock.patch.object(sync, "_PostRepoFetch").start()

        # Mock parallel context for worker tests.
        self.parallel_context_patcher = mock.patch(
            "subcmds.sync.Sync.get_parallel_context"
        )
        self.mock_get_parallel_context = self.parallel_context_patcher.start()
        self.sync_dict = {}
        self.mock_context = {
            "projects": [],
            "sync_dict": self.sync_dict,
        }
        self.mock_get_parallel_context.return_value = self.mock_context

        # Mock _GetCurrentBranchOnly for worker tests.
        mock.patch.object(sync.Sync, "_GetCurrentBranchOnly").start()

    def tearDown(self):
        """Clean up resources."""
        shutil.rmtree(self.repodir)
        mock.patch.stopall()

    def test_interleaved_fail_fast(self):
        """Test that --fail-fast is respected in interleaved mode."""
        opt, args = self.cmd.OptionParser.parse_args(
            ["--interleaved", "--fail-fast", "-j2"]
        )
        opt.quiet = True

        # With projA/sub, _SafeCheckoutOrder creates two batches:
        # 1. [projA, projB]
        # 2. [projA/sub]
        # We want to fail on the first batch and ensure the second isn't run.
        all_projects = [self.projA, self.projB, self.projA_sub]
        mock.patch.object(
            self.cmd, "GetProjects", return_value=all_projects
        ).start()

        # Mock ExecuteInParallel to simulate a failed run on the first batch of
        # projects.
        execute_mock = mock.patch.object(
            self.cmd, "ExecuteInParallel", return_value=False
        ).start()

        with self.assertRaises(sync.SyncFailFastError):
            self.cmd._SyncInterleaved(
                opt,
                args,
                [],
                self.manifest,
                self.manifest.manifestProject,
                all_projects,
                {},
            )

        execute_mock.assert_called_once()

    def test_interleaved_shared_objdir_serial(self):
        """Test that projects with shared objdir are processed serially."""
        opt, args = self.cmd.OptionParser.parse_args(["--interleaved", "-j4"])
        opt.quiet = True

        # Setup projects with a shared objdir.
        self.projA.objdir = "common_objdir"
        self.projC.objdir = "common_objdir"

        all_projects = [self.projA, self.projB, self.projC]
        mock.patch.object(
            self.cmd, "GetProjects", return_value=all_projects
        ).start()

        def execute_side_effect(jobs, target, work_items, **kwargs):
            # The callback is a partial object. The first arg is the set we
            # need to update to avoid the stall detection.
            synced_relpaths_set = kwargs["callback"].args[0]
            projects_in_pass = self.cmd.get_parallel_context()["projects"]
            for item in work_items:
                for project_idx in item:
                    synced_relpaths_set.add(
                        projects_in_pass[project_idx].relpath
                    )
            return True

        execute_mock = mock.patch.object(
            self.cmd, "ExecuteInParallel", side_effect=execute_side_effect
        ).start()

        self.cmd._SyncInterleaved(
            opt,
            args,
            [],
            self.manifest,
            self.manifest.manifestProject,
            all_projects,
            {},
        )

        execute_mock.assert_called_once()
        jobs_arg, _, work_items = execute_mock.call_args.args
        self.assertEqual(jobs_arg, 2)
        work_items_sets = {frozenset(item) for item in work_items}
        expected_sets = {frozenset([0, 2]), frozenset([1])}
        self.assertEqual(work_items_sets, expected_sets)

    def _get_opts(self, args=None):
        """Helper to get default options for worker tests."""
        if args is None:
            args = ["--interleaved"]
        opt, _ = self.cmd.OptionParser.parse_args(args)
        # Set defaults for options used by the worker.
        opt.quiet = True
        opt.verbose = False
        opt.force_sync = False
        opt.clone_bundle = False
        opt.tags = False
        opt.optimized_fetch = False
        opt.retry_fetches = 0
        opt.prune = False
        opt.detach_head = False
        opt.force_checkout = False
        opt.rebase = False
        return opt

    def test_worker_successful_sync(self):
        """Test _SyncProjectList with a successful fetch and checkout."""
        opt = self._get_opts()
        project = self.projA
        project.Sync_NetworkHalf = mock.Mock(
            return_value=SyncNetworkHalfResult(error=None, remote_fetched=True)
        )
        project.Sync_LocalHalf = mock.Mock()
        project.manifest.manifestProject.config = mock.MagicMock()
        self.mock_context["projects"] = [project]

        with mock.patch("subcmds.sync.SyncBuffer") as mock_sync_buffer:
            mock_sync_buf_instance = mock.MagicMock()
            mock_sync_buf_instance.Finish.return_value = True
            mock_sync_buffer.return_value = mock_sync_buf_instance

            result_obj = self.cmd._SyncProjectList(opt, [0])

            self.assertEqual(len(result_obj.results), 1)
            result = result_obj.results[0]
            self.assertTrue(result.fetch_success)
            self.assertTrue(result.checkout_success)
            self.assertIsNone(result.fetch_error)
            self.assertIsNone(result.checkout_error)
            project.Sync_NetworkHalf.assert_called_once()
            project.Sync_LocalHalf.assert_called_once()

    def test_worker_fetch_fails(self):
        """Test _SyncProjectList with a failed fetch."""
        opt = self._get_opts()
        project = self.projA
        fetch_error = GitError("Fetch failed")
        project.Sync_NetworkHalf = mock.Mock(
            return_value=SyncNetworkHalfResult(
                error=fetch_error, remote_fetched=False
            )
        )
        project.Sync_LocalHalf = mock.Mock()
        self.mock_context["projects"] = [project]

        result_obj = self.cmd._SyncProjectList(opt, [0])
        result = result_obj.results[0]

        self.assertFalse(result.fetch_success)
        self.assertFalse(result.checkout_success)
        self.assertEqual(result.fetch_error, fetch_error)
        self.assertIsNone(result.checkout_error)
        project.Sync_NetworkHalf.assert_called_once()
        project.Sync_LocalHalf.assert_not_called()

    def test_worker_no_worktree(self):
        """Test interleaved sync does not checkout with no worktree."""
        opt = self._get_opts()
        project = self.projA
        project.worktree = None
        project.Sync_NetworkHalf = mock.Mock(
            return_value=SyncNetworkHalfResult(error=None, remote_fetched=True)
        )
        project.Sync_LocalHalf = mock.Mock()
        self.mock_context["projects"] = [project]

        result_obj = self.cmd._SyncProjectList(opt, [0])
        result = result_obj.results[0]

        self.assertTrue(result.fetch_success)
        self.assertTrue(result.checkout_success)
        project.Sync_NetworkHalf.assert_called_once()
        project.Sync_LocalHalf.assert_not_called()

    def test_worker_fetch_fails_exception(self):
        """Test _SyncProjectList with an exception during fetch."""
        opt = self._get_opts()
        project = self.projA
        fetch_error = GitError("Fetch failed")
        project.Sync_NetworkHalf = mock.Mock(side_effect=fetch_error)
        project.Sync_LocalHalf = mock.Mock()
        self.mock_context["projects"] = [project]

        result_obj = self.cmd._SyncProjectList(opt, [0])
        result = result_obj.results[0]

        self.assertFalse(result.fetch_success)
        self.assertFalse(result.checkout_success)
        self.assertEqual(result.fetch_error, fetch_error)
        project.Sync_NetworkHalf.assert_called_once()
        project.Sync_LocalHalf.assert_not_called()

    def test_worker_checkout_fails(self):
        """Test _SyncProjectList with an exception during checkout."""
        opt = self._get_opts()
        project = self.projA
        project.Sync_NetworkHalf = mock.Mock(
            return_value=SyncNetworkHalfResult(error=None, remote_fetched=True)
        )
        checkout_error = GitError("Checkout failed")
        project.Sync_LocalHalf = mock.Mock(side_effect=checkout_error)
        project.manifest.manifestProject.config = mock.MagicMock()
        self.mock_context["projects"] = [project]

        with mock.patch("subcmds.sync.SyncBuffer"):
            result_obj = self.cmd._SyncProjectList(opt, [0])
            result = result_obj.results[0]

            self.assertTrue(result.fetch_success)
            self.assertFalse(result.checkout_success)
            self.assertIsNone(result.fetch_error)
            self.assertEqual(result.checkout_error, checkout_error)
            project.Sync_NetworkHalf.assert_called_once()
            project.Sync_LocalHalf.assert_called_once()

    def test_worker_local_only(self):
        """Test _SyncProjectList with --local-only."""
        opt = self._get_opts(["--interleaved", "--local-only"])
        project = self.projA
        project.Sync_NetworkHalf = mock.Mock()
        project.Sync_LocalHalf = mock.Mock()
        project.manifest.manifestProject.config = mock.MagicMock()
        self.mock_context["projects"] = [project]

        with mock.patch("subcmds.sync.SyncBuffer") as mock_sync_buffer:
            mock_sync_buf_instance = mock.MagicMock()
            mock_sync_buf_instance.Finish.return_value = True
            mock_sync_buffer.return_value = mock_sync_buf_instance

            result_obj = self.cmd._SyncProjectList(opt, [0])
            result = result_obj.results[0]

            self.assertTrue(result.fetch_success)
            self.assertTrue(result.checkout_success)
            project.Sync_NetworkHalf.assert_not_called()
            project.Sync_LocalHalf.assert_called_once()

    def test_worker_network_only(self):
        """Test _SyncProjectList with --network-only."""
        opt = self._get_opts(["--interleaved", "--network-only"])
        project = self.projA
        project.Sync_NetworkHalf = mock.Mock(
            return_value=SyncNetworkHalfResult(error=None, remote_fetched=True)
        )
        project.Sync_LocalHalf = mock.Mock()
        self.mock_context["projects"] = [project]

        result_obj = self.cmd._SyncProjectList(opt, [0])
        result = result_obj.results[0]

        self.assertTrue(result.fetch_success)
        self.assertTrue(result.checkout_success)
        project.Sync_NetworkHalf.assert_called_once()
        project.Sync_LocalHalf.assert_not_called()
