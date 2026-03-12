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
from typing import Optional
import unittest
from unittest import mock

import utils_for_test

import error
import git_config
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


class ProjectTests(unittest.TestCase):
    """Check Project behavior."""

    def test_encode_patchset_description(self):
        self.assertEqual(
            project.Project._encode_patchset_description("abcd00!! +"),
            "abcd00%21%21_%2b",
        )

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


class InitWorkTreeReadTreeErrorTest(unittest.TestCase):
    """Check that _InitWorkTree includes stderr in read-tree errors."""

    def _setup_project(self, tempdir):
        """Create a FakeProject with a commit and the attributes needed
        by _InitWorkTree."""
        fakeproj = FakeProject(tempdir)

        readme = os.path.join(tempdir, "readme")
        with open(readme, "w") as f:
            f.write("test")
        fakeproj.work_git.add("readme")
        fakeproj.work_git.commit("-mInit")

        worktree = os.path.join(tempdir, "sub", "worktree")
        fakeproj.worktree = worktree
        fakeproj.objdir = fakeproj.gitdir
        fakeproj.use_git_worktrees = False
        fakeproj.parent = None

        # Add methods that _InitWorkTree calls on self.
        gitdir = fakeproj.gitdir

        def _createDotGit(dg):
            os.makedirs(os.path.dirname(dg), exist_ok=True)
            with open(dg, "w") as f:
                f.write("gitdir: %s\n" % gitdir)

        fakeproj._createDotGit = _createDotGit
        fakeproj.GetRevisionId = lambda *a, **kw: "abc123"
        fakeproj._CopyAndLinkFiles = lambda: None

        return fakeproj

    def test_read_tree_failure_includes_stderr_and_exit_code(self):
        """When read-tree fails, the error should contain the exit code and
        git's stderr output so operators can diagnose the root cause."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        with TempGitTree() as tempdir:
            fakeproj = self._setup_project(tempdir)
            dotgit = os.path.join(fakeproj.worktree, ".git")

            mock_git_cmd = MagicMock()
            mock_git_cmd.Wait.return_value = 128
            mock_git_cmd.rc = 128
            mock_git_cmd.stderr = (
                "error: unable to read tree abc123\n"
                "fatal: failed to unpack tree object abc123\n"
            )

            with patch("project.GitCommand", return_value=mock_git_cmd):
                with self.assertRaises(error.GitError) as ctx:
                    project.Project._InitWorkTree(fakeproj)

                msg = str(ctx.exception)
                self.assertIn("exit code 128", msg)
                self.assertIn("fatal: failed to unpack tree", msg)
                self.assertIn(fakeproj.name, msg)

                # .git should have been cleaned up.
                self.assertFalse(os.path.exists(dotgit))

    def test_read_tree_failure_empty_stderr(self):
        """When read-tree fails with no stderr (e.g. SIGKILL), the error
        should still include the exit code."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        with TempGitTree() as tempdir:
            fakeproj = self._setup_project(tempdir)

            mock_git_cmd = MagicMock()
            mock_git_cmd.Wait.return_value = 137  # SIGKILL
            mock_git_cmd.rc = 137
            mock_git_cmd.stderr = ""

            with patch("project.GitCommand", return_value=mock_git_cmd):
                with self.assertRaises(error.GitError) as ctx:
                    project.Project._InitWorkTree(fakeproj)

                msg = str(ctx.exception)
                self.assertIn("exit code 137", msg)
                self.assertIn(fakeproj.name, msg)

    def test_read_tree_success_no_error(self):
        """When read-tree succeeds, no error should be raised."""
        from unittest.mock import MagicMock
        from unittest.mock import patch

        with TempGitTree() as tempdir:
            fakeproj = self._setup_project(tempdir)

            mock_git_cmd = MagicMock()
            mock_git_cmd.Wait.return_value = 0
            mock_git_cmd.rc = 0
            mock_git_cmd.stderr = ""

            with patch("project.GitCommand", return_value=mock_git_cmd):
                project.Project._InitWorkTree(fakeproj)

                dotgit = os.path.join(fakeproj.worktree, ".git")
                self.assertTrue(os.path.exists(dotgit))


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


class StatelessSyncTests(unittest.TestCase):
    """Tests for stateless sync strategy."""

    def _get_project(self, tempdir):
        manifest = mock.MagicMock()
        manifest.manifestProject.depth = None
        manifest.manifestProject.dissociate = False
        manifest.manifestProject.clone_filter = None
        manifest.is_multimanifest = False
        manifest.manifestProject.config.GetBoolean.return_value = False

        remote = mock.MagicMock()
        remote.name = "origin"
        remote.url = "http://"

        proj = project.Project(
            manifest=manifest,
            name="test-project",
            remote=remote,
            gitdir=os.path.join(tempdir, ".git"),
            objdir=os.path.join(tempdir, ".git"),
            worktree=tempdir,
            relpath="test-project",
            revisionExpr="1234abcd",
            revisionId=None,
            sync_strategy="stateless",
        )
        proj._CheckForImmutableRevision = mock.MagicMock(return_value=False)
        proj._LsRemote = mock.MagicMock(
            return_value="1234abcd\trefs/heads/main\n"
        )
        proj.bare_git = mock.MagicMock()
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

    def _get_project(self, tempdir, depth=None):
        manifest = mock.MagicMock()
        manifest.manifestProject.depth = depth
        manifest.manifestProject.dissociate = False
        manifest.manifestProject.clone_filter = None
        manifest.is_multimanifest = False
        manifest.manifestProject.config.GetBoolean.return_value = False
        manifest.IsMirror = False

        remote = mock.MagicMock()
        remote.name = "origin"
        remote.url = "http://"

        proj = project.Project(
            manifest=manifest,
            name="test-project",
            remote=remote,
            gitdir=os.path.join(tempdir, "gitdir"),
            objdir=os.path.join(tempdir, "objdir"),
            worktree=tempdir,
            relpath="test-project",
            revisionExpr="0123456789abcdef0123456789abcdef01234567",
            revisionId=None,
        )
        proj._CheckForImmutableRevision = mock.MagicMock(return_value=True)
        proj.DeleteWorktree = mock.MagicMock()
        proj._InitGitDir = mock.MagicMock()
        proj._InitRemote = mock.MagicMock()
        proj._InitMRef = mock.MagicMock()
        return proj

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
