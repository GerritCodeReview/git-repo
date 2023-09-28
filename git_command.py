# Copyright (C) 2008 The Android Open Source Project
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

import functools
import json
import os
import re
import subprocess
import sys
from typing import Any, Optional

from error import GitError
from error import RepoExitError
from git_refs import HEAD
from git_trace2_event_log_base import BaseEventLog
import platform_utils
from repo_logging import RepoLogger
from repo_trace import IsTrace
from repo_trace import REPO_TRACE
from repo_trace import Trace
from wrapper import Wrapper


GIT = "git"
# NB: These do not need to be kept in sync with the repo launcher script.
# These may be much newer as it allows the repo launcher to roll between
# different repo releases while source versions might require a newer git.
#
# The soft version is when we start warning users that the version is old and
# we'll be dropping support for it.  We'll refuse to work with versions older
# than the hard version.
#
# git-1.7 is in (EOL) Ubuntu Precise.  git-1.9 is in Ubuntu Trusty.
MIN_GIT_VERSION_SOFT = (1, 9, 1)
MIN_GIT_VERSION_HARD = (1, 7, 2)
GIT_DIR = "GIT_DIR"

LAST_GITDIR = None
LAST_CWD = None
DEFAULT_GIT_FAIL_MESSAGE = "git command failure"
ERROR_EVENT_LOGGING_PREFIX = "RepoGitCommandError"
# Common line length limit
GIT_ERROR_STDOUT_LINES = 1
GIT_ERROR_STDERR_LINES = 1
INVALID_GIT_EXIT_CODE = 126

logger = RepoLogger(__file__)


class _GitCall(object):
    @functools.lru_cache(maxsize=None)
    def version_tuple(self):
        ret = Wrapper().ParseGitVersion()
        if ret is None:
            msg = "fatal: unable to detect git version"
            logger.error(msg)
            raise GitRequireError(msg)
        return ret

    def __getattr__(self, name):
        name = name.replace("_", "-")

        def fun(*cmdv):
            command = [name]
            command.extend(cmdv)
            return GitCommand(None, command, add_event_log=False).Wait() == 0

        return fun


git = _GitCall()


def RepoSourceVersion():
    """Return the version of the repo.git tree."""
    ver = getattr(RepoSourceVersion, "version", None)

    # We avoid GitCommand so we don't run into circular deps -- GitCommand needs
    # to initialize version info we provide.
    if ver is None:
        env = GitCommand._GetBasicEnv()

        proj = os.path.dirname(os.path.abspath(__file__))
        env[GIT_DIR] = os.path.join(proj, ".git")
        result = subprocess.run(
            [GIT, "describe", HEAD],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            env=env,
            check=False,
        )
        if result.returncode == 0:
            ver = result.stdout.strip()
            if ver.startswith("v"):
                ver = ver[1:]
        else:
            ver = "unknown"
        setattr(RepoSourceVersion, "version", ver)

    return ver


@functools.lru_cache(maxsize=None)
def GetEventTargetPath():
    """Get the 'trace2.eventtarget' path from git configuration.

    Returns:
        path: git config's 'trace2.eventtarget' path if it exists, or None
    """
    path = None
    cmd = ["config", "--get", "trace2.eventtarget"]
    # TODO(https://crbug.com/gerrit/13706): Use GitConfig when it supports
    # system git config variables.
    p = GitCommand(
        None,
        cmd,
        capture_stdout=True,
        capture_stderr=True,
        bare=True,
        add_event_log=False,
    )
    retval = p.Wait()
    if retval == 0:
        # Strip trailing carriage-return in path.
        path = p.stdout.rstrip("\n")
    elif retval != 1:
        # `git config --get` is documented to produce an exit status of `1`
        # if the requested variable is not present in the configuration.
        # Report any other return value as an error.
        logger.error(
            "repo: error: 'git config --get' call failed with return code: "
            "%r, stderr: %r",
            retval,
            p.stderr,
        )
    return path


class UserAgent(object):
    """Mange User-Agent settings when talking to external services

    We follow the style as documented here:
    https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent
    """

    _os = None
    _repo_ua = None
    _git_ua = None

    @property
    def os(self):
        """The operating system name."""
        if self._os is None:
            os_name = sys.platform
            if os_name.lower().startswith("linux"):
                os_name = "Linux"
            elif os_name == "win32":
                os_name = "Win32"
            elif os_name == "cygwin":
                os_name = "Cygwin"
            elif os_name == "darwin":
                os_name = "Darwin"
            self._os = os_name

        return self._os

    @property
    def repo(self):
        """The UA when connecting directly from repo."""
        if self._repo_ua is None:
            py_version = sys.version_info
            self._repo_ua = "git-repo/%s (%s) git/%s Python/%d.%d.%d" % (
                RepoSourceVersion(),
                self.os,
                git.version_tuple().full,
                py_version.major,
                py_version.minor,
                py_version.micro,
            )

        return self._repo_ua

    @property
    def git(self):
        """The UA when running git."""
        if self._git_ua is None:
            self._git_ua = "git/%s (%s) git-repo/%s" % (
                git.version_tuple().full,
                self.os,
                RepoSourceVersion(),
            )

        return self._git_ua


user_agent = UserAgent()


def git_require(min_version, fail=False, msg=""):
    git_version = git.version_tuple()
    if min_version <= git_version:
        return True
    if fail:
        need = ".".join(map(str, min_version))
        if msg:
            msg = " for " + msg
        error_msg = "fatal: git %s or later required%s" % (need, msg)
        logger.error(error_msg)
        raise GitRequireError(error_msg)
    return False


def _build_env(
    _kwargs_only=(),
    bare: Optional[bool] = False,
    disable_editor: Optional[bool] = False,
    ssh_proxy: Optional[Any] = None,
    gitdir: Optional[str] = None,
    objdir: Optional[str] = None,
):
    """Constucts an env dict for command execution."""

    assert _kwargs_only == (), "_build_env only accepts keyword arguments."

    env = GitCommand._GetBasicEnv()

    if disable_editor:
        env["GIT_EDITOR"] = ":"
    if ssh_proxy:
        env["REPO_SSH_SOCK"] = ssh_proxy.sock()
        env["GIT_SSH"] = ssh_proxy.proxy
        env["GIT_SSH_VARIANT"] = "ssh"
    if "http_proxy" in env and "darwin" == sys.platform:
        s = "'http.proxy=%s'" % (env["http_proxy"],)
        p = env.get("GIT_CONFIG_PARAMETERS")
        if p is not None:
            s = p + " " + s
        env["GIT_CONFIG_PARAMETERS"] = s
    if "GIT_ALLOW_PROTOCOL" not in env:
        env[
            "GIT_ALLOW_PROTOCOL"
        ] = "file:git:http:https:ssh:persistent-http:persistent-https:sso:rpc"
    env["GIT_HTTP_USER_AGENT"] = user_agent.git

    if objdir:
        # Set to the place we want to save the objects.
        env["GIT_OBJECT_DIRECTORY"] = objdir

        alt_objects = os.path.join(gitdir, "objects") if gitdir else None
        if alt_objects and os.path.realpath(alt_objects) != os.path.realpath(
            objdir
        ):
            # Allow git to search the original place in case of local or unique
            # refs that git will attempt to resolve even if we aren't fetching
            # them.
            env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = alt_objects
    if bare and gitdir is not None:
        env[GIT_DIR] = gitdir

    return env


class GitCommand(object):
    """Wrapper around a single git invocation."""

    def __init__(
        self,
        project,
        cmdv,
        bare=False,
        input=None,
        capture_stdout=True,
        capture_stderr=True,
        merge_output=False,
        disable_editor=False,
        ssh_proxy=None,
        cwd=None,
        gitdir=None,
        objdir=None,
        verify_command=False,
        add_event_log=True,
        log_as_error=True,
    ):
        if project:
            if not cwd:
                cwd = project.worktree
            if not gitdir:
                gitdir = project.gitdir

        self.project = project
        self.cmdv = cmdv
        self.verify_command = verify_command

        # Git on Windows wants its paths only using / for reliability.
        if platform_utils.isWindows():
            if objdir:
                objdir = objdir.replace("\\", "/")
            if gitdir:
                gitdir = gitdir.replace("\\", "/")

        env = _build_env(
            disable_editor=disable_editor,
            ssh_proxy=ssh_proxy,
            objdir=objdir,
            gitdir=gitdir,
            bare=bare,
        )

        command = [GIT]
        if bare:
            cwd = None
        command_name = cmdv[0]
        command.append(command_name)
        # Need to use the --progress flag for fetch/clone so output will be
        # displayed as by default git only does progress output if stderr is a
        # TTY.
        if sys.stderr.isatty() and command_name in ("fetch", "clone"):
            if "--progress" not in cmdv and "--quiet" not in cmdv:
                command.append("--progress")
        command.extend(cmdv[1:])

        stdin = subprocess.PIPE if input else None
        stdout = subprocess.PIPE if capture_stdout else None
        stderr = (
            subprocess.STDOUT
            if merge_output
            else (subprocess.PIPE if capture_stderr else None)
        )

        event_log = (
            BaseEventLog(env=env, add_init_count=True)
            if add_event_log
            else None
        )

        try:
            self._RunCommand(
                command,
                env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                ssh_proxy=ssh_proxy,
                cwd=cwd,
                input=input,
            )
            self.VerifyCommand()
        except GitCommandError as e:
            logger.error(e)
            if event_log is not None:
                error_info = json.dumps(
                    {
                        "ErrorType": type(e).__name__,
                        "Project": e.project,
                        "CommandName": command_name,
                        "Message": str(e),
                        "ReturnCode": str(e.git_rc)
                        if e.git_rc is not None
                        else None,
                        "IsError": log_as_error,
                    }
                )
                event_log.ErrorEvent(
                    f"{ERROR_EVENT_LOGGING_PREFIX}:{error_info}"
                )
                event_log.Write(GetEventTargetPath())
            if isinstance(e, GitPopenCommandError):
                raise

    def _RunCommand(
        self,
        command,
        env,
        stdin=None,
        stdout=None,
        stderr=None,
        ssh_proxy=None,
        cwd=None,
        input=None,
    ):
        dbg = ""
        if IsTrace():
            global LAST_CWD
            global LAST_GITDIR

            if cwd and LAST_CWD != cwd:
                if LAST_GITDIR or LAST_CWD:
                    dbg += "\n"
                dbg += ": cd %s\n" % cwd
                LAST_CWD = cwd

            if GIT_DIR in env and LAST_GITDIR != env[GIT_DIR]:
                if LAST_GITDIR or LAST_CWD:
                    dbg += "\n"
                dbg += ": export GIT_DIR=%s\n" % env[GIT_DIR]
                LAST_GITDIR = env[GIT_DIR]

            if "GIT_OBJECT_DIRECTORY" in env:
                dbg += (
                    ": export GIT_OBJECT_DIRECTORY=%s\n"
                    % env["GIT_OBJECT_DIRECTORY"]
                )
            if "GIT_ALTERNATE_OBJECT_DIRECTORIES" in env:
                dbg += ": export GIT_ALTERNATE_OBJECT_DIRECTORIES=%s\n" % (
                    env["GIT_ALTERNATE_OBJECT_DIRECTORIES"]
                )

            dbg += ": "
            dbg += " ".join(command)
            if stdin == subprocess.PIPE:
                dbg += " 0<|"
            if stdout == subprocess.PIPE:
                dbg += " 1>|"
            if stderr == subprocess.PIPE:
                dbg += " 2>|"
            elif stderr == subprocess.STDOUT:
                dbg += " 2>&1"

        with Trace(
            "git command %s %s with debug: %s", LAST_GITDIR, command, dbg
        ):
            try:
                p = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    encoding="utf-8",
                    errors="backslashreplace",
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                )
            except Exception as e:
                raise GitPopenCommandError(
                    message="%s: %s" % (command[1], e),
                    project=self.project.name if self.project else None,
                    command_args=self.cmdv,
                )

            if ssh_proxy:
                ssh_proxy.add_client(p)

            self.process = p

            try:
                self.stdout, self.stderr = p.communicate(input=input)
            finally:
                if ssh_proxy:
                    ssh_proxy.remove_client(p)
            self.rc = p.wait()

    @staticmethod
    def _GetBasicEnv():
        """Return a basic env for running git under.

        This is guaranteed to be side-effect free.
        """
        env = os.environ.copy()
        for key in (
            REPO_TRACE,
            GIT_DIR,
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_OBJECT_DIRECTORY",
            "GIT_WORK_TREE",
            "GIT_GRAFT_FILE",
            "GIT_INDEX_FILE",
        ):
            env.pop(key, None)
        return env

    def VerifyCommand(self):
        if self.rc == 0:
            return None
        stdout = (
            "\n".join(self.stdout.split("\n")[:GIT_ERROR_STDOUT_LINES])
            if self.stdout
            else None
        )
        stderr = (
            "\n".join(self.stderr.split("\n")[:GIT_ERROR_STDERR_LINES])
            if self.stderr
            else None
        )
        project = self.project.name if self.project else None
        raise GitCommandError(
            project=project,
            command_args=self.cmdv,
            git_rc=self.rc,
            git_stdout=stdout,
            git_stderr=stderr,
        )

    def Wait(self):
        if self.verify_command:
            self.VerifyCommand()
        return self.rc


class GitRequireError(RepoExitError):
    """Error raised when git version is unavailable or invalid."""

    def __init__(self, message, exit_code: int = INVALID_GIT_EXIT_CODE):
        super().__init__(message, exit_code=exit_code)


class GitCommandError(GitError):
    """
    Error raised from a failed git command.
    Note that GitError can refer to any Git related error (e.g. branch not
    specified for project.py 'UploadForReview'), while GitCommandError is
    raised exclusively from non-zero exit codes returned from git commands.
    """

    # Custom suggestions to augment git stderr with.
    error_to_suggestion = {
        re.compile(
            "couldn't find remote ref .*"
        ): "Check if the provided ref exists in the remote.",
        re.compile("unable to access '.*': .*"): (
            "Please make sure you have the correct access rights and the "
            "repository exists."
        ),
        re.compile(
            "'.*' does not appear to be a git repository"
        ): "Are you running this repo command outside of a repo workspace?",
        re.compile(
            "not a git repository: '.*'"
        ): "Are you running this repo command outside of a repo workspace?",
        re.compile("cannot .*: You have unstaged changes."): (
            "You need to commit, stash, or delete these unstaged changes before"
            " re-running the command."
        ),
    }

    def __init__(
        self,
        message: str = DEFAULT_GIT_FAIL_MESSAGE,
        git_rc: int = None,
        git_stdout: str = None,
        git_stderr: str = None,
        **kwargs,
    ):
        super().__init__(
            message,
            **kwargs,
        )
        self.git_rc = git_rc
        self.git_stdout = git_stdout
        self.git_stderr = self.augument_stderr(git_stderr)

    @staticmethod
    def augument_stderr(stderr):
        """Augments the given stderr with helpful suggestions."""
        if not stderr:
            return stderr

        for err, log in GitCommandError.error_to_suggestion.items():
            if err.search(stderr):
                return f"{stderr}\n{log}"

        return stderr

    def __str__(self):
        args = "[]" if not self.command_args else " ".join(self.command_args)
        error_type = type(self).__name__
        string = f"{error_type}: '{args}' on {self.project} failed"

        if self.message != DEFAULT_GIT_FAIL_MESSAGE:
            string += f": {self.message}"

        if self.git_stdout:
            string += f"\nstdout: {self.git_stdout}"

        if self.git_stderr:
            string += f"\nstderr: {self.git_stderr}"

        return string


class GitPopenCommandError(GitError):
    """
    Error raised when subprocess.Popen fails for a GitCommand
    """
