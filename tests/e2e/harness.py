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

The harness has three parts:

* `GitHttpServer`: a local smart HTTP git server built on `git http-backend`.
  It also serves static `clone.bundle` files like Gerrit/GoB do, and can
  simulate outages.
* `ServerRepo`/`GitHost`: bare repositories hosted by the server, with helpers
  to create commits (including gitlinks for superprojects), branches, tags &
  bundles without needing a worktree.
* `RepoClient`: runs a standalone copy of the `repo` launcher as a real
  subprocess, the same way end users do, against the server.

The code under test (current checkout including uncommitted changes) is
published on the server as the `git-repo` project by `publish_repo_source`, so
`repo init` installs it into `.repo/repo/` over HTTP.
"""

import contextlib
import functools
import http.server
import os
from pathlib import Path
import re
import shutil
import socketserver
import stat
import subprocess
import sys
import threading
import time
from typing import (
    Dict,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Union,
)
import urllib.parse


ROOT_DIR = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT_DIR / "repo"

# The developer's environment, captured at import (i.e. collection) time before
# `tests/conftest.py` isolates HOME for the test session.
HOST_ENVIRON = dict(os.environ)

# Every repo/git subprocess gets this timeout so a hang can't wedge the CQ.
COMMAND_TIMEOUT = 300

# Name of the branch used for the published repo source.
REPO_SOURCE_BRANCH = "main"

# The manifest repo lives two levels deep (like AOSP's platform/manifest) so
# the common `fetch=".."` resolves to the root of the host namespace.
MANIFEST_REPO = "platform/manifest"

# The git endpoints (relative to a repo URL) that clients request.
REPO_ENDPOINTS = (
    "info/refs",
    "git-upload-pack",
    "git-receive-pack",
    "clone.bundle",
)

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

# Client git defaults that tests can emulate.
# Git 3.0 changes several defaults; these let us test them on older git.
# https://git-scm.com/docs/BreakingChanges
GIT_DEFAULTS: Dict[str, Dict[str, str]] = {
    # Git 2 defaults.
    "git2": {
        "init.defaultBranch": "master",
        "init.defaultObjectFormat": "sha1",
        "init.defaultRefFormat": "files",
        "init.defaultRefStorageFormat": "files",
        "safe.bareRepository": "all",
    },
    # Git 3 defaults, except for SHA-256.
    "git3": {
        "init.defaultBranch": "main",
        # TODO(b/483758905): Switch to sha256 (the Git 3 default) once remotes
        # migrate to sha256.
        "init.defaultObjectFormat": "sha1",
        # init.defaultRefFormat is the deprecated name for
        # init.defaultRefStorageFormat; set both to support old & new git.
        "init.defaultRefFormat": "reftable",
        "init.defaultRefStorageFormat": "reftable",
        "safe.bareRepository": "explicit",
    },
}

GIT_DEFAULTS_PARAMS = list(GIT_DEFAULTS)


def clean_environ() -> Dict[str, str]:
    """Return a copy of os.environ without settings that leak into tests.

    Use a denylist rather than an allowlist so OS and toolchain variables
    required by git/python subprocesses (e.g. PATH, TMPDIR, VIRTUAL_ENV, and
    Windows vars like SYSTEMROOT needed for Winsock) pass through across
    platforms and CI environments.

    Note: `HOME` is already isolated by `session_tmp_home_dir` &
    `tmp_home_dir` in `tests/conftest.py`, and overridden per test in
    `client_env` in `tests/e2e/conftest.py`.
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
    exec_dir = _git_exec_dir()
    if exec_dir:
        env["PATH"] = os.pathsep.join([exec_dir, env.get("PATH", "")])
    return env


@functools.lru_cache(maxsize=None)
def _git_exec_dir() -> Optional[str]:
    """Return git's exec dir if it has a `git` binary, to put first on PATH.

    `git` on PATH may be a wrapper, e.g. LUCI's, which retries the server
    errors tests simulate for minutes.  The real git answers `--exec-path`
    (wrappers pass it through) & installs a copy of itself there, so putting
    that dir first makes the harness, repo & the git that repo runs all use the
    real git.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        proc = subprocess.run(
            ["git", "--exec-path"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
    except OSError:
        return None
    exec_dir = proc.stdout.decode("utf-8").strip()
    if proc.returncode or not any(
        os.path.isfile(os.path.join(exec_dir, name))
        for name in ("git", "git.exe")
    ):
        return None
    return exec_dir


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


def has_http_backend() -> bool:
    """Whether `git http-backend` is available."""
    try:
        exec_path = Path(run_git("--exec-path"))
    except (OSError, AssertionError):
        return False
    return any(
        (exec_path / name).exists()
        for name in ("git-http-backend", "git-http-backend.exe")
    )


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


class Request(NamedTuple):
    """A request received by GitHttpServer."""

    method: str
    path: str
    status: int


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Like `http.server.ThreadingHTTPServer`, which needs Python 3.7+."""

    daemon_threads = True
    # The default backlog of 5 can overflow when `repo sync` fetches many
    # projects in parallel, stalling connections on SYN retries.
    request_queue_size = 128


class GitHttpServer:
    """A local smart HTTP git server backed by `git http-backend`.

    All bare repositories under `root` are exported.  Requests for
    `<repo>/clone.bundle` are served from a `clone.bundle` file inside the
    repository directory (if it exists) to emulate Gerrit's bundle support.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.requests: List[Request] = []
        self._lock = threading.Lock()
        # Path prefixes for which every request fails; see offline().
        self._offline: Set[str] = set()
        self._httpd: Optional[_ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._env = dict(
            clean_environ(),
            GIT_HTTP_EXPORT_ALL="1",
            GIT_PROJECT_ROOT=str(root),
            HOME=str(root),
            USERPROFILE=str(root),
        )

    @property
    def url(self) -> str:
        """Base URL of the server (without trailing slash)."""
        assert self._httpd, "server not started"
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        """Start serving in a background thread."""
        server = self

        class Handler(_GitHttpHandler):
            git_server = server

        self._httpd = _ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="git-http-server"
        )
        self._thread.daemon = True
        self._thread.start()

    def stop(self) -> None:
        """Stop the server."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join()
            self._thread = None

    def record(self, method: str, path: str, status: int) -> None:
        with self._lock:
            self.requests.append(Request(method, path, status))

    def request_count(self) -> int:
        """Return the number of requests received so far."""
        with self._lock:
            return len(self.requests)

    def requests_for(self, prefix: str, start: int = 0) -> List[Request]:
        """Return the requests whose path starts with `prefix`.

        Args:
            prefix: The request path prefix to match.
            start: Skip the first `start` requests (see `request_count`).
        """
        with self._lock:
            return [
                r for r in self.requests[start:] if r.path.startswith(prefix)
            ]

    @contextlib.contextmanager
    def offline(self, prefix: str) -> Iterator[None]:
        """Fail all requests under the path `prefix` (like an outage).

        Requests are still recorded (with a 503 status) so tests can tell
        whether a command needed the network.
        """
        with self._lock:
            assert prefix not in self._offline, f"{prefix} is already offline"
            self._offline.add(prefix)
        try:
            yield
        finally:
            with self._lock:
                self._offline.discard(prefix)

    def is_offline(self, path: str) -> bool:
        """Whether requests for `path` should fail; see offline()."""
        with self._lock:
            return any(path.startswith(x) for x in self._offline)

    def run_backend(
        self,
        method: str,
        path: str,
        query: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bytes:
        """Run `git http-backend` as a CGI script and return its output."""
        env = dict(
            self._env,
            REQUEST_METHOD=method,
            PATH_INFO=path,
            QUERY_STRING=query,
            CONTENT_TYPE=headers.get("Content-Type", ""),
            CONTENT_LENGTH=str(len(body)),
            REMOTE_ADDR="127.0.0.1",
        )
        # Needed for git protocol v2.
        if headers.get("Git-Protocol"):
            env["GIT_PROTOCOL"] = headers["Git-Protocol"]
        if headers.get("Content-Encoding"):
            env["HTTP_CONTENT_ENCODING"] = headers["Content-Encoding"]
        proc = subprocess.run(
            ["git", "http-backend"],
            input=body,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return proc.stdout


class _GitHttpHandler(http.server.BaseHTTPRequestHandler):
    """Request handler for GitHttpServer."""

    git_server: GitHttpServer

    # Keep the protocol simple: one request per connection.
    protocol_version = "HTTP/1.0"

    def log_message(self, *args: object) -> None:
        """Silence the default stderr logging."""

    def _read_body(self) -> bytes:
        # Respond to libcurl's `Expect: 100-continue` immediately so chunked
        # POSTs don't wait for curl's 1s expect timeout under HTTP/1.0.
        if self.headers.get("Expect", "").lower() == "100-continue":
            self.send_response_only(100)
            self.end_headers()
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks = []
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                size = int(line.split(b";")[0].strip(), 16)
                if not size:
                    # Consume the trailer section.
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    @property
    def _request_path(self) -> str:
        """The URL-decoded request path (like CGI's PATH_INFO)."""
        return urllib.parse.unquote(self.path.partition("?")[0])

    def _send(self, status: int, headers: Dict[str, str], body: bytes) -> None:
        self.git_server.record(self.command, self._request_path, status)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve_bundle(self, path: str) -> None:
        repo = path[: -len("/clone.bundle")].strip("/")
        if ".." not in repo.split("/"):
            for candidate in (f"{repo}.git", repo):
                bundle = self.git_server.root / candidate / "clone.bundle"
                if bundle.is_file():
                    self._send(
                        200,
                        {"Content-Type": "application/octet-stream"},
                        bundle.read_bytes(),
                    )
                    return
        self._send(404, {"Content-Type": "text/plain"}, b"no bundle\n")

    def _handle(self) -> None:
        path = self._request_path
        query = self.path.partition("?")[2]
        if self.git_server.is_offline(path):
            # Drain any request body so the client sees the response.
            self._read_body()
            self._send(503, {"Content-Type": "text/plain"}, b"offline\n")
            return
        if path.endswith("/clone.bundle"):
            self._serve_bundle(path)
            return

        body = self._read_body()
        output = self.git_server.run_backend(
            self.command, path, query, self.headers, body
        )
        # Split the CGI response into headers & body at the first blank line.
        match = re.search(rb"\r?\n\r?\n", output)
        if not match:
            self._send(500, {}, b"invalid CGI response\n")
            return
        sep, body_start = match.span()
        status = 200
        headers = {}
        for line in output[:sep].decode("latin-1").splitlines():
            key, _, value = line.partition(":")
            if key.lower() == "status":
                status = int(value.split()[0])
            elif key and key.lower() != "content-length":
                headers[key] = value.strip()
        self._send(status, headers, output[body_start:])

    do_GET = _handle
    do_POST = _handle
    do_HEAD = _handle


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
    """A bare repository hosted by GitHttpServer."""

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

    def commit_history_only_blob(
        self, path: str, data: Union[str, bytes]
    ) -> str:
        """Commit `data` at `path`, then delete `path` in a second commit.

        Partial clones only download such blobs if the filter allows it.

        Returns:
            The id of the blob (only reachable from history).
        """
        self.commit({path: data}, message=f"add {path}")
        blob = self.git("rev-parse", f"{self.default_branch}:{path}")
        self.commit({path: None}, message=f"delete {path}")
        return blob

    def write_bundle(self) -> Path:
        """Write a clone.bundle (all branches & tags) served by the server."""
        bundle = self.path / "clone.bundle"
        self.git("bundle", "create", str(bundle), "--branches", "--tags")
        return bundle


def _manifest_files(
    content: Union[str, Mapping[str, FileContent]],
) -> Mapping[str, FileContent]:
    """Normalize default.xml contents or a map of files to a map of files."""
    return {"default.xml": content} if isinstance(content, str) else content


class GitHost:
    """A namespace of repositories on a GitHttpServer.

    Each test gets its own namespace so tests don't interfere with each other
    while sharing a single server.
    """

    def __init__(self, server: GitHttpServer, prefix: str) -> None:
        self.server = server
        self.prefix = prefix
        (server.root / prefix).mkdir(parents=True, exist_ok=True)

    @property
    def url(self) -> str:
        """Base URL for this namespace (without trailing slash)."""
        return f"{self.server.url}/{self.prefix}"

    def path_of(self, name: str) -> Path:
        return self.server.root / self.prefix / f"{name}.git"

    def url_of(self, name: str) -> str:
        return f"{self.url}/{name}"

    def create_repo(
        self,
        name: str,
        files: Optional[Mapping[str, FileContent]] = None,
        branch: str = "main",
    ) -> ServerRepo:
        """Create a repository, optionally with an initial commit."""
        repo = ServerRepo.create(
            self.path_of(name), self.url_of(name), default_branch=branch
        )
        if files is not None:
            repo.commit(files, branch=branch, message=f"{name}: initial")
        return repo

    @property
    def manifest_url(self) -> str:
        """URL of the manifest repo created by create_manifest."""
        return self.url_of(MANIFEST_REPO)

    def create_manifest(
        self,
        content: Union[str, Mapping[str, FileContent]],
        branch: str = "main",
    ) -> ServerRepo:
        """Create the manifest repo.

        Args:
            content: The default.xml contents, or a map of files.
            branch: The manifest branch.
        """
        return self.create_repo(
            MANIFEST_REPO, _manifest_files(content), branch=branch
        )

    def update_manifest(
        self,
        content: Union[str, Mapping[str, FileContent]],
        branch: str = "main",
    ) -> str:
        """Commit to the manifest repo.

        Args:
            content: The new default.xml contents, or a map of files.
            branch: The manifest branch.

        Returns:
            The new manifest commit id.
        """
        repo = ServerRepo(
            self.path_of(MANIFEST_REPO),
            self.manifest_url,
            default_branch=branch,
        )
        return repo.commit(_manifest_files(content), branch=branch)

    def fork(self, src: ServerRepo, name: str) -> ServerRepo:
        """Create a cheap copy of `src` sharing its objects via alternates.

        Use this before mutating a session-wide repo (e.g. the repo source).
        """
        repo = ServerRepo.create(
            self.path_of(name),
            self.url_of(name),
            default_branch=src.default_branch,
        )
        alternates = repo.path / "objects" / "info" / "alternates"
        # Use forward slashes & LF (write_text would emit CRLF on Windows),
        # which git accepts on every platform.
        objects = (src.path / "objects").as_posix()
        alternates.write_bytes(f"{objects}\n".encode())
        refs = src.git("for-each-ref", "--format=%(objectname) %(refname)")
        for line in refs.splitlines():
            oid, ref = line.split()
            repo.set_ref(ref, oid)
        return repo

    def requests(self) -> List[Request]:
        """All requests received for this namespace."""
        return self.server.requests_for(f"/{self.prefix}/")

    def requests_for(
        self, name: str, requests: Optional[List[Request]] = None
    ) -> List[Request]:
        """The requests for the repo `name` (out of `requests`, or all so far).

        Args:
            name: The repo name, e.g. `platform/foo`.
            requests: Requests to filter, e.g. from `watch_requests`.
        """
        if requests is None:
            requests = self.requests()
        prefix = f"/{self.prefix}/{name}/"
        return [r for r in requests if r.path.startswith(prefix)]

    def requested_repos(
        self, requests: Optional[List[Request]] = None
    ) -> Set[str]:
        """Return the names of the repos that received requests.

        Args:
            requests: Requests to inspect (e.g. from `watch_requests`), or all
                requests received so far if None.
        """
        if requests is None:
            requests = self.requests()
        namespace = f"/{self.prefix}/"
        names = set()
        for request in requests:
            if not request.path.startswith(namespace):
                continue
            for suffix in REPO_ENDPOINTS:
                if request.path.endswith(f"/{suffix}"):
                    names.add(request.path[len(namespace) : -len(suffix) - 1])
                    break
        return names

    @contextlib.contextmanager
    def watch_requests(self) -> Iterator[List[Request]]:
        """Collect the requests this namespace receives inside the block.

        The yielded list is filled in when the block exits, e.g.:

            with host.watch_requests() as requests:
                client.sync("-l")
            assert requests == []
        """
        start = self.server.request_count()
        requests: List[Request] = []
        try:
            yield requests
        finally:
            requests.extend(self.server.requests_for(f"/{self.prefix}/", start))

    @contextlib.contextmanager
    def offline(self) -> Iterator[None]:
        """Fail all requests for this namespace during the context.

        This emulates the server (or network) being unavailable.
        """
        with self.server.offline(f"/{self.prefix}/"):
            yield


def manifest_xml(*elements: str, default: Optional[str] = None) -> str:
    """Build a manifest with an `origin` remote & a default element.

    Args:
        elements: Extra XML elements (projects, etc...) to include.
        default: Attributes for the <default> element.
    """
    if default is None:
        default = 'remote="origin" revision="main"'
    body = "".join(f"  {x}\n" for x in elements)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <remote name="origin" fetch=".." />\n'
        f"  <default {default} />\n"
        f"{body}"
        "</manifest>\n"
    )


def _snapshot_worktree(root: Path) -> Dict[str, FileContent]:
    """Return the files in the git checkout at `root` (honoring .gitignore).

    This includes uncommitted & untracked (but not ignored) files.
    """
    # Use the developer's git config (not the isolated test HOME) so their
    # global excludes (e.g. a venv/) & safe.directory settings apply.
    env = clean_environ()
    del env["GIT_CONFIG_NOSYSTEM"]
    for key in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        env.pop(key, None)
        if key in HOST_ENVIRON:
            env[key] = HOST_ENVIRON[key]
    out = run_git(
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        cwd=root,
        env=env,
    )
    files: Dict[str, FileContent] = {}
    for name in sorted(set(out.split("\0"))):
        if not name:
            continue
        path = root / name
        try:
            st_mode = path.lstat().st_mode
        except OSError:
            # Deleted in the worktree but not (yet) in the index.
            continue
        if stat.S_ISLNK(st_mode):
            # Python <3.8 on Windows rejects Path objects here.
            files[name] = Blob(os.fsencode(os.readlink(str(path))), "120000")
        elif stat.S_ISREG(st_mode):
            mode = "100755" if st_mode & 0o111 else "100644"
            files[name] = Blob(path.read_bytes(), mode)
    return files


def publish_repo_source(dest: Path, url: str) -> ServerRepo:
    """Publish the code under test as a bare repository at `dest`.

    The snapshot is taken from the working tree so uncommitted local changes
    are tested too.  It's a single orphan commit (cheap to clone) with an
    annotated tag so `git describe` works like it does for releases.
    """
    repo = ServerRepo.create(dest, url, default_branch=REPO_SOURCE_BRANCH)
    commit = repo.commit(
        _snapshot_worktree(ROOT_DIR),
        branch=REPO_SOURCE_BRANCH,
        message="e2e snapshot of repo",
    )
    repo.tag("v99.0-e2e", commit)
    return repo


class RepoResult(NamedTuple):
    """Result of running a repo command."""

    args: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


class RepoCommandError(AssertionError):
    """A repo command exited with an unexpected status."""


class RepoClient:
    """Runs the repo launcher against a client checkout directory."""

    def __init__(
        self,
        top: Path,
        launcher: Path,
        env: Mapping[str, str],
        repo_url: str,
    ) -> None:
        self.top = top
        self.launcher = launcher
        self.env = dict(env)
        self.repo_url = repo_url
        # The launcher searches parent dirs for a client checkout, so an outer
        # one (e.g. `--basetemp` inside a repo client) would hijack the tests.
        for parent in top.resolve().parents:
            if (parent / ".repo" / "repo" / "main.py").is_file():
                raise AssertionError(
                    f"{top} is inside the repo client checkout {parent}; "
                    "use a different temp dir"
                )
        top.mkdir(parents=True, exist_ok=True)

    @property
    def repodir(self) -> Path:
        """The .repo/ directory."""
        return self.top / ".repo"

    def run(self, *args: str, check: bool = True) -> RepoResult:
        """Run `repo <args>` and return the result.

        The command & its output are printed so pytest displays them if the
        test fails on a later assertion.

        Raises:
            RepoCommandError: If `check` and the command failed.
        """
        argv = [sys.executable, str(self.launcher)] + list(args)
        cmd = f"repo {' '.join(args)}"
        start = time.monotonic()
        proc = subprocess.run(
            argv,
            # See run_git for why this isn't a Path.
            cwd=str(self.top),
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
        elapsed = time.monotonic() - start
        # Python on Windows writes `\r\n` to pipes; normalize so tests can match
        # multi-line output.
        result = RepoResult(
            list(args),
            proc.returncode,
            proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n"),
            proc.stderr.decode("utf-8", "replace").replace("\r\n", "\n"),
        )
        print(f"$ {cmd}  # exit {result.returncode} after {elapsed:.1f}s")
        if result.output:
            print(result.output.rstrip("\n"))
        if check and result.returncode:
            raise RepoCommandError(
                f"`{cmd}` failed with {result.returncode} "
                f"after {elapsed:.1f}s\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}"
            )
        return result

    def init(self, manifest_url: str, *args: str) -> RepoResult:
        """Run `repo init` installing the code under test."""
        return self.run(
            "init",
            "--manifest-url",
            manifest_url,
            "--repo-url",
            self.repo_url,
            "--repo-rev",
            REPO_SOURCE_BRANCH,
            "--no-repo-verify",
            *args,
        )

    def sync(self, *args: str, check: bool = True) -> RepoResult:
        """Run `repo sync`."""
        return self.run("sync", *args, check=check)

    def git(self, path: str, *args: str) -> str:
        """Run git in a checkout dir (relative to the client top)."""
        return run_git(*args, cwd=self.top / path, env=self.env)

    def head(self, path: str) -> str:
        """Return the commit checked out in `path`."""
        return self.git(path, "rev-parse", "HEAD")

    def is_detached(self, path: str) -> bool:
        """Whether HEAD in `path` is detached (not on a local branch)."""
        return self.git(path, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"

    def config(self, path: str, key: str) -> Optional[str]:
        """Return git config `key` of the checkout at `path` (None if unset).

        Only the repo's own config is read (not e.g. the user's), and `path`
        must be a git checkout.
        """
        proc = subprocess.run(
            ["git", "config", "--local", "--get", key],
            # See run_git for why this isn't a Path.
            cwd=str(self.top / path),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
        # git exits 1 for unset keys; anything else (e.g. 128 outside of a
        # repo) is a real error.
        if proc.returncode == 1:
            return None
        if proc.returncode:
            raise AssertionError(
                f"git config --get {key} failed in {path} "
                f"({proc.returncode}):\n"
                f"{proc.stderr.decode('utf-8', 'replace')}"
            )
        return proc.stdout.decode("utf-8").rstrip("\r\n")

    def remote_branches(self, path: str) -> Set[str]:
        """Return the names of the `origin` remote-tracking branches."""
        out = self.git(
            path,
            "for-each-ref",
            "--format=%(refname:lstrip=3)",
            "refs/remotes/origin/",
        )
        return set(out.split())

    def tags(self, path: str) -> Set[str]:
        """Return the names of the tags in `path`."""
        return set(self.git(path, "tag", "--list").split())

    def checkouts(self) -> Set[str]:
        """Return the names of the top-level dirs, except `.repo`."""
        return {
            x.name
            for x in self.top.iterdir()
            if x.is_dir() and x.name != ".repo"
        }

    def has_object(self, path: str, oid: str) -> bool:
        """Whether the checkout at `path` has object `oid` locally."""
        # Unlike `cat-file -e`, this never lazily fetches missing objects in
        # partial clones.  Test repos are small, so listing them all is cheap.
        out = self.git(
            path,
            "cat-file",
            "--batch-check=%(objectname)",
            "--batch-all-objects",
        )
        return oid in out.split()

    def is_shallow(self, path: str) -> bool:
        return self.git(path, "rev-parse", "--is-shallow-repository") == "true"

    def list_projects(self, *args: str) -> Dict[str, str]:
        """Return a map of project path to name from `repo list <args>`."""
        out = self.run("list", *args).stdout
        projects = {}
        for line in out.splitlines():
            path, _, name = line.partition(" : ")
            projects[path.strip()] = name.strip()
        return projects


@contextlib.contextmanager
def serve(root: Path) -> Iterator[GitHttpServer]:
    """Run a GitHttpServer for the duration of the context."""
    server = GitHttpServer(root)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def install_launcher(bindir: Path) -> Path:
    """Copy the repo launcher to `bindir`.

    A standalone copy is used (instead of running ./repo from the checkout) so
    the launcher behaves like an end user's install and runs the code that
    `repo init` fetched into .repo/repo/ rather than the checkout directly.
    """
    bindir.mkdir(parents=True, exist_ok=True)
    dest = bindir / "repo"
    shutil.copy2(LAUNCHER, dest)
    return dest
