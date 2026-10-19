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

"""E2E tests for the core `repo init` & `repo sync` options."""

import shutil
from typing import List, Set

from harness import GIT_DEFAULTS_PARAMS
from harness import GitHost
from harness import Gitlink
from harness import manifest_xml
from harness import RepoClient
import pytest


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
def test_init_sync_basic(host: GitHost, client: RepoClient) -> None:
    """The basic `repo init && repo sync` flow."""
    foo = host.create_repo("platform/foo", {"foo.txt": "foo"})
    host.create_repo("platform/bar", {"bar.txt": "bar"})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="sub/bar" />',
        )
    )

    client.init(host.manifest_url)
    client.sync()

    assert (client.top / "foo" / "foo.txt").read_text() == "foo"
    assert (client.top / "sub" / "bar" / "bar.txt").read_text() == "bar"
    assert client.head("foo") == foo.rev_parse("main")
    assert client.list_projects() == {
        "foo": "platform/foo",
        "sub/bar": "platform/bar",
    }
    # The code under test is what got installed & is running.
    assert "v99.0-e2e" in client.run("version").stdout


@pytest.mark.parametrize(
    "init_args,sync_args,manifest_refs,project_refs",
    [
        # `init -c` is the default for the manifest project.
        ([], [], {"main"}, {"main", "other"}),
        (["--no-current-branch"], [], {"main", "other"}, {"main", "other"}),
        ([], ["-c"], {"main"}, {"main"}),
    ],
)
def test_current_branch(
    host: GitHost,
    client: RepoClient,
    init_args: List[str],
    sync_args: List[str],
    manifest_refs: Set[str],
    project_refs: Set[str],
) -> None:
    """`init` limits the manifest fetch; `sync -c` limits projects."""
    foo = host.create_repo("platform/foo", {"foo.txt": "main"})
    foo.commit({"foo.txt": "other"}, branch="other")
    manifest = host.create_manifest(
        manifest_xml('<project name="platform/foo" />')
    )
    manifest.commit({"README": "other"}, branch="other")

    def remote_branches(path: str) -> Set[str]:
        out = client.git(
            path,
            "for-each-ref",
            "--format=%(refname:lstrip=3)",
            "refs/remotes/origin/",
        )
        return set(out.split())

    client.init(host.manifest_url, *init_args)
    assert remote_branches(".repo/manifests") == manifest_refs

    client.sync(*sync_args)
    assert remote_branches("platform/foo") == project_refs
    assert (client.top / "platform/foo/foo.txt").read_text() == "main"


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
@pytest.mark.parametrize("use_superproject", [True, False])
def test_superproject(
    host: GitHost, client: RepoClient, use_superproject: bool
) -> None:
    """Projects are pinned to the superproject's gitlinks when enabled."""
    foo = host.create_repo("platform/foo", {"foo.txt": "v1"})
    pinned = foo.rev_parse("main")
    host.create_repo("superproject", {"foo": Gitlink(pinned)})
    # Advance the project past what the superproject points to.
    latest = foo.commit({"foo.txt": "v2"})
    host.create_manifest(
        manifest_xml(
            '<superproject name="superproject" />',
            '<project name="platform/foo" path="foo" />',
        )
    )
    flag = "--use-superproject" if use_superproject else "--no-use-superproject"

    client.init(host.manifest_url, flag)
    client.sync(flag)

    assert client.head("foo") == (pinned if use_superproject else latest)
    override = client.repodir / "exp-superproject/superproject_override.xml"
    assert override.exists() == use_superproject


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
def test_partial_clone(host: GitHost, client: RepoClient) -> None:
    """`--partial-clone` leaves large historical blobs on the server."""
    big = "x" * 20_000
    foo = host.create_repo("platform/foo", {"big.bin": big, "small": "s"})
    big_blob = foo.git("rev-parse", "main:big.bin")
    foo.commit({"big.bin": None, "big2.bin": big + "2"})
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))

    client.init(
        host.manifest_url, "--partial-clone", "--clone-filter=blob:limit=10k"
    )
    client.sync()

    path = "platform/foo"
    # git normalizes the size suffix.
    assert (
        client.git(path, "config", "remote.origin.partialclonefilter")
        == "blob:limit=10240"
    )
    # The checked out large blob was lazily fetched,
    assert (client.top / path / "big2.bin").read_text() == big + "2"
    # while the one only in history was never downloaded.
    assert not client.has_object(path, big_blob)


@pytest.mark.skipif(not shutil.which("curl"), reason="requires curl")
@pytest.mark.parametrize(
    "sync_args,expect_bundle", [([], True), (["--no-clone-bundle"], False)]
)
def test_clone_bundle(
    host: GitHost,
    client: RepoClient,
    sync_args: List[str],
    expect_bundle: bool,
) -> None:
    """repo bootstraps new projects from clone.bundle when available."""
    foo = host.create_repo("platform/foo", {"foo.txt": "foo"})
    # A commit that only the bundle has, to prove the bundle was applied.
    bundle_only = foo.commit({"x": "bundle"}, branch="bundle-only")
    foo.write_bundle()
    foo.git("update-ref", "-d", "refs/heads/bundle-only")
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))

    client.init(host.manifest_url)
    client.sync(*sync_args)

    bundle_gets = [
        r
        for r in host.requests()
        if r.path.endswith("/platform/foo/clone.bundle")
    ]
    assert [r.status for r in bundle_gets] == ([200] if expect_bundle else [])
    assert client.has_object("platform/foo", bundle_only) == expect_bundle
    assert client.head("platform/foo") == foo.rev_parse("main")


@pytest.mark.parametrize(
    "init_args,project_attrs",
    [
        (["--depth=1"], ""),
        ([], 'clone-depth="1"'),
    ],
)
def test_shallow(
    host: GitHost,
    client: RepoClient,
    init_args: List[str],
    project_attrs: str,
) -> None:
    """Shallow clones via `--depth` and manifest `clone-depth`."""
    foo = host.create_repo("platform/foo", {"foo.txt": "1"})
    foo.commit({"foo.txt": "2"})
    foo.commit({"foo.txt": "3"})
    host.create_manifest(
        manifest_xml(f'<project name="platform/foo" {project_attrs} />')
    )

    client.init(host.manifest_url, *init_args)
    client.sync()

    path = "platform/foo"
    assert client.is_shallow(path)
    assert client.git(path, "rev-list", "--count", "HEAD") == "1"
    assert (client.top / path / "foo.txt").read_text() == "3"


@pytest.mark.parametrize(
    "init_args,expected",
    [
        ([], {"a", "b"}),
        (["-g", "all"], {"a", "b", "c", "d"}),
        (["-g", "g2"], {"c"}),
        (["-g", "default,-g1"], {"a"}),
        (["-g", "default,g2"], {"a", "b", "c"}),
        (["-g", "name:platform/d"], {"d"}),
    ],
)
def test_groups(
    host: GitHost, client: RepoClient, init_args: List[str], expected: Set[str]
) -> None:
    """Manifest groups select which projects get synced."""
    for name in "abcd":
        host.create_repo(f"platform/{name}", {"f": name})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/a" path="a" />',
            '<project name="platform/b" path="b" groups="g1" />',
            '<project name="platform/c" path="c" groups="g2,notdefault" />',
            '<project name="platform/d" path="d" groups="notdefault" />',
        )
    )

    client.init(host.manifest_url, *init_args)
    client.sync()

    assert set(client.list_projects()) == expected
    on_disk = {x.name for x in client.top.iterdir() if x.name != ".repo"}
    assert on_disk == expected


def test_local_manifests(host: GitHost, client: RepoClient) -> None:
    """.repo/local_manifests/ can add, remove & extend projects."""
    foo = host.create_repo("platform/foo", {"f": "main"})
    stable = foo.commit({"f": "stable"}, branch="stable")
    host.create_repo("platform/bar", {"f": "bar"})
    host.create_repo("vendor/extra", {"f": "extra"})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="bar" />',
        )
    )
    client.init(host.manifest_url)
    local = client.repodir / "local_manifests"
    local.mkdir()
    (local / "local.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remove-project name="platform/bar" />
  <extend-project name="platform/foo" revision="stable" />
  <project name="vendor/extra" path="extra" />
</manifest>
"""
    )

    client.sync()

    assert client.list_projects() == {
        "extra": "vendor/extra",
        "foo": "platform/foo",
    }
    assert client.head("foo") == stable
    assert not (client.top / "bar").exists()


def test_manifest_name(host: GitHost, client: RepoClient) -> None:
    """`-m` selects a manifest file other than default.xml."""
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_repo("platform/bar", {"f": "bar"})
    host.create_manifest(
        {
            "default.xml": manifest_xml('<project name="platform/foo" />'),
            "other.xml": manifest_xml('<project name="platform/bar" />'),
        }
    )

    client.init(host.manifest_url, "-m", "other.xml")
    client.sync()

    assert client.list_projects() == {"platform/bar": "platform/bar"}
