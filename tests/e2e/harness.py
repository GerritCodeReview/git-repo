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

"""Hermetic end-to-end test harness for repo.

`ServerRepo` manages bare repositories with helpers to create commits
(including gitlinks for superprojects), branches, tags & bundles without
needing a worktree.
"""

import functools
import os
from pathlib import Path
import subprocess
from typing import Dict, Mapping, NamedTuple, Optional, Tuple, Union


# Every repo/git subprocess gets this timeout so a hang can't wedge the CQ.
COMMAND_TIMEOUT = 300

# Fixed identity used for all commits created by the harness (not by
# the simulated user).
HARNESS_IDENTITY = {
    "GIT_AUTHOR_NAME": "E2E Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "E2E Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.com",
}

# Settings applied to every server repo to mimic Gerrit/GoB behavior.
SERVER_REPO_CONFIG = {
    "uploadpack.allowFilter": "true",
    "uploadpack.allowReachableSHA1InWant": "true",
    "http.receivepack": "false",
}


def clean_environ() -> Dict[str, str]:
    """Return a copy of os.environ without settings that leak into tests.

    Use a denylist rather than an allowlist so OS and toolchain variables
    required by git/python subprocesses (e.g. PATH, TMPDIR, VIRTUAL_ENV, and
    Windows vars like SYSTEMROOT needed for Winsock) pass through across
    platforms and CI environments.

    Note: `HOME` is already isolated by `session_tmp_home_dir` &
    `tmp_home_dir` in `tests/conftest.py`.
    """
    env = {}
    for key, value in os.environ.items():
        if key.startswith(("GIT_", "REPO_")):
            continue
        if key.lower() in (
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "xdg_config_home",
            # curl reads .curlrc/.netrc from these (repo uses curl for bundles).
            "curl_home",
            "netrc",
            # Fallbacks used by git when the config has no identity/locale.
            "email",
            "language",
            # The launcher prepends to PYTHONPATH rather than replacing it.
            "pythonpath",
            # These add warnings to stderr, which tests often check is empty.
            "pythondevmode",
            "pythonwarnings",
            # LUCI's git wrapper replaces HOME with this.
            "infra_git_wrapper_home",
        ):
            continue
        env[key] = value
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Never launch an interactive editor (git & repo both honor this).
    env["GIT_EDITOR"] = ":"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # Tests match on English git & repo output.
    env["LC_ALL"] = "C"
    return env


def run_git(
    *args: str,
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Mapping[str, str]] = None,
    stdin: Optional[bytes] = None,
) -> str:
    """Run git and return its stripped stdout, raising on failure."""
    if env is None:
        env = dict(clean_environ(), **HARNESS_IDENTITY)
    proc = subprocess.run(
        ["git"] + list(args),
        # Python <3.8 on Windows rejects Path objects for cwd.
        # https://github.com/python/cpython/issues/85919
        cwd=None if cwd is None else str(cwd),
        env=env,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=COMMAND_TIMEOUT,
    )
    if proc.returncode:
        raise AssertionError(
            f"git {' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stderr.decode('utf-8', 'replace')}"
        )
    return proc.stdout.decode("utf-8").rstrip("\r\n")


@functools.lru_cache(maxsize=None)
def git_version() -> Tuple[int, ...]:
    """Return the local git version as a tuple of ints."""
    ver = run_git("--version").split()[2].split("-")[0]
    return tuple(int(x) if x.isdigit() else 0 for x in ver.split(".")[:3])


def _quote_config(value: str) -> str:
    """Quote `value` for use as a git config subsection name or value."""
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    )
    return f'"{escaped}"'


def write_config(path: Path, settings: Mapping[str, str]) -> None:
    """Append `settings` (e.g. {"section.key": "value"}) to a git config file.

    This writes the file directly to avoid spawning `git config` per setting.
    Subsections are supported (e.g. "url.<base>.insteadOf").
    """
    with path.open("a", encoding="utf-8") as fp:
        for key, value in settings.items():
            section, _, rest = key.partition(".")
            subsection, _, name = rest.rpartition(".")
            if subsection:
                section = f"{section} {_quote_config(subsection)}"
            fp.write(f"[{section}]\n\t{name} = {_quote_config(value)}\n")


class Gitlink(NamedTuple):
    """A gitlink (submodule/superproject) tree entry pointing at a commit."""

    commit: str


class Blob(NamedTuple):
    """File content with an explicit tree entry mode."""

    data: bytes
    mode: str = "100644"


# Content for ServerRepo.commit: file contents (str/bytes/Blob), a gitlink, or
# None to delete the path.
FileContent = Optional[Union[str, bytes, Blob, Gitlink]]


class ServerRepo:
    """A bare repository."""

    # Fake commit timestamp; see commit().
    _clock = 1700000000

    def __init__(
        self, path: Path, url: str, default_branch: str = "main"
    ) -> None:
        self.path = path
        self.url = url
        self.default_branch = default_branch

    @classmethod
    def create(
        cls, path: Path, url: str, default_branch: str = "main"
    ) -> "ServerRepo":
        """Create a new (empty) bare repository."""
        path.parent.mkdir(parents=True, exist_ok=True)
        run_git(
            "-c",
            "init.defaultObjectFormat=sha1",
            "init",
            "--quiet",
            "--bare",
            f"--initial-branch={default_branch}",
            str(path),
        )
        write_config(path / "config", SERVER_REPO_CONFIG)
        return cls(path, url, default_branch=default_branch)

    def git(self, *args: str, stdin: Optional[bytes] = None) -> str:
        """Run git against this repository."""
        return run_git(f"--git-dir={self.path}", *args, stdin=stdin)

    def rev_parse(self, rev: str) -> str:
        """Resolve `rev` to a commit id (peeling tags)."""
        return self.git("rev-parse", "--verify", "--quiet", f"{rev}^{{}}")

    def has_ref(self, ref: str) -> bool:
        try:
            self.git("rev-parse", "--verify", "--quiet", ref)
            return True
        except AssertionError:
            return False

    def commit(
        self,
        files: Mapping[str, FileContent],
        branch: Optional[str] = None,
        message: str = "commit",
    ) -> str:
        """Create a commit on `branch` and return its id.

        This uses `git fast-import` so all objects land in a single pack.

        Args:
            files: Map of path to new content.  Paths not listed are carried
                over from the parent commit (the tip of `branch`, if it
                exists).  Use None to delete a path and Gitlink to add a
                gitlink entry.
            branch: Branch to create/advance; defaults to `default_branch`.
            message: The commit message.
        """
        if branch is None:
            branch = self.default_branch
        ref = f"refs/heads/{branch}"
        parent = self.rev_parse(ref) if self.has_ref(ref) else None

        # Use a monotonic fake clock so commits are strictly ordered even
        # when created within the same second.
        ServerRepo._clock += 1
        stamp = f"{ServerRepo._clock} +0000"
        msg = message.encode("utf-8") + b"\n"
        stream = [
            f"commit {ref}\n".encode(),
            f"author {HARNESS_IDENTITY['GIT_AUTHOR_NAME']} "
            f"<{HARNESS_IDENTITY['GIT_AUTHOR_EMAIL']}> {stamp}\n".encode(),
            f"committer {HARNESS_IDENTITY['GIT_COMMITTER_NAME']} "
            f"<{HARNESS_IDENTITY['GIT_COMMITTER_EMAIL']}> {stamp}\n".encode(),
            f"data {len(msg)}\n".encode(),
            msg,
        ]
        if parent:
            stream.append(f"from {parent}\n".encode())
        # fast-import applies file commands in order, so emit deletions first
        # or e.g. {"foo/bar": "x", "foo": None} would delete the new foo/bar.
        for name, content in sorted(
            files.items(), key=lambda item: item[1] is not None
        ):
            if content is None:
                stream.append(f"D {name}\n".encode())
            elif isinstance(content, Gitlink):
                stream.append(f"M 160000 {content.commit} {name}\n".encode())
            else:
                if isinstance(content, str):
                    content = content.encode("utf-8")
                if isinstance(content, bytes):
                    content = Blob(content)
                stream += [
                    f"M {content.mode} inline {name}\n".encode(),
                    f"data {len(content.data)}\n".encode(),
                    content.data,
                    b"\n",
                ]
        stream.append(b"done\n")
        self.git(
            "fast-import",
            "--quiet",
            "--force",
            "--done",
            stdin=b"".join(stream),
        )
        return self.rev_parse(ref)

    def set_ref(self, ref: str, rev: str) -> None:
        """Point `ref` at `rev`."""
        self.git("update-ref", ref, rev)

    def tag(self, name: str, rev: str = "HEAD") -> None:
        """Create an annotated tag."""
        self.git("tag", "-a", "-m", name, name, rev)

    def write_bundle(self) -> Path:
        """Write a clone.bundle (all branches & tags) in the repo."""
        bundle = self.path / "clone.bundle"
        self.git("bundle", "create", str(bundle), "--branches", "--tags")
        return bundle
