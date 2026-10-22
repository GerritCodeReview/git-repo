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

The harness has two parts:

* `GitHttpServer`: a local smart HTTP git server built on `git http-backend`.
  It also serves static `clone.bundle` files like Gerrit/GoB do.
* `ServerRepo`/`GitHost`: bare repositories hosted by the server, with helpers
  to create commits (including gitlinks for superprojects), branches, tags &
  bundles without needing a worktree.
"""

import contextlib
import functools
import http.server
import os
from pathlib import Path
import re
import socketserver
import subprocess
import sys
import threading
from typing import (
    Dict,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Tuple,
    Union,
)
import urllib.parse


# Every repo/git subprocess gets this timeout so a hang can't wedge the CQ.
COMMAND_TIMEOUT = 300

# The manifest repo lives two levels deep (like AOSP's platform/manifest) so
# the common `fetch=".."` resolves to the root of the host namespace.
MANIFEST_REPO = "platform/manifest"

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
        cwd=cwd,
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

    def requests_for(self, prefix: str) -> List[Request]:
        """Return the requests whose path starts with `prefix`."""
        with self._lock:
            return [r for r in self.requests if r.path.startswith(prefix)]

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


@contextlib.contextmanager
def serve(root: Path) -> Iterator[GitHttpServer]:
    """Run a GitHttpServer for the duration of the context."""
    server = GitHttpServer(root)
    server.start()
    try:
        yield server
    finally:
        server.stop()
