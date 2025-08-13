# Copyright (C) 2025 The Android Open Source Project
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

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from command import UsageError
from subcmds.wipe import Wipe


class WipeUnitTest(unittest.TestCase):
    """Test the wipe subcommand."""

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="repo_wipe_test_")
        self.addCleanup(shutil.rmtree, self.tempdir)

    def _create_mock_project(self, name, objdir_path=None, has_changes=False):
        """Creates a mock project with necessary attributes and directories."""
        proj = MagicMock()
        proj.name = name
        proj.relpath = name
        proj.HasChanges = MagicMock(return_value=has_changes)
        proj.worktree = os.path.join(self.tempdir, name)
        proj.gitdir = os.path.join(
            self.tempdir, ".repo/projects", name + ".git"
        )
        if objdir_path:
            proj.objdir = objdir_path
        else:
            proj.objdir = os.path.join(
                self.tempdir, ".repo/project-objects", name + ".git"
            )

        os.makedirs(proj.worktree, exist_ok=True)
        os.makedirs(proj.gitdir, exist_ok=True)
        os.makedirs(proj.objdir, exist_ok=True)
        return proj

    def _run_wipe(self, all_projects, projects_to_wipe_names, options=None):
        """Helper to run the Wipe command with mocked projects."""
        cmd = Wipe()

        def get_projects_mock(projects, all_manifests=False):
            if projects is None:
                return all_projects
            names_to_find = set(projects)
            return [p for p in all_projects if p.name in names_to_find]

        cmd.GetProjects = MagicMock(side_effect=get_projects_mock)

        if options is None:
            options = []

        # The first element of the tuple returned by parse_args is the options object
        opts = cmd.OptionParser.parse_args(options + projects_to_wipe_names)[0]
        cmd.Execute(opts, projects_to_wipe_names)

    def test_wipe_single_unshared_project(self):
        """Test wiping a single project that is not shared."""
        p1 = self._create_mock_project("project/one")
        self._run_wipe([p1], ["project/one"])

        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p1.objdir))

    def test_wipe_multiple_unshared_projects(self):
        """Test wiping multiple projects that are not shared."""
        p1 = self._create_mock_project("project/one")
        p2 = self._create_mock_project("project/two")
        self._run_wipe([p1, p2], ["project/one", "project/two"])

        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p1.objdir))
        self.assertFalse(os.path.exists(p2.worktree))
        self.assertFalse(os.path.exists(p2.gitdir))
        self.assertFalse(os.path.exists(p2.objdir))

    def test_wipe_shared_project_no_force_raises_error(self):
        """Test that wiping a shared project without --force raises an error."""
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self._create_mock_project("project/one", objdir_path=shared_objdir)
        p2 = self._create_mock_project("project/two", objdir_path=shared_objdir)

        with self.assertRaises(UsageError) as e:
            self._run_wipe([p1, p2], ["project/one"])

        self.assertIn("shared object directories", str(e.exception))
        self.assertIn("project/one", str(e.exception))
        self.assertIn("project/two", str(e.exception))

        self.assertTrue(os.path.exists(p1.worktree))
        self.assertTrue(os.path.exists(p1.gitdir))
        self.assertTrue(os.path.exists(p2.worktree))
        self.assertTrue(os.path.exists(p2.gitdir))
        self.assertTrue(os.path.exists(shared_objdir))

    def test_wipe_shared_project_with_force(self):
        """Test wiping a shared project with --force."""
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self._create_mock_project("project/one", objdir_path=shared_objdir)
        p2 = self._create_mock_project("project/two", objdir_path=shared_objdir)

        self._run_wipe([p1, p2], ["project/one"], options=["--force"])

        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertTrue(os.path.exists(shared_objdir))
        self.assertTrue(os.path.exists(p2.worktree))
        self.assertTrue(os.path.exists(p2.gitdir))

    def test_wipe_all_sharing_projects(self):
        """Test wiping all projects that share an object directory."""
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self._create_mock_project("project/one", objdir_path=shared_objdir)
        p2 = self._create_mock_project("project/two", objdir_path=shared_objdir)

        self._run_wipe([p1, p2], ["project/one", "project/two"])

        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p2.worktree))
        self.assertFalse(os.path.exists(p2.gitdir))
        self.assertFalse(os.path.exists(shared_objdir))

    def test_wipe_with_uncommitted_changes_raises_error(self):
        """Test wiping a project with uncommitted changes raises an error."""
        p1 = self._create_mock_project("project/one", has_changes=True)

        with self.assertRaises(UsageError) as e:
            self._run_wipe([p1], ["project/one"])

        self.assertIn("uncommitted changes", str(e.exception))
        self.assertIn("project/one", str(e.exception))

        self.assertTrue(os.path.exists(p1.worktree))
        self.assertTrue(os.path.exists(p1.gitdir))
        self.assertTrue(os.path.exists(p1.objdir))

    def test_wipe_with_uncommitted_changes_with_force(self):
        """Test wiping a project with uncommitted changes with --force."""
        p1 = self._create_mock_project("project/one", has_changes=True)
        self._run_wipe([p1], ["project/one"], options=["--force"])

        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p1.objdir))

    def test_wipe_uncommitted_and_shared_raises_combined_error(self):
        """Test that uncommitted and shared projects raise a combined error."""
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self._create_mock_project(
            "project/one", objdir_path=shared_objdir, has_changes=True
        )
        p2 = self._create_mock_project("project/two", objdir_path=shared_objdir)

        with self.assertRaises(UsageError) as e:
            self._run_wipe([p1, p2], ["project/one"])

        self.assertIn("uncommitted changes", str(e.exception))
        self.assertIn("shared object directories", str(e.exception))
        self.assertIn("project/one", str(e.exception))
        self.assertIn("project/two", str(e.exception))

        self.assertTrue(os.path.exists(p1.worktree))
        self.assertTrue(os.path.exists(p1.gitdir))
        self.assertTrue(os.path.exists(p2.worktree))
        self.assertTrue(os.path.exists(p2.gitdir))
        self.assertTrue(os.path.exists(shared_objdir))


if __name__ == "__main__":
    unittest.main()
