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

"""E2E regression tests for manifests that broke users in the past.

Each test names the commit and/or bug that fixed the original breakage.
"""

import os
from typing import List

from harness import GitHost
from harness import Gitlink
from harness import manifest_xml
from harness import RepoClient
import pytest


def test_empty_manifest(host: GitHost, client: RepoClient) -> None:
    """A manifest without projects syncs (616e314, b/377546300)."""
    host.create_manifest(manifest_xml())

    client.init(host.manifest_url)
    client.sync()

    assert client.list_projects() == {}


def test_local_extend_project_with_superproject(
    host: GitHost, client: RepoClient
) -> None:
    """Local `extend-project` works with superproject overrides.

    Regression test for 3c0e67b (b/470374343).
    """
    foo = host.create_repo("platform/foo", {"f": "v1"})
    pinned = foo.rev_parse("main")
    host.create_repo("superproject", {"foo": Gitlink(pinned)})
    foo.commit({"f": "v2"})
    host.create_manifest(
        manifest_xml(
            '<superproject name="superproject" />',
            '<project name="platform/foo" path="foo" />',
        )
    )
    client.init(host.manifest_url, "--use-superproject")
    local = client.repodir / "local_manifests"
    local.mkdir()
    (local / "local.xml").write_text(
        "<manifest>\n"
        '  <extend-project name="platform/foo" groups="extra" />\n'
        "</manifest>\n"
    )

    client.sync("--use-superproject")

    assert client.head("foo") == pinned


# 3af9e2f fixed both the regular & the --optimized-fetch skip-fetch checks.
@pytest.mark.parametrize("sync_args", [[], ["--optimized-fetch"]])
def test_same_project_shallow_pinned_paths(
    host: GitHost, client: RepoClient, sync_args: List[str]
) -> None:
    """One project at two paths pinned to SHAs with sync-c, one shallow.

    The non-shallow path shares the shallow path's (depth-limited) objects, so
    it needs its own shallow file too.

    Regression test for 3af9e2f (b/505072873).
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(manifest_xml())

    def pin(rev: str) -> None:
        host.update_manifest(
            manifest_xml(
                f'<project name="platform/foo" path="a" revision="{rev}" '
                'clone-depth="1" />',
                f'<project name="platform/foo" path="b" revision="{rev}" />',
                default='remote="origin" revision="main" sync-c="true"',
            )
        )

    pin(foo.commit({"f": "2"}))
    client.init(host.manifest_url)
    client.sync(*sync_args)

    latest = foo.commit({"f": "3"})
    pin(latest)
    client.sync(*sync_args)

    assert client.is_shallow("a")
    for path in ("a", "b"):
        assert client.head(path) == latest
        # Fails to traverse the shared, truncated history if `path` lacks a
        # shallow file.
        client.git(path, "rev-list", "HEAD")


def test_shallow_pinned_with_upstream(
    host: GitHost, client: RepoClient
) -> None:
    """clone-depth + upstream + SHA revisions stay shallow.

    The bug only triggered when the upstream branch was ahead of the pinned
    SHA, so each pin leaves `main` one commit ahead.

    Regression test for d9cc0a1 (b/427093249).
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(manifest_xml())

    def pin(rev: str) -> None:
        host.update_manifest(
            manifest_xml(
                f'<project name="platform/foo" revision="{rev}" '
                'upstream="main" clone-depth="1" />'
            )
        )

    path = "platform/foo"
    pinned = foo.commit({"f": "2"})
    foo.commit({"f": "2 ahead"})
    pin(pinned)
    client.init(host.manifest_url)
    client.sync()
    assert client.head(path) == pinned
    assert client.git(path, "rev-list", "--count", "HEAD") == "1"

    pinned = foo.commit({"f": "3"})
    foo.commit({"f": "3 ahead"})
    pin(pinned)
    client.sync()

    assert client.head(path) == pinned
    assert client.git(path, "rev-list", "--count", "HEAD") == "1"


def test_pinned_revision_refreshes_upstream(
    host: GitHost, client: RepoClient
) -> None:
    """Pinned SHAs already present locally still refresh the upstream ref.

    Regression test for d27d682: when the pinned commit was already in the
    local object store (e.g. prefetched), `sync -c` skipped the fetch as an
    immutable revision, so the stale tracking ref of the upstream branch was
    never updated.
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(manifest_xml())

    def pin(rev: str) -> None:
        host.update_manifest(
            manifest_xml(
                f'<project name="platform/foo" revision="{rev}" '
                'upstream="main" />',
                # The skip only happens when fetching the current branch only.
                default='remote="origin" revision="main" sync-c="true"',
            )
        )

    initial = foo.rev_parse("main")
    pin(initial)
    client.init(host.manifest_url)
    client.sync()

    path = "platform/foo"
    second = foo.commit({"f": "2"})
    latest = foo.commit({"f": "3"})
    # Emulate a background prefetch that doesn't touch the tracking refs.
    client.git(
        path, "fetch", "-q", "--refmap=", "origin", "+main:refs/prefetch/main"
    )
    assert client.has_object(path, second)
    assert client.git(path, "rev-parse", "refs/remotes/origin/main") == initial
    pin(second)
    client.sync()

    assert client.head(path) == second
    assert client.git(path, "rev-parse", "refs/remotes/origin/main") == latest


def test_nested_projects(host: GitHost, client: RepoClient) -> None:
    """Nested project paths are checked out and removed in the right order.

    Regression test for 4679022 (b/325119758).
    """
    foo = host.create_repo("platform/foo", {"f": "foo", "bar/f": "old"})
    host.create_repo("platform/bar", {"f": "foo/bar"})
    host.create_repo("platform/foo-bar", {"f": "foo-bar"})
    # aaa shares foo/bar's project, so foo/bar is grouped with it & checked out
    # early unless the checkout order puts it after its parent foo.
    host.create_manifest(
        manifest_xml(
            '<project name="platform/bar" path="aaa" />',
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/foo-bar" path="foo-bar" />',
        )
    )
    client.init(host.manifest_url)
    client.sync()

    # Move foo's bar/f into the new nested project foo/bar.
    foo.commit({"bar/f": None})
    host.update_manifest(
        manifest_xml(
            '<project name="platform/bar" path="aaa" />',
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="foo/bar" />',
            '<project name="platform/foo-bar" path="foo-bar" />',
        )
    )
    client.sync("-j1")

    for path in ("foo", "foo/bar", "foo-bar"):
        assert (client.top / path / "f").read_text() == path
    assert client.git("foo/bar", "status", "--porcelain") == ""

    host.update_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/foo-bar" path="foo-bar" />',
        )
    )
    client.sync()

    assert set(client.list_projects()) == {"foo", "foo-bar"}
    assert not (client.top / "foo/bar").exists()
    assert (client.top / "foo/f").read_text() == "foo"


def test_copyfile_linkfile(host: GitHost, client: RepoClient) -> None:
    """copyfile and linkfile are created, updated and cleaned up.

    linkfile symlinks are relative (0184dcc) so trees can be moved.
    """
    foo = host.create_repo(
        "platform/foo", {"copy.txt": "v1", "dir/link.txt": "link"}
    )
    host.create_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo">'
            '<copyfile src="copy.txt" dest="copied.txt" />'
            '<linkfile src="dir/link.txt" dest="links/link.txt" />'
            "</project>"
        )
    )
    client.init(host.manifest_url)
    client.sync()

    link = client.top / "links/link.txt"
    assert os.readlink(link) == os.path.join("..", "foo", "dir", "link.txt")
    assert link.read_text() == "link"
    assert (client.top / "copied.txt").read_text() == "v1"

    foo.commit({"copy.txt": "v2"})
    host.update_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo">'
            '<copyfile src="copy.txt" dest="copied.txt" />'
            "</project>"
        )
    )
    client.sync()

    assert (client.top / "copied.txt").read_text() == "v2"
    assert not os.path.lexists(link)


@pytest.mark.parametrize("sync_args", [[], ["--no-interleaved"]])
def test_submodules(
    host: GitHost, client: RepoClient, sync_args: List[str]
) -> None:
    """sync-s checks out & updates submodules, incl. for repeated projects.

    Regression tests for 4623264 (b/444366154, `git submodule init` in
    interleaved sync), 1b4e7a0 (the same repo checked out at multiple paths),
    and 3a6e25a/3f087a8 (b/550074864, submodules follow their parent's new
    revision in the same interleaved & phased sync).
    """
    sub = host.create_repo("platform/sub", {"s": "1"})
    gitmodules = '[submodule "sub"]\n\tpath = sub\n\turl = ../sub\n'
    foo = host.create_repo(
        "platform/foo",
        {".gitmodules": gitmodules, "sub": Gitlink(sub.rev_parse("main"))},
    )
    paths = ("a", "b")
    # Track a branch, as gitlinks are only stale (b/550074864) when the
    # parent's revision resolves before it's fetched (unlike new pinned SHAs).
    # With sync-c, phased syncs skip fetching the stale (present) revision.
    host.create_manifest(
        manifest_xml(
            *(
                f'<project name="platform/foo" path="{p}" sync-s="true" '
                'sync-c="true" />'
                for p in paths
            )
        )
    )

    client.init(host.manifest_url)
    client.sync(*sync_args)
    for path in paths:
        assert (client.top / path / "sub/s").read_text() == "1"
        assert client.git(path, "config", "--get", "submodule.sub.url")

    latest = foo.commit({"sub": Gitlink(sub.commit({"s": "2"}))})
    client.sync(*sync_args)

    for path in paths:
        assert client.head(path) == latest
        assert (client.top / path / "sub/s").read_text() == "2"


# The default layout reads HEAD from the ref cache instead of GetHead().
@pytest.mark.parametrize("init_args", [[], ["--worktree"]])
def test_prune_detached_head(
    host: GitHost, client: RepoClient, init_args: List[str]
) -> None:
    """`repo prune` handles projects with a detached HEAD.

    Regression test for 7f7d70e (b/434077990).
    """
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))
    client.init(host.manifest_url, *init_args)
    client.sync()
    path = "platform/foo"
    client.run("start", "topic", "--all")
    client.git(path, "checkout", "-q", "--detach")

    client.run("prune")

    assert not client.git(path, "branch", "--list", "topic")


def test_submanifest_groups(host: GitHost, client: RepoClient) -> None:
    """Submanifests apply their own default groups.

    Regression test for cc88be3 (b/382086294).
    """
    for name in ("parent", "child", "child-extra"):
        host.create_repo(f"platform/{name}", {"f": name})
    host.create_repo(
        "platform/child-manifest",
        {
            "default.xml": manifest_xml(
                '<project name="platform/child" path="child" groups="g1" />',
                '<project name="platform/child-extra" path="extra" />',
            )
        },
    )
    host.create_manifest(
        manifest_xml(
            '<project name="platform/parent" path="parent" />',
            '<submanifest name="sub" project="platform/child-manifest" '
            'revision="main" path="sub" default-groups="g1" />',
        )
    )

    client.init(host.manifest_url)
    client.sync()

    assert client.list_projects() == {
        "parent": "platform/parent",
        "sub/child": "platform/child",
    }
    assert (client.top / "sub/child/f").read_text() == "child"
    assert not (client.top / "sub/extra").exists()
