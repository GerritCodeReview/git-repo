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
        # Create a temporary directory for the entire test run
        self.tempdir = tempfile.mkdtemp(prefix="repo_wipe_test_")
        self.addCleanup(shutil.rmtree, self.tempdir)

        # Helper to create mock project objects
        def create_mock_project(name, objdir_path=None, has_changes=False):
            """Creates a mock project with necessary attributes and directories."""
            proj = MagicMock()
            proj.name = name
            proj.relpath = name
            proj.HasChanges = MagicMock(return_value=has_changes)
            # Simulate paths based on the temp directory
            proj.worktree = os.path.join(self.tempdir, name)
            proj.gitdir = os.path.join(
                self.tempdir, ".repo/projects", name + ".git"
            )
            # Allow sharing objdir by specifying a path
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

        self.create_mock_project = create_mock_project

    def test_wipe_single_unshared_project(self):
        """Test wiping a single project that is not shared."""
        p1 = self.create_mock_project("project/one", has_changes=False)

        cmd = Wipe()
        # Simulate repo's project discovery
        cmd.GetAllProjects = MagicMock(return_value=[p1])
        cmd.GetProjects = MagicMock(return_value=[p1])

        cmd.Execute(
            cmd.OptionParser.parse_args(["project/one"])[0], ["project/one"]
        )

        # All directories should be gone
        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p1.objdir))

    def test_wipe_multiple_unshared_projects(self):
        """Test wiping multiple projects that are not shared."""
        p1 = self.create_mock_project("project/one", has_changes=False)
        p2 = self.create_mock_project("project/two", has_changes=False)

        cmd = Wipe()
        cmd.GetAllProjects = MagicMock(return_value=[p1, p2])
        cmd.GetProjects = MagicMock(return_value=[p1, p2])

        cmd.Execute(
            cmd.OptionParser.parse_args(["project/one", "project/two"])[0],
            ["project/one", "project/two"],
        )

        # All directories for both projects should be gone
        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p1.objdir))
        self.assertFalse(os.path.exists(p2.worktree))
        self.assertFalse(os.path.exists(p2.gitdir))
        self.assertFalse(os.path.exists(p2.objdir))

    def test_wipe_shared_project_no_force_raises_error(self):
        """Test that wiping a shared project without --force raises an error."""
        # p1 and p2 share an object directory
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self.create_mock_project(
            "project/one", objdir_path=shared_objdir, has_changes=False
        )
        p2 = self.create_mock_project(
            "project/two", objdir_path=shared_objdir, has_changes=False
        )

        cmd = Wipe()
        cmd.GetAllProjects = MagicMock(return_value=[p1, p2])
        # We are only trying to wipe p1
        cmd.GetProjects = MagicMock(return_value=[p1])

        with self.assertRaises(UsageError):
            cmd.Execute(
                cmd.OptionParser.parse_args(["project/one"])[0], ["project/one"]
            )

        # Nothing should have been deleted
        self.assertTrue(os.path.exists(p1.worktree))
        self.assertTrue(os.path.exists(p1.gitdir))
        self.assertTrue(os.path.exists(p2.worktree))
        self.assertTrue(os.path.exists(p2.gitdir))
        self.assertTrue(os.path.exists(shared_objdir))

    def test_wipe_shared_project_with_force(self):
        """
        Test wiping a shared project with --force.
        It should remove the project but leave the shared object directory.
        """
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self.create_mock_project(
            "project/one", objdir_path=shared_objdir, has_changes=False
        )
        p2 = self.create_mock_project(
            "project/two", objdir_path=shared_objdir, has_changes=False
        )

        cmd = Wipe()
        cmd.GetAllProjects = MagicMock(return_value=[p1, p2])
        cmd.GetProjects = MagicMock(return_value=[p1])

        cmd.Execute(
            cmd.OptionParser.parse_args(["--force", "project/one"])[0],
            ["project/one"],
        )

        # p1's specific dirs are gone
        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))

        # The shared object directory and p2's dirs must remain
        self.assertTrue(os.path.exists(shared_objdir))
        self.assertTrue(os.path.exists(p2.worktree))
        self.assertTrue(os.path.exists(p2.gitdir))

    def test_wipe_all_sharing_projects(self):
        """
        Test wiping all projects that share an object directory.
        This should remove the shared object directory as well.
        """
        shared_objdir = os.path.join(
            self.tempdir, ".repo/project-objects", "shared.git"
        )
        p1 = self.create_mock_project(
            "project/one", objdir_path=shared_objdir, has_changes=False
        )
        p2 = self.create_mock_project(
            "project/two", objdir_path=shared_objdir, has_changes=False
        )

        cmd = Wipe()
        cmd.GetAllProjects = MagicMock(return_value=[p1, p2])
        # Wiping both projects
        cmd.GetProjects = MagicMock(return_value=[p1, p2])

        cmd.Execute(
            cmd.OptionParser.parse_args(["project/one", "project/two"])[0],
            ["project/one", "project/two"],
        )

        # Everything should be gone, including the shared directory
        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p2.worktree))
        self.assertFalse(os.path.exists(p2.gitdir))
        self.assertFalse(os.path.exists(shared_objdir))

    def test_wipe_with_uncommitted_changes_raises_error(self):
        """Test that wiping a project with uncommitted changes raises an error."""
        p1 = self.create_mock_project("project/one", has_changes=True)

        cmd = Wipe()
        cmd.GetAllProjects = MagicMock(return_value=[p1])
        cmd.GetProjects = MagicMock(return_value=[p1])

        with self.assertRaises(UsageError):
            cmd.Execute(
                cmd.OptionParser.parse_args(["project/one"])[0], ["project/one"]
            )

        # Nothing should have been deleted
        self.assertTrue(os.path.exists(p1.worktree))
        self.assertTrue(os.path.exists(p1.gitdir))
        self.assertTrue(os.path.exists(p1.objdir))

    def test_wipe_with_uncommitted_changes_with_force(self):
        """Test wiping a project with uncommitted changes with --force."""
        p1 = self.create_mock_project("project/one", has_changes=True)

        cmd = Wipe()
        cmd.GetAllProjects = MagicMock(return_value=[p1])
        cmd.GetProjects = MagicMock(return_value=[p1])

        cmd.Execute(
            cmd.OptionParser.parse_args(["--force", "project/one"])[0],
            ["project/one"],
        )

        # All directories should be gone
        self.assertFalse(os.path.exists(p1.worktree))
        self.assertFalse(os.path.exists(p1.gitdir))
        self.assertFalse(os.path.exists(p1.objdir))
