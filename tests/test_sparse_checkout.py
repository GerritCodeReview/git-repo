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

"""Test sparse-checkout functionality."""

import contextlib
import os
import shutil
import subprocess
import tempfile
import unittest

import git_command
import git_config
import project


@contextlib.contextmanager
def TempGitTree():
    """Create a new empty git checkout for testing."""
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git", "init"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init.
            templatedir = tempfile.mkdtemp(prefix=".test-template")
            with open(os.path.join(templatedir, "HEAD"), "w") as fp:
                fp.write("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        subprocess.check_call(cmd, cwd=tempdir)
        yield tempdir


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


class SparseCheckoutTests(unittest.TestCase):
    """Check sparse-checkout handling."""

    def test_configure_sparse_checkout_with_string(self):
        """Test configuring sparse-checkout with comma-separated string."""
        with TempGitTree() as tempdir:
            fakeproj = FakeProject(tempdir)

            # Skip if git version is too old
            if not git_command.git_require((2, 25, 0)):
                self.skipTest("Git 2.25.0+ required for sparse-checkout")

            # Configure sparse-checkout with string
            sparse_paths = "src/main,src/tests,docs"
            fakeproj._ConfigureSparseCheckout = (
                project.Project._ConfigureSparseCheckout.__get__(
                    fakeproj, FakeProject
                )
            )
            fakeproj._ConfigureSparseCheckout(sparse_paths)

            # Verify sparse-checkout was initialized
            result = fakeproj.work_git.sparse_checkout("list")
            paths = result.strip().split("\n")
            self.assertIn("src/main", paths)
            self.assertIn("src/tests", paths)
            self.assertIn("docs", paths)

    def test_configure_sparse_checkout_with_list(self):
        """Test configuring sparse-checkout with list of paths."""
        with TempGitTree() as tempdir:
            fakeproj = FakeProject(tempdir)

            # Skip if git version is too old
            if not git_command.git_require((2, 25, 0)):
                self.skipTest("Git 2.25.0+ required for sparse-checkout")

            # Configure sparse-checkout with list
            sparse_paths = ["src/backend", "src/shared"]
            fakeproj._ConfigureSparseCheckout = (
                project.Project._ConfigureSparseCheckout.__get__(
                    fakeproj, FakeProject
                )
            )
            fakeproj._ConfigureSparseCheckout(sparse_paths)

            # Verify sparse-checkout was initialized
            result = fakeproj.work_git.sparse_checkout("list")
            paths = result.strip().split("\n")
            self.assertIn("src/backend", paths)
            self.assertIn("src/shared", paths)

    def test_configure_sparse_checkout_empty(self):
        """Test that empty sparse paths are handled gracefully."""
        with TempGitTree() as tempdir:
            fakeproj = FakeProject(tempdir)

            fakeproj._ConfigureSparseCheckout = (
                project.Project._ConfigureSparseCheckout.__get__(
                    fakeproj, FakeProject
                )
            )
            # Should not raise an error
            fakeproj._ConfigureSparseCheckout(None)
            fakeproj._ConfigureSparseCheckout("")
            fakeproj._ConfigureSparseCheckout([])


class SparseCheckoutExistingRepoTest(unittest.TestCase):
    """Test that sparse-checkout works on repositories that already have a full clone."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempdir = tempfile.mkdtemp(prefix="repo-sparse-test-")

        # Create a test git repository with multiple directories
        self.upstream_repo = os.path.join(self.tempdir, "upstream.git")
        os.makedirs(self.upstream_repo)

        # Initialize bare upstream repo
        subprocess.check_call(
            ["git", "init", "--bare", self.upstream_repo],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Create a temporary clone to populate the upstream
        temp_clone = os.path.join(self.tempdir, "temp_clone")
        subprocess.check_call(
            ["git", "clone", self.upstream_repo, temp_clone],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Create directory structure with files
        os.makedirs(os.path.join(temp_clone, "src/main"))
        os.makedirs(os.path.join(temp_clone, "src/tests"))
        os.makedirs(os.path.join(temp_clone, "docs"))
        os.makedirs(os.path.join(temp_clone, "build"))

        # Create files in each directory
        with open(os.path.join(temp_clone, "README.md"), "w") as f:
            f.write("# Test Repository\n")

        with open(os.path.join(temp_clone, "src/main/app.py"), "w") as f:
            f.write("print('Hello from main')\n")

        with open(os.path.join(temp_clone, "src/tests/test_app.py"), "w") as f:
            f.write("def test_app(): pass\n")

        with open(os.path.join(temp_clone, "docs/guide.md"), "w") as f:
            f.write("# User Guide\n")

        with open(os.path.join(temp_clone, "build/Makefile"), "w") as f:
            f.write("all:\n\techo 'Building...'\n")

        # Commit all files
        subprocess.check_call(
            ["git", "-C", temp_clone, "add", "."],
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "-C", temp_clone, "commit", "-m", "Initial commit"],
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "-C", temp_clone, "push", "origin", "master"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Clean up temp clone
        shutil.rmtree(temp_clone)

        # Create the "existing" full clone that we'll test with
        self.existing_clone = os.path.join(self.tempdir, "existing_clone")
        subprocess.check_call(
            ["git", "clone", self.upstream_repo, self.existing_clone],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir)

    def test_sparse_checkout_on_existing_full_clone(self):
        """Test applying sparse-checkout to an existing repository with full clone."""
        # Skip if git version is too old
        if not git_command.git_require((2, 25, 0)):
            self.skipTest("Git 2.25.0+ required for sparse-checkout")

        # Verify we have a full clone initially
        self.assertTrue(os.path.exists(os.path.join(self.existing_clone, "src/main/app.py")))
        self.assertTrue(os.path.exists(os.path.join(self.existing_clone, "src/tests/test_app.py")))
        self.assertTrue(os.path.exists(os.path.join(self.existing_clone, "docs/guide.md")))
        self.assertTrue(os.path.exists(os.path.join(self.existing_clone, "build/Makefile")))

        # Create a FakeProject to test sparse checkout configuration
        class FakeProject:
            def __init__(self, worktree):
                self.worktree = worktree
                self.gitdir = os.path.join(worktree, ".git")
                self.name = "test-project"
                self.work_git = project.Project._GitGetByExec(
                    self, bare=False, gitdir=self.gitdir
                )

        fake_proj = FakeProject(self.existing_clone)
        fake_proj._ConfigureSparseCheckout = (
            project.Project._ConfigureSparseCheckout.__get__(
                fake_proj, FakeProject
            )
        )

        # Apply sparse-checkout to only include src/main and docs
        sparse_paths = ["src/main", "docs"]
        fake_proj._ConfigureSparseCheckout(sparse_paths)

        # Verify sparse-checkout is configured
        result = fake_proj.work_git.sparse_checkout("list")
        paths = result.strip().split("\n")
        self.assertIn("src/main", paths)
        self.assertIn("docs", paths)

        # Now update the working tree to reflect sparse-checkout
        # This simulates what would happen during a sync
        subprocess.check_call(
            ["git", "-C", self.existing_clone, "read-tree", "-mu", "HEAD"],
            stdout=subprocess.DEVNULL,
        )

        # Verify that only the sparse paths are checked out
        self.assertTrue(os.path.exists(os.path.join(self.existing_clone, "src/main/app.py")),
                       "src/main/app.py should exist (in sparse paths)")
        self.assertTrue(os.path.exists(os.path.join(self.existing_clone, "docs/guide.md")),
                       "docs/guide.md should exist (in sparse paths)")

        # These should not exist in the working tree (but still in git history)
        self.assertFalse(os.path.exists(os.path.join(self.existing_clone, "src/tests/test_app.py")),
                        "src/tests/test_app.py should not exist (not in sparse paths)")
        self.assertFalse(os.path.exists(os.path.join(self.existing_clone, "build/Makefile")),
                        "build/Makefile should not exist (not in sparse paths)")

        # Verify files still exist in git (can be retrieved)
        result = subprocess.check_output(
            ["git", "-C", self.existing_clone, "ls-tree", "-r", "--name-only", "HEAD"],
            text=True,
        )
        all_files = result.strip().split("\n")
        self.assertIn("src/tests/test_app.py", all_files,
                     "src/tests/test_app.py should still be in git history")
        self.assertIn("build/Makefile", all_files,
                     "build/Makefile should still be in git history")

    def test_sparse_checkout_with_updates(self):
        """Test that sparse-checkout only fetches updates for configured paths."""
        # Skip if git version is too old
        if not git_command.git_require((2, 25, 0)):
            self.skipTest("Git 2.25.0+ required for sparse-checkout")

        # Set up sparse-checkout on existing clone
        class FakeProject:
            def __init__(self, worktree):
                self.worktree = worktree
                self.gitdir = os.path.join(worktree, ".git")
                self.name = "test-project"
                self.work_git = project.Project._GitGetByExec(
                    self, bare=False, gitdir=self.gitdir
                )

        fake_proj = FakeProject(self.existing_clone)
        fake_proj._ConfigureSparseCheckout = (
            project.Project._ConfigureSparseCheckout.__get__(
                fake_proj, FakeProject
            )
        )

        # Configure sparse-checkout for only src/main
        fake_proj._ConfigureSparseCheckout(["src/main"])
        subprocess.check_call(
            ["git", "-C", self.existing_clone, "read-tree", "-mu", "HEAD"],
            stdout=subprocess.DEVNULL,
        )

        # Create a new commit in upstream that modifies files in both sparse and non-sparse paths
        temp_clone = os.path.join(self.tempdir, "temp_clone2")
        subprocess.check_call(
            ["git", "clone", self.upstream_repo, temp_clone],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Modify file in sparse path
        with open(os.path.join(temp_clone, "src/main/app.py"), "a") as f:
            f.write("# Updated in sparse path\n")

        # Modify file in non-sparse path
        with open(os.path.join(temp_clone, "build/Makefile"), "a") as f:
            f.write("# Updated in non-sparse path\n")

        subprocess.check_call(
            ["git", "-C", temp_clone, "add", "."],
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "-C", temp_clone, "commit", "-m", "Update files"],
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "-C", temp_clone, "push", "origin", "master"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(temp_clone)

        # Fetch and merge updates in existing clone
        subprocess.check_call(
            ["git", "-C", self.existing_clone, "fetch", "origin"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "-C", self.existing_clone, "merge", "origin/master"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Verify the sparse path file was updated
        with open(os.path.join(self.existing_clone, "src/main/app.py")) as f:
            content = f.read()
            self.assertIn("Updated in sparse path", content,
                         "File in sparse path should be updated")

        # Verify the non-sparse path file is still not in working tree
        self.assertFalse(os.path.exists(os.path.join(self.existing_clone, "build/Makefile")),
                        "File in non-sparse path should not be checked out")

        # But verify it's in git history with the update
        result = subprocess.check_output(
            ["git", "-C", self.existing_clone, "show", "HEAD:build/Makefile"],
            text=True,
        )
        self.assertIn("Updated in non-sparse path", result,
                     "File in non-sparse path should be updated in git history")


if __name__ == "__main__":
    unittest.main()
