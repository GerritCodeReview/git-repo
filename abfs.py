"""
abfs.py - Interface for the abfs binary.
"""

import json
import logging
import os
import subprocess
import urllib
from typing import Any, Dict, List, Optional, Union

NO_ABFS_ENV = "NO_ABFS_REPO"

# Try to use the project's logger if available, otherwise fallback to standard logging.
try:
    from repo_logging import RepoLogger
    logger = RepoLogger(__file__)
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("abfs")


class AbfsError(Exception):
    """Raised when an abfs command fails."""

    def __init__(self, cmd: List[str], returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.message = (
            f"Command '{' '.join(cmd)}' failed with return code {returncode}.\n"
            f"STDERR: {stderr.strip()}"
        )
        super().__init__(self.message)


class AbfsFlags:
    """Helper class to build flags for abfs commands.

    Usage:
        flags = AbfsFlags().add("--verbose").add("--output", "file.txt")
        abfs.run(["cmd"], flags=flags)
    """

    def __init__(self):
        self._flags: List[str] = []

    def add(self, flag: str, value: Optional[Any] = None) -> "AbfsFlags":
        """Add a flag, optionally with a value.

        Args:
            flag: The flag name (e.g. "--foo").
            value: Optional value for the flag. If provided, it is appended
                   as a separate argument (e.g. ["--foo", "value"]).
        """
        self._flags.append(flag)
        if value is not None:
            self._flags.append(str(value))
        return self

    def add_if(self, condition: bool, flag: str, value: Optional[Any] = None) -> "AbfsFlags":
        """Add a flag only if the condition is True."""
        if condition:
            self.add(flag, value)
        return self

    def build(self) -> List[str]:
        """Return the list of flags."""
        return self._flags


class Abfs:
    """Interface to the abfs binary."""

    def __init__(self, topdir: str, binary: str = "abfs"):
        """
        Args:
            binary: Path or name of the abfs binary. Defaults to 'abfs'.
        """
        self.binary = binary
        self.topdir = topdir
        self._load_args()
        self.instance = self.abfs_args.get("ABFS_INSTANCE")

    def _load_args(self):
        self.abfs_args = {}
        path = os.path.join(self.topdir, ".repo", "repo", "abfs_args.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.abfs_args = json.load(f)
            except Exception as e:
                logger.warning("Failed to load %s: %s", path, e)

    def run(
        self,
        args: List[str],
        flags: Optional[Union[AbfsFlags, List[str]]] = None,
        check: bool = True,
        input_data: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        stream_output: bool = False,
    ) -> subprocess.CompletedProcess:
        """
        Run the abfs binary with the given arguments and flags.

        Args:
            args: List of positional arguments (e.g. subcommands, paths).
            flags: An AbfsFlags object or a list of flag strings.
            check: Whether to raise AbfsError on non-zero exit code.
            input_data: String data to pass to stdin.
            env: Extra environment variables to pass to the process.
            cwd: The working directory to run the command in.

        Returns:
            subprocess.CompletedProcess object containing stdout, stderr, etc.

        Raises:
            AbfsError: If check is True and the process exits with non-zero code.
        """
        cmd = [self.binary]
        if self.instance:
            cmd.extend(["-i", self.instance])

        cmd.extend(args)

        if flags:
            if isinstance(flags, AbfsFlags):
                cmd.extend(flags.build())
            else:
                cmd.extend(flags)

        try:
            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            if stream_output:
                result = subprocess.run(
                    cmd,
                    input=input_data,
                    capture_output=False,
                    check=False,
                    env=full_env,
                    cwd=cwd,
                )
                if check and result.returncode != 0:
                    raise AbfsError(cmd, result.returncode, "", "")
                return result
            else:
                result = subprocess.run(
                    cmd,
                    input=input_data,
                    capture_output=True,
                    text=True,
                    check=False,  # We handle checking manually to wrap the error
                    env=full_env,
                    cwd=cwd,
                )
        except FileNotFoundError:
            logger.Error("Failed command: %s", " ".join(cmd))
            logger.error("Binary '%s' not found in PATH.", self.binary)
            raise AbfsError(cmd, -1, "", f"Binary '{self.binary}' not found.")
        except Exception as e:
            logger.Error("Failed command: %s", " ".join(cmd))
            logger.error("Unexpected error running abfs: %s", e)
            raise AbfsError(cmd, -1, "", str(e))

        if check and result.returncode != 0:
            logger.error("abfs command failed: %s", result.stderr.strip())
            raise AbfsError(cmd, result.returncode, result.stdout, result.stderr)

        return result

    def createProject(self, project):
        flags = AbfsFlags()
        flags.add("--repo")
        if project.revisionId:
            flags.add("--commit", project.revisionId)
        elif project.revisionExpr:
            flags.add("--branch", project.revisionExpr)
        flags.add("--origin", project.remote.name)

        env = {
            "GIT_DIR": project.gitdir,
            "GIT_OBJECT_DIRECTORY": os.path.join(project.objdir, "objects"),
        }
        result = self.run([
            "git",
            "clone",
            project.remote.url,
            project.relpath,
        ], flags=flags, env=env)
        return result.stdout.strip()

    def checkout(self, project):
        flags = AbfsFlags()
        result = self.run(
            ["git", "checkout", project.revisionExpr],
            cwd=project.worktree,
            flags=flags,
        )
        return result.stdout.strip()

    def _get_version(self) -> str:
        try:
            result = self.run(["--version"], check=False, stream_output=False)
            return result.stdout.strip()
        except Exception:
            return ""

    def repo_sync(self, args: List[str], opt: Any):
        version_str = self._get_version()
        prefix = version_str.split('-')[0]
        try:
            version_tuple = tuple(int(x) for x in prefix.split('.'))
        except ValueError:
            version_tuple = (0, 0, 0)

        if version_tuple > (0, 1, 14):
            import sys
            try:
                sync_idx = sys.argv.index('sync')
                args_to_pass = sys.argv[sync_idx + 1:]
            except ValueError:
                args_to_pass = sys.argv[2:]

            self.run(
                ["repo", "sync"] + args_to_pass,
                stream_output=True,
            )
            return ""

        flags = AbfsFlags()
        if getattr(opt, 'jobs', None):
            flags.add("--jobs", opt.jobs)

        self.run(
            ["repo", "sync"] + args,
            flags=flags,
            stream_output=True,
        )
        return ""

