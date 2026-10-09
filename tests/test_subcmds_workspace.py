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

"""Unittests for the subcmds/workspace.py module."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import git_config
import project
from subcmds import workspace
import workspace_ns


def _git(cwd, *args, **kwargs):
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=main"] + list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _userns_available() -> bool:
    if sys.platform != "linux":
        return False
    pid = os.fork()
    if pid == 0:
        try:
            workspace_ns.Libc().unshare(workspace_ns.CLONE_NEWUSER, "probe")
            os._exit(0)
        except Exception:  # noqa: B902
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    return os.WEXITSTATUS(status) == 0


class FakeClient:
    """A repo-ish client: real git repos in the classic .repo/projects layout.

    No manifest machinery; Project objects are constructed directly.
    """

    def __init__(self, tempdir: str):
        self.topdir = os.path.join(tempdir, "client")
        self.repodir = os.path.join(self.topdir, ".repo")
        os.makedirs(self.repodir)
        self.manifest = mock.MagicMock()
        self.manifest.topdir = self.topdir
        self.manifest.default.revisionExpr = "main"
        self.manifest.manifestProject.config = git_config.GitConfig(
            configfile=os.path.join(self.repodir, "config")
        )
        self.manifest.is_multimanifest = False
        self.manifest.IsMirror = False
        self.manifest.IsArchive = False
        self.projects = {}

    def add_project(self, relpath: str):
        name = relpath.replace("/", "_")
        gitdir = os.path.join(self.repodir, "projects", relpath + ".git")
        worktree = os.path.join(self.topdir, relpath)
        os.makedirs(worktree)
        os.makedirs(os.path.dirname(gitdir))
        _git(worktree, "init", "-q", "--separate-git-dir", gitdir)
        # repo's layout: worktree/.git is a symlink to the gitdir.
        dotgit = os.path.join(worktree, ".git")
        os.remove(dotgit)
        os.symlink(os.path.relpath(gitdir, worktree), dotgit)
        _git(worktree, "config", "user.name", "t")
        _git(worktree, "config", "user.email", "t@t")
        with open(os.path.join(worktree, "file.txt"), "w") as f:
            f.write("v1\n")
        _git(worktree, "add", ".")
        _git(worktree, "commit", "-q", "-m", "init")
        _git(worktree, "branch", "-M", "main")
        _git(worktree, "update-ref", "refs/remotes/origin/main", "HEAD")
        _git(worktree, "remote", "add", "origin", "https://example.invalid/r")
        _git(worktree, "checkout", "-q", "--detach")

        remote = mock.MagicMock()
        remote.name = "origin"
        remote.ToLocal = lambda rev: f"refs/remotes/origin/{rev}"
        p = project.Project(
            manifest=self.manifest,
            name=name,
            remote=remote,
            gitdir=gitdir,
            objdir=gitdir,
            worktree=worktree,
            relpath=relpath,
            revisionExpr="main",
            revisionId=None,
        )
        p.GetRemote = lambda name=None: remote
        p.GetRevisionId = lambda all_refs=None: _git(
            worktree, "rev-parse", "refs/remotes/origin/main"
        ).stdout.strip()
        self.projects[relpath] = p
        return p

    def command(self) -> workspace.Workspace:
        cmd = workspace.Workspace(repodir=self.repodir, manifest=self.manifest)

        def get_projects(args, all_manifests=False, **kwargs):
            out = []
            for a in args:
                a = os.path.abspath(a)
                for p in self.projects.values():
                    if a == p.worktree or a.startswith(p.worktree + os.sep):
                        out.append(p)
            return out

        cmd.GetProjects = get_projects
        return cmd

    def run(self, argv, env=None):
        cmd = self.command()
        opt, args = cmd.OptionParser.parse_args(argv)
        cmd.ValidateOptions(opt, args)
        with mock.patch.dict(os.environ, env or {}, clear=False):
            return cmd.Execute(opt, args)


class WorkspaceCreateListRemoveTests(unittest.TestCase):
    """Worktree management without entering the overlay."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.client = FakeClient(self.tempdir.name)
        self.proj = self.client.add_project("packages/projA")
        self.cwd = os.getcwd()
        os.chdir(self.proj.worktree)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tempdir.cleanup()

    def _ws(self, name):
        return os.path.join(self.client.repodir, "workspaces", name)

    def test_create_layout(self):
        rc = self.client.run(["create", "feat", "--no-enter"])
        self.assertEqual(rc, 0)
        ws = self._ws("feat")
        wt = os.path.join(ws, "packages/projA")
        self.assertTrue(os.path.isfile(os.path.join(wt, "file.txt")))
        self.assertTrue(os.path.isfile(os.path.join(ws, "out", ".out-dir")))
        with open(os.path.join(ws, "workspace.json")) as f:
            data = json.load(f)
        self.assertEqual(data["project"], "packages/projA")
        self.assertEqual(data["branch"], "feat")
        # Linked worktree, on the new branch, tracking configured.
        with open(os.path.join(wt, ".git")) as f:
            self.assertTrue(f.read().startswith("gitdir:"))
        self.assertEqual(
            _git(wt, "branch", "--show-current").stdout.strip(), "feat"
        )
        self.assertEqual(
            _git(wt, "config", "branch.feat.merge").stdout.strip(),
            "refs/heads/main",
        )
        # Main checkout untouched.
        self.assertEqual(
            _git(self.proj.worktree, "branch", "--show-current").stdout, ""
        )

    def test_create_duplicate_rejected(self):
        self.client.run(["create", "feat", "--no-enter"])
        with self.assertRaises(workspace.WorkspaceError):
            self.client.run(["create", "feat", "--no-enter"])

    def test_create_bad_names(self):
        for bad in ("a/b", "..", ".hidden", "bad name"):
            with self.assertRaises(workspace.WorkspaceError):
                self.client.run(["create", bad, "--no-enter"])

    def test_create_inside_workspace_rejected(self):
        with self.assertRaises(workspace.WorkspaceError):
            self.client.run(
                ["create", "feat", "--no-enter"], env={"REPO_WORKSPACE": "x"}
            )

    def test_create_with_existing_branch(self):
        _git(self.proj.worktree, "branch", "old", "HEAD")
        rc = self.client.run(["create", "ws", "-b", "old", "--no-enter"])
        self.assertEqual(rc, 0)
        wt = os.path.join(self._ws("ws"), "packages/projA")
        self.assertEqual(
            _git(wt, "branch", "--show-current").stdout.strip(), "old"
        )

    def test_remove_clean(self):
        self.client.run(["create", "feat", "--no-enter"])
        rc = self.client.run(["remove", "feat"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self._ws("feat")))
        branches = _git(self.proj.worktree, "branch", "--list").stdout
        self.assertNotIn("feat", branches)

    def test_remove_dirty_needs_force(self):
        self.client.run(["create", "feat", "--no-enter"])
        wt = os.path.join(self._ws("feat"), "packages/projA")
        with open(os.path.join(wt, "file.txt"), "a") as f:
            f.write("more\n")
        _git(wt, "commit", "-q", "-am", "local")
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            self.assertEqual(self.client.run(["remove", "feat"]), 1)
        self.assertTrue(os.path.exists(self._ws("feat")))
        self.assertEqual(self.client.run(["remove", "feat", "--force"]), 0)
        self.assertFalse(os.path.exists(self._ws("feat")))

    def test_remove_active_rejected(self):
        self.client.run(["create", "feat", "--no-enter"])
        with self.assertRaises(workspace.WorkspaceError):
            self.client.run(["remove", "feat"], env={"REPO_WORKSPACE": "feat"})

    def test_list(self):
        self.client.run(["create", "a", "--no-enter"])
        self.client.run(["create", "b", "--no-enter"])
        with mock.patch("sys.stdout") as out:
            self.client.run(["list"], env={"REPO_WORKSPACE": "b"})
        text = "".join(c.args[0] for c in out.write.call_args_list)
        self.assertIn("a", text)
        self.assertIn("* b", text)

    def test_clean_removes_empty(self):
        self.client.run(["create", "empty", "--no-enter"])
        self.client.run(["create", "busy", "--no-enter"])
        wt = os.path.join(self._ws("busy"), "packages/projA")
        with open(os.path.join(wt, "file.txt"), "a") as f:
            f.write("more\n")
        rc = self.client.run(["clean", "-y"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self._ws("empty")))
        self.assertTrue(os.path.exists(self._ws("busy")))

    def test_project_is_linked_worktree(self):
        self.assertFalse(self.proj.IsLinkedWorktree)
        self.client.run(["create", "feat", "--no-enter"])
        wt = os.path.join(self._ws("feat"), "packages/projA")
        linked = project.Project(
            manifest=self.client.manifest,
            name=self.proj.name,
            remote=self.proj.remote,
            gitdir=self.proj.gitdir,
            objdir=self.proj.objdir,
            worktree=wt,
            relpath=self.proj.relpath,
            revisionExpr="main",
            revisionId=None,
        )
        self.assertTrue(linked.IsLinkedWorktree)
        # Even after loading the shared refs, HEAD comes from the worktree.
        linked.bare_ref.all  # noqa: B018
        self.assertEqual(linked.CurrentBranch, "feat")


@unittest.skipUnless(_userns_available(), "unprivileged userns unavailable")
class WorkspaceOverlayTests(unittest.TestCase):
    """`run` inside the real overlay."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.client = FakeClient(self.tempdir.name)
        self.proj = self.client.add_project("packages/projA")
        self.cwd = os.getcwd()
        os.chdir(self.proj.worktree)
        self.client.run(["create", "feat", "--no-enter"])

    def tearDown(self):
        os.chdir(self.cwd)
        self.tempdir.cleanup()

    def _run(self, script, env=None):
        return self.client.run(
            ["run", "feat", "--", "sh", "-c", script], env=env
        )

    def test_overlay_paths(self):
        top = self.client.topdir
        script = (
            f'test "$(git branch --show-current)" = feat && '
            f'test "$REPO_WORKSPACE" = feat && '
            f'test "$REPO_WORKSPACE_PROJECT" = packages/projA && '
            f"test -e {top}/out/.out-dir && "
            f"touch {top}/out/built && "
            f"echo v2 > {top}/packages/projA/file.txt"
        )
        self.assertEqual(self._run(script), 0)
        # Host sees none of it.
        self.assertFalse(os.path.exists(os.path.join(top, "out", "built")))
        with open(os.path.join(self.proj.worktree, "file.txt")) as f:
            self.assertEqual(f.read(), "v1\n")
        # The workspace does.
        ws = os.path.join(self.client.repodir, "workspaces", "feat")
        self.assertTrue(os.path.exists(os.path.join(ws, "out", "built")))
        with open(os.path.join(ws, "packages/projA/file.txt")) as f:
            self.assertEqual(f.read(), "v2\n")

    def test_exit_status(self):
        self.assertEqual(self._run("exit 3"), 3)

    def test_nested_rejected(self):
        with self.assertRaises(workspace.WorkspaceError):
            self._run("true", env={"REPO_WORKSPACE": "feat"})

    def test_preserve_runtime_off(self):
        cfg = self.client.manifest.manifestProject.config
        cfg.SetString("repo.workspace.preserveRuntime", "false")
        self.assertEqual(self._run("test -d /run"), 0)
