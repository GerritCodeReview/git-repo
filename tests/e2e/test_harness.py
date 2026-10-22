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

"""Tests for the E2E harness helpers themselves."""

import http.client
from pathlib import Path
from typing import Iterator, Mapping
import urllib.parse

import harness
import pytest


# `ServerRepo.create` uses `git init --initial-branch`.
pytestmark = pytest.mark.skipif(
    harness.git_version() < (2, 28, 0), reason="requires git 2.28+"
)


@pytest.fixture
def git_server(tmp_path: Path) -> Iterator[harness.GitHttpServer]:
    """A git smart HTTP server for a single test."""
    if not harness.has_http_backend():
        pytest.skip("git http-backend is not available")
    with harness.serve(tmp_path) as server:
        yield server


@pytest.mark.parametrize(
    "key,value",
    [
        ("core.bare", "true"),
        ('url.C:\\src\\#1;"x".insteadOf', 'C:\\dst\\ #2;"y"'),
        ("alias.multi", "a\nb"),
    ],
)
def test_write_config(tmp_path: Path, key: str, value: str) -> None:
    """Subsections & values round-trip through git's config parser."""
    path = tmp_path / "config"
    harness.write_config(path, {key: value})
    got = harness.run_git("config", "--file", str(path), "--get", key)
    assert got == value


@pytest.mark.parametrize(
    "files",
    [
        {"foo/bar": "x", "foo": None},
        {"foo": None, "foo/bar": "x"},
    ],
)
def test_commit_replace_file_with_dir(
    tmp_path: Path, files: Mapping[str, harness.FileContent]
) -> None:
    """Deletions apply before additions regardless of dict order."""
    repo = harness.ServerRepo.create(tmp_path / "repo.git", "unused")
    repo.commit({"foo": "file"})
    repo.commit(files)
    assert repo.git("ls-tree", "-r", "--name-only", "main") == "foo/bar"


def test_snapshot_worktree_host_excludes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The developer's global excludes apply despite the isolated HOME."""
    host_home = tmp_path / "host-home"
    host_home.mkdir()
    excludes = host_home / "excludes"
    excludes.write_text("venv/\n")
    # Set excludesFile explicitly so a system-wide one can't take precedence.
    harness.write_config(
        host_home / ".gitconfig", {"core.excludesFile": excludes.as_posix()}
    )
    monkeypatch.setattr(harness, "HOST_ENVIRON", {"HOME": str(host_home)})
    root = tmp_path / "checkout"
    harness.run_git("init", "--quiet", str(root))
    (root / ".gitignore").write_text("*.pyc\n")
    (root / "main.py").write_text("")
    (root / "main.pyc").write_text("")
    (root / "venv").mkdir()
    (root / "venv" / "lib.py").write_text("")
    assert sorted(harness._snapshot_worktree(root)) == [".gitignore", "main.py"]


@pytest.mark.parametrize(
    "chunked,expect_continue",
    [(False, False), (True, False), (True, True)],
)
def test_http_post_body(
    git_server: harness.GitHttpServer, chunked: bool, expect_continue: bool
) -> None:
    """POST bodies reach git http-backend however curl encodes them."""
    name = f"post-{int(chunked)}{int(expect_continue)}.git"
    repo = harness.ServerRepo.create(git_server.root / name, "unused")
    commit = repo.commit({"file": "x"})
    # A protocol v2 ls-refs request: a command pkt-line & a flush-pkt.
    body = b"0014command=ls-refs\n0000"
    headers = {
        "Content-Type": "application/x-git-upload-pack-request",
        "Git-Protocol": "version=2",
    }
    if expect_continue:
        headers["Expect"] = "100-continue"
    url = urllib.parse.urlsplit(git_server.url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
    try:
        # http.client skips any interim `100 Continue` response.
        conn.request(
            "POST",
            f"/{name}/git-upload-pack",
            body=iter([body[:10], body[10:]]) if chunked else body,
            headers=headers,
            encode_chunked=chunked,
        )
        resp = conn.getresponse()
        assert resp.status == 200
        assert f"{commit} refs/heads/main".encode() in resp.read()
    finally:
        conn.close()
