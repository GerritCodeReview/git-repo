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
    def __init__(self, relpath):
        self.relpath = relpath

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
