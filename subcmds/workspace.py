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

from __future__ import annotations

import json
import os
import sys
import time
from typing import List, Optional

from command import Command
from error import RepoExitError
from git_command import git
from git_command import git_require
from git_command import GitCommand
from git_config import IsImmutable
from git_refs import R_HEADS
import platform_utils
from repo_logging import RepoLogger
import workspace_ns


logger = RepoLogger(__file__)

ENV_NAME = "REPO_WORKSPACE"
ENV_PROJECT = "REPO_WORKSPACE_PROJECT"
ENV_DIR = "REPO_WORKSPACE_DIR"
STATE_FILE = "workspace.json"
OUT_MARKER = ".out-dir"
WORKSPACES_DIR = "workspaces"


class WorkspaceError(RepoExitError):
    """Exit error for failed workspace command."""


class Workspace(Command):
    COMMON = True
    helpSummary = "Manage parallel checkouts of a project at its normal path"
    helpUsage = """
%prog create <name> [-b <branch>] [-r <rev>] [<project>]
%prog enter <name>
%prog run <name> -- <command>...
%prog list [--size]
%prog remove <name> [--force]
%prog clean [<name>] [--all] [--days <n>] [-y]
%prog status
"""
    helpDescription = """
A workspace is a second, independent checkout of one project that appears at
the project's normal path, with its own out/ directory, inside a private
shell.  Builds in a workspace are incremental and do not disturb the main
checkout or other workspaces.

'%prog create' makes a linked git worktree under .repo/workspaces/<name>/ on
a new branch (default: the manifest revision, like 'repo start') and enters
it.  '%prog enter' starts $SHELL with the worktree bind-mounted over the
project directory and .repo/workspaces/<name>/out bind-mounted over out/.
Type 'exit' to return.  '%prog run' executes a single command the same way.

Inside a workspace, $REPO_WORKSPACE holds the workspace name and
$REPO_WORKSPACE_PROJECT the project path.  A prompt hint for bash:

  PS1='${REPO_WORKSPACE:+[$REPO_WORKSPACE] }'"$PS1"

The overlay uses Linux user and mount namespaces and needs no privileges or
extra tools, but requires unprivileged user namespaces to be enabled.

Configuration (git config, e.g. in .repo/manifests.git/config):

  repo.workspace.preserveRuntime  keep user-owned entries and sockets of
                                  /run visible on a private /run (default
                                  true; needed by credential helpers that
                                  check directory ownership)
  repo.workspace.bind             extra host path(s) under /run to keep
  repo.workspace.cleanDays        idle threshold for 'clean' (default 7)
"""

    def _Options(self, p):
        p.add_option(
            "-b",
            "--branch",
            help="branch name (default: the workspace name)",
        )
        p.add_option(
            "-r",
            "--rev",
            "--revision",
            dest="revision",
            help="start the branch at this revision instead of the "
            "manifest revision",
        )
        p.add_option(
            "--head",
            "--HEAD",
            dest="revision",
            action="store_const",
            const="HEAD",
            help="abbreviation for --rev HEAD (start from the main "
            "checkout's current commit)",
        )
        p.add_option(
            "--no-enter",
            dest="enter",
            action="store_false",
            default=True,
            help="create the workspace without entering it",
        )
        p.add_option(
            "--no-overlay",
            dest="overlay",
            action="store_false",
            default=True,
            help="create the worktree only; print its path instead of "
            "entering a shell",
        )
        p.add_option(
            "--size",
            action="store_true",
            help="include disk usage in 'list'",
        )
        p.add_option(
            "-f",
            "--force",
            action="store_true",
            help="remove even if the workspace has local changes or "
            "unmerged commits",
        )
        p.add_option(
            "--all",
            action="store_true",
            help="'clean': wipe build output of every workspace",
        )
        p.add_option(
            "--days",
            type="float",
            help="'clean': idle threshold in days",
        )
        p.add_option(
            "-y",
            "--yes",
            action="store_true",
            help="answer yes to confirmations",
        )

    # Helpers.

    @property
    def _ws_root(self) -> str:
        return os.path.join(self.repodir, WORKSPACES_DIR)

    def _ws_dir(self, name: str) -> str:
        return os.path.join(self._ws_root, name)

    def _config(self):
        return self.manifest.manifestProject.config

    def _Load(self, name: str) -> dict:
        path = os.path.join(self._ws_dir(name), STATE_FILE)
        try:
            with open(path) as f:
                data = json.load(f)
        except OSError:
            raise WorkspaceError(f"workspace '{name}' does not exist")
        data["name"] = name
        return data

    def _Save(self, name: str, data: dict) -> None:
        path = os.path.join(self._ws_dir(name), STATE_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)

    def _AllNames(self) -> List[str]:
        try:
            names = platform_utils.listdir(self._ws_root)
        except OSError:
            return []
        return sorted(
            n
            for n in names
            if os.path.isfile(os.path.join(self._ws_root, n, STATE_FILE))
        )

    def _ProjectFor(self, data: dict):
        path = os.path.join(self.manifest.topdir, data["project"])
        projects = self.GetProjects([path], all_manifests=False)
        if not projects:
            raise WorkspaceError(
                f"project '{data['project']}' for workspace "
                f"'{data['name']}' is no longer in the manifest"
            )
        return projects[0]

    def _ProjectFromArg(self, arg: Optional[str]):
        projects = self.GetProjects([arg or "."], all_manifests=False)
        if len(projects) != 1:
            raise WorkspaceError(
                "specify exactly one project (run inside it or name it)"
            )
        return projects[0]

    def _WorktreePath(self, name: str, relpath: str) -> str:
        return os.path.join(self._ws_dir(name), relpath)

    def _OutPath(self, name: str) -> str:
        return os.path.join(self._ws_dir(name), "out")

    def _Active(self) -> Optional[str]:
        return os.environ.get(ENV_NAME)

    def _Confirm(self, prompt: str, opt) -> bool:
        if getattr(opt, "yes", False):
            return True
        if not sys.stdin.isatty():
            return False
        try:
            return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    def _Git(self, project, cmdv, cwd=None, check=True) -> GitCommand:
        gc = GitCommand(
            project,
            cmdv,
            cwd=cwd,
            capture_stdout=True,
            capture_stderr=True,
            verify_command=check,
        )
        gc.Wait()
        return gc

    def _IsClean(self, project, wt_path: str) -> bool:
        """True if |wt_path| has no local changes and no unmerged commits."""
        st = self._Git(project, ["status", "--porcelain"], cwd=wt_path)
        if st.stdout.strip():
            return False
        try:
            base = project.GetRevisionId()
        except Exception:
            return False
        anc = self._Git(
            project,
            ["merge-base", "--is-ancestor", "HEAD", base],
            cwd=wt_path,
            check=False,
        )
        return anc.rc == 0

    # Subcommands.

    def _Create(self, opt, args):
        if len(args) < 1:
            self.Usage()
        name = args[0]
        if self._Active():
            raise WorkspaceError(
                f"already inside workspace '{self._Active()}'; exit first"
            )
        if "/" in name or name in (".", "..") or name.startswith("."):
            raise WorkspaceError(f"'{name}' is not a valid workspace name")
        branch = opt.branch or name
        if not git.check_ref_format("heads/" + branch):
            raise WorkspaceError(f"'{branch}' is not a valid branch name")
        git_require((2, 15, 0), fail=True, msg="git worktree gc corruption")

        project = self._ProjectFromArg(args[1] if len(args) > 1 else None)
        ws_dir = self._ws_dir(name)
        if os.path.exists(ws_dir):
            raise WorkspaceError(f"workspace '{name}' already exists")

        wt_path = self._WorktreePath(name, project.relpath)
        out_path = self._OutPath(name)

        # Resolve the start point and configure tracking like `repo start`.
        branch_merge = project.revisionExpr
        if IsImmutable(project.revisionExpr):
            branch_merge = (
                project.dest_branch or self.manifest.default.revisionExpr
            )
        if opt.revision:
            revid = project.work_git.rev_parse(opt.revision)
        else:
            revid = project.GetRevisionId()

        existing = (R_HEADS + branch) in project.bare_ref.all
        if existing and opt.revision:
            raise WorkspaceError(
                f"branch '{branch}' already exists; drop --rev to use it, "
                "or pick another name with -b"
            )

        os.makedirs(os.path.dirname(wt_path), exist_ok=True)
        self._Git(project, ["worktree", "prune"])
        cmd = ["worktree", "add"]
        if existing:
            cmd += [wt_path, branch]
        else:
            cmd += ["-b", branch, wt_path, revid]
        try:
            self._Git(project, cmd)
        except Exception:
            platform_utils.rmtree(ws_dir, ignore_errors=True)
            raise

        if not existing:
            b = project.GetBranch(branch)
            b.remote = project.GetRemote()
            b.merge = branch_merge
            if not b.merge.startswith("refs/") and not IsImmutable(b.merge):
                b.merge = R_HEADS + b.merge
            b.Save()

        os.makedirs(out_path, exist_ok=True)
        with open(os.path.join(out_path, OUT_MARKER), "w"):
            pass

        now = time.time()
        data = {
            "project": project.relpath,
            "project_name": project.name,
            "branch": branch,
            "created": now,
            "last_entered": None,
        }
        self._Save(name, data)

        if existing:
            logger.warning(
                "warning: branch '%s' already existed and was checked out; "
                "it may be behind the manifest revision",
                branch,
            )
        print(
            f"Created workspace '{name}' for {project.relpath} "
            f"on branch '{branch}'"
        )
        if not opt.enter:
            return 0
        data["name"] = name
        return self._Enter(opt, data, project, argv=None)

    def _Enter(self, opt, data: dict, project, argv: Optional[List[str]]):
        name = data["name"]
        if self._Active():
            raise WorkspaceError(
                f"already inside workspace '{self._Active()}'; exit first"
            )
        wt_path = self._WorktreePath(name, project.relpath)
        out_path = self._OutPath(name)
        if not os.path.isdir(wt_path):
            raise WorkspaceError(
                f"worktree for '{name}' is missing at {wt_path}"
            )
        if not os.path.isdir(project.worktree):
            raise WorkspaceError(
                f"project path {project.worktree} is missing; "
                "run `repo sync`"
            )

        if not opt.overlay:
            print(wt_path)
            return 0

        ok, why = workspace_ns.is_supported()
        if not ok:
            raise WorkspaceError(
                f"cannot enter workspace: {why}\n"
                f"The worktree is at {wt_path} (use --no-overlay to print it)."
            )

        env = dict(os.environ)
        binds = []

        # Clients using --use-local-gitdirs keep .git inside the project, so
        # the overlay would hide it.  Expose it at a side path and point git
        # at it explicitly.
        if project.gitdir.startswith(project.worktree.rstrip("/") + "/"):
            side = os.path.join(self._ws_dir(name), ".gitdir")
            os.makedirs(side, exist_ok=True)
            binds.append((project.gitdir, side))
            dotgit = os.path.join(wt_path, ".git")
            with open(dotgit) as f:
                per_wt = f.read().split(":", 1)[1].strip()
            per_wt = os.path.normpath(os.path.join(wt_path, per_wt))
            rel = os.path.relpath(per_wt, project.gitdir)
            env["GIT_DIR"] = os.path.join(side, rel)
            env["GIT_COMMON_DIR"] = side

        binds.append((wt_path, project.worktree))

        host_out = os.path.join(self.manifest.topdir, "out")
        os.makedirs(host_out, exist_ok=True)
        os.makedirs(out_path, exist_ok=True)
        binds.append((out_path, host_out))

        cfg = self._config()
        preserve = cfg.GetBoolean("repo.workspace.preserveRuntime")
        if preserve is None:
            preserve = True
        extra = cfg.GetString("repo.workspace.bind", all_keys=True) or []

        env[ENV_NAME] = name
        env[ENV_PROJECT] = project.relpath
        env[ENV_DIR] = self._ws_dir(name)

        if argv is None:
            shell = os.environ.get("SHELL") or "/bin/sh"
            argv = [shell]
            print(f"Entering workspace '{name}' (type 'exit' to leave)")

        data["last_entered"] = time.time()
        self._Save(name, {k: v for k, v in data.items() if k != "name"})

        overlay = workspace_ns.Overlay(
            binds, preserve_runtime=preserve, extra_runtime_binds=extra
        )
        return workspace_ns.run_in_overlay(overlay, argv, env, cwd=os.getcwd())

    def _EnterCmd(self, opt, args):
        if len(args) != 1:
            self.Usage()
        data = self._Load(args[0])
        return self._Enter(opt, data, self._ProjectFor(data), argv=None)

    def _Run(self, opt, args):
        if len(args) < 2:
            self.Usage()
        data = self._Load(args[0])
        return self._Enter(
            opt, data, self._ProjectFor(data), argv=list(args[1:])
        )

    def _List(self, opt, args):
        names = self._AllNames()
        if not names:
            print("No workspaces.")
            return 0
        active = self._Active()
        rows = []
        for name in names:
            data = self._Load(name)
            wt = self._WorktreePath(name, data["project"])
            note = ""
            if not os.path.isdir(wt):
                note = "worktree missing"
            elif not os.path.isdir(
                os.path.join(self.manifest.topdir, data["project"])
            ):
                note = "project path missing (manifest changed?)"
            size = ""
            if opt.size:
                total = _DirSize(wt) + _DirSize(self._OutPath(name))
                size = f"{total / 2**30:.1f}G"
            rows.append(
                (
                    "*" if name == active else "",
                    name,
                    data["project"],
                    data.get("branch", ""),
                    size,
                    note,
                )
            )
        widths = [max(len(r[i]) for r in rows) for i in range(4)]
        for r in rows:
            line = (
                f"{r[0]:<1} {r[1]:<{widths[1]}}  {r[2]:<{widths[2]}}  "
                f"{r[3]:<{widths[3]}}"
            )
            if opt.size:
                line += f"  {r[4]:>7}"
            if r[5]:
                line += f"  ({r[5]})"
            print(line.rstrip())
        return 0

    def _Remove(self, opt, args, name=None, quiet=False):
        if name is None:
            if len(args) != 1:
                self.Usage()
            name = args[0]
        data = self._Load(name)
        if self._Active() == name:
            raise WorkspaceError("cannot remove the active workspace")
        project = self._ProjectFor(data)
        wt_path = self._WorktreePath(name, data["project"])
        branch = data.get("branch")

        force = bool(opt.force)
        if os.path.isdir(wt_path) and not force:
            if not self._IsClean(project, wt_path):
                print(
                    f"Workspace '{name}' has local changes or commits not "
                    f"in {project.revisionExpr}."
                )
                if not self._Confirm(
                    f"Remove it and force-delete branch '{branch}'?", opt
                ):
                    print("Aborted.")
                    return 1
                force = True

        if os.path.isdir(wt_path):
            self._Git(
                project, ["worktree", "remove", "--force", wt_path], check=False
            )
        self._Git(project, ["worktree", "prune"], check=False)

        if branch and branch != project.CurrentBranch:
            res = self._Git(
                project,
                ["branch", "-D" if force else "-d", branch],
                check=False,
            )
            if res.rc != 0 and not quiet:
                logger.warning(
                    "warning: branch '%s' not deleted: %s",
                    branch,
                    (res.stderr or "").strip(),
                )
        platform_utils.rmtree(self._ws_dir(name), ignore_errors=True)
        if not quiet:
            print(f"Removed workspace '{name}'.")
        return 0

    def _Clean(self, opt, args):
        days = opt.days
        if days is None:
            days = self._config().GetInt("repo.workspace.cleanDays")
        if days is None:
            days = 7
        cutoff = time.time() - days * 86400
        names = [args[0]] if args else self._AllNames()
        active = self._Active()

        wiped = 0
        empty = []
        for name in names:
            data = self._Load(name)
            out_path = self._OutPath(name)
            if os.path.isdir(out_path):
                idle = _LastActivity(out_path) < cutoff
                if args or opt.all or idle:
                    size = _DirSize(out_path)
                    if size:
                        print(
                            f"{name}: wiping build output ({size / 2**30:.1f}G)"
                        )
                        platform_utils.rmtree(out_path, ignore_errors=True)
                        os.makedirs(out_path, exist_ok=True)
                        with open(os.path.join(out_path, OUT_MARKER), "w"):
                            pass
                        wiped += size
            if args or name == active:
                continue
            wt_path = self._WorktreePath(name, data["project"])
            try:
                project = self._ProjectFor(data)
            except WorkspaceError:
                continue
            if os.path.isdir(wt_path) and self._IsClean(project, wt_path):
                empty.append(name)

        if wiped:
            print(f"Freed {wiped / 2**30:.1f}G of build output.")
        if empty:
            print("Workspaces with no local changes or commits:")
            for name in empty:
                print(f"  {name}")
            if self._Confirm("Remove them?", opt):
                for name in empty:
                    self._Remove(opt, [], name=name, quiet=True)
                print(f"Removed {len(empty)} workspace(s).")
        return 0

    def _Status(self, opt, args):
        name = self._Active()
        if not name:
            print("Not inside a workspace.")
            return 0
        print(f"workspace: {name}")
        print(f"project:   {os.environ.get(ENV_PROJECT, '')}")
        print(f"state:     {os.environ.get(ENV_DIR, '')}")
        return 0

    def ValidateOptions(self, opt, args):
        if not args:
            self.Usage()
        verbs = {
            "create": self._Create,
            "enter": self._EnterCmd,
            "run": self._Run,
            "list": self._List,
            "remove": self._Remove,
            "rm": self._Remove,
            "clean": self._Clean,
            "status": self._Status,
        }
        if args[0] not in verbs:
            self.OptionParser.error(f"unknown subcommand '{args[0]}'")
        self._verb = verbs[args[0]]

    def Execute(self, opt, args):
        return self._verb(opt, args[1:]) or 0


def _DirSize(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            if not os.path.islink(os.path.join(root, f)):
                total += st.st_size
    return total


def _LastActivity(out_path: str) -> float:
    """Best-effort 'last build' time for an out/ directory."""
    newest = 0.0
    for name in (
        ".ninja_log",
        ".ninja_deps",
        "build.ninja",
        "soong.log",
        ".soong.environment.used",
    ):
        for base in (out_path, os.path.join(out_path, "soong")):
            try:
                newest = max(newest, os.stat(os.path.join(base, name)).st_mtime)
            except OSError:
                pass
    if newest:
        return newest
    try:
        newest = os.stat(out_path).st_mtime
    except OSError:
        return 0.0
    for root, dirs, files in os.walk(out_path):
        if root[len(out_path) :].count(os.sep) >= 2:
            dirs[:] = []
        for f in files:
            try:
                newest = max(newest, os.stat(os.path.join(root, f)).st_mtime)
            except OSError:
                pass
    return newest
