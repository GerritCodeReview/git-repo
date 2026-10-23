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

"""E2E tests for partial clones, incl. the standard Android configuration."""

import os
from typing import Dict, List, NamedTuple, Tuple

from harness import GIT_DEFAULTS_PARAMS
from harness import GitHost
from harness import Gitlink
from harness import manifest_xml
from harness import RepoClient
from harness import ServerRepo
import pytest


# The go/repo-init flags.  The filter is 10M there; 10k keeps the test data
# small without changing the semantics.
ANDROID_INIT_ARGS = [
    "-c",
    "-b",
    "main",
    "--use-superproject",
    "--partial-clone",
    "--partial-clone-exclude=platform/frameworks/base",
    "--clone-filter=blob:limit=10k",
]

# The go/sync flags.
ANDROID_SYNC_ARGS = ["-c", "-j20", "--no-tags", "--optimized-fetch", "--prune"]

# Larger than the 10k filter above, smaller than git's default big file
# threshold so it's still delta compressed & packed normally.
BIG = "x" * 20_000

# The git config key holding a partial clone's filter.
FILTER_KEY = "remote.origin.partialclonefilter"


def create_with_big_history(host: GitHost, name: str) -> Tuple[ServerRepo, str]:
    """Create `name` with a large blob that only exists in history.

    Returns:
        The repo and the id of the historical large blob.  The tip commit has
        a different large blob (`big2.bin`) and a small file.
    """
    repo = host.create_repo(name, {"big.bin": BIG, "small": "s"})
    big_blob = repo.git("rev-parse", "main:big.bin")
    repo.commit({"big.bin": None, "big2.bin": BIG + "2"})
    return repo, big_blob


class AndroidTree(NamedTuple):
    """The server side of `create_android_tree`, keyed by project path."""

    repos: Dict[str, ServerRepo]
    superproject: ServerRepo
    # The commit the superproject pins each project to.
    pins: Dict[str, str]
    # A large blob that only exists in each project's history.
    blobs: Dict[str, str]


def create_android_tree(host: GitHost) -> AndroidTree:
    """Create a small AOSP-like tree with a superproject.

    `platform/foo` is a regular project and `platform/frameworks/base` is the
    one go/repo-init excludes from the partial clone.  Both have moved past
    the superproject's pins.
    """
    repos, pins, blobs = {}, {}, {}
    for path in ("foo", "frameworks/base"):
        name = f"platform/{path}"
        repos[path], blobs[path] = create_with_big_history(host, name)
        pins[path] = repos[path].rev_parse("main")
    superproject = host.create_repo(
        "platform/superproject",
        {path: Gitlink(rev) for path, rev in pins.items()},
    )
    for repo in repos.values():
        repo.commit({"small": "ahead"})
        repo.commit({"small": "other"}, branch="other")
    host.create_manifest(
        manifest_xml(
            '<superproject name="platform/superproject" />',
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/frameworks/base" '
            'path="frameworks/base" />',
        )
    )
    return AndroidTree(repos, superproject, pins, blobs)


def bundle_requests(host: GitHost) -> Dict[str, List[int]]:
    """Map repo name to the status codes of its `clone.bundle` requests."""
    result: Dict[str, List[int]] = {}
    for r in host.requests():
        if r.path.endswith("/clone.bundle"):
            name = r.path[len(f"/{host.prefix}/") : -len("/clone.bundle")]
            result.setdefault(name, []).append(r.status)
    return result


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
def test_android_init_sync(host: GitHost, client: RepoClient) -> None:
    """The go/repo-init flag combination followed by `repo sync -c -j32`.

    Covers superproject pinning, `-c`, the clone filter on included projects,
    no filter on the `--partial-clone-exclude`d project, and that historical
    large blobs stay on the server while small historical blobs are fetched.
    """
    tree = create_android_tree(host)
    small_history_blob = tree.repos["foo"].commit_history_only_blob(
        "small_old.txt", b"small history"
    )
    new_foo_pin = tree.repos["foo"].rev_parse("main")
    tree.superproject.commit({"foo": Gitlink(new_foo_pin)})
    tree.repos["foo"].commit({"small": "unpinned"})
    pins = dict(tree.pins, foo=new_foo_pin)

    client.init(host.manifest_url, *ANDROID_INIT_ARGS)
    assert client.sync("-c", "-j32").stderr == ""

    # init persisted the settings later syncs depend on.
    manifests = ".repo/manifests"
    assert client.config(manifests, "repo.superproject") == "true"
    assert client.config(manifests, "repo.partialclone") == "true"
    assert client.config(manifests, "repo.clonefilter") == "blob:limit=10k"
    assert (
        client.config(manifests, "repo.partialcloneexclude")
        == "platform/frameworks/base"
    )
    for path, pinned in pins.items():
        assert client.head(path) == pinned
        assert (client.top / path / "big2.bin").read_text() == BIG + "2"
        assert client.remote_branches(path) == {"main"}
    override = client.repodir / "exp-superproject/superproject_override.xml"
    assert override.exists()
    # The included project is a partial clone (git normalizes the size), so
    # the large historical blob was never downloaded, while the small
    # historical blob (under the 10k limit) was downloaded.
    assert client.config("foo", "extensions.partialclone") == "origin"
    assert client.config("foo", FILTER_KEY) == "blob:limit=10240"
    assert not client.has_object("foo", tree.blobs["foo"])
    assert client.has_object("foo", small_history_blob)
    # The excluded project is a full clone.
    assert client.config("frameworks/base", "extensions.partialclone") is None
    assert client.config("frameworks/base", FILTER_KEY) is None
    assert client.has_object("frameworks/base", tree.blobs["frameworks/base"])
    # Partial clones disable clone bundles, but repo still requests one for
    # excluded projects (this server has none).
    assert bundle_requests(host) == {"platform/frameworks/base": [404]}


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
def test_android_sync_flags(host: GitHost, client: RepoClient) -> None:
    """The go/sync flags on an initial & an incremental sync.

    `-c -jN --no-tags --optimized-fetch --prune` on top of the go/repo-init
    configuration.  The incremental sync must fetch a project whose pin moved
    and skip one whose pin didn't.
    """
    tree = create_android_tree(host)
    tree.repos["foo"].tag("v1", tree.pins["foo"])

    client.init(host.manifest_url, *ANDROID_INIT_ARGS)
    assert client.sync(*ANDROID_SYNC_ARGS).stderr == ""

    for path, pinned in tree.pins.items():
        assert client.head(path) == pinned
        assert client.remote_branches(path) == {"main"}
        assert client.tags(path) == set()

    # Move foo's pin forward (on main) & tag it; frameworks/base keeps its pin.
    new_pin = tree.repos["foo"].commit({"small": "new pin"})
    tree.repos["foo"].tag("v2", new_pin)
    tree.superproject.commit({"foo": Gitlink(new_pin)})
    with host.watch_requests() as requests:
        assert client.sync(*ANDROID_SYNC_ARGS).stderr == ""

    assert client.head("foo") == new_pin
    assert client.head("frameworks/base") == tree.pins["frameworks/base"]
    assert client.tags("foo") == set()
    assert (client.top / "foo/small").read_text() == "new pin"
    # A project already at its (immutable) pin isn't fetched.
    assert host.requested_repos(requests) == {
        "platform/manifest",
        "platform/superproject",
        "platform/foo",
    }


def test_partial_clone_default_filter(
    host: GitHost, client: RepoClient
) -> None:
    """`--partial-clone` alone uses `blob:none` & disables clone bundles."""
    foo, big_blob = create_with_big_history(host, "platform/foo")
    small_history = foo.commit_history_only_blob("old_small.txt", b"tiny")
    small_tip = foo.git("rev-parse", "main:small")
    foo.write_bundle()
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))

    client.init(host.manifest_url, "--partial-clone")
    client.sync()

    path = "platform/foo"
    assert client.config(".repo/manifests", "repo.partialclone") == "true"
    assert client.config(".repo/manifests", "repo.clonefilter") == "blob:none"
    assert client.config(".repo/manifests", FILTER_KEY) == "blob:none"
    assert client.config(path, FILTER_KEY) == "blob:none"
    assert client.config(path, "extensions.partialclone") == "origin"
    # Blobs of the checked out tree were fetched on demand; history wasn't
    # (even tiny blobs).
    assert (client.top / path / "big2.bin").read_text() == BIG + "2"
    assert client.has_object(path, small_tip)
    assert not client.has_object(path, big_blob)
    assert not client.has_object(path, small_history)
    assert bundle_requests(host) == {}


def test_partial_clone_two_phase_sync(
    host: GitHost, client: RepoClient
) -> None:
    """`sync -n` then `sync -l` with a partial clone (initial & incremental).

    The network phase fetches no blobs, so the local phase has to fetch the
    checked out blobs on demand: `-l` isn't offline for partial clones.  When
    the server is unreachable, `sync -l` fails cleanly & can be retried.
    """
    foo, big_blob = create_with_big_history(host, "platform/foo")
    small_blob = foo.git("rev-parse", "main:small")
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))
    client.init(host.manifest_url, "--partial-clone")

    assert client.sync("-n").stderr == ""
    path = "platform/foo"
    assert not (client.top / path).exists()
    gitdir = f"--git-dir={client.repodir / 'projects' / path}.git"
    assert client.git(
        ".", gitdir, "rev-parse", "refs/remotes/origin/main"
    ) == foo.rev_parse("main")
    objects = client.git(
        ".",
        gitdir,
        "cat-file",
        "--batch-check=%(objectname)",
        "--batch-all-objects",
    ).split()
    assert foo.rev_parse("main") in objects
    assert small_blob not in objects

    # When the server is offline, `sync -l` fails cleanly without leaving a
    # broken worktree behind.
    with host.offline():
        failed = client.sync("-l", check=False)
    assert failed.returncode != 0
    assert "Cannot initialize work tree for platform/foo" in failed.stderr
    assert not os.path.lexists(client.top / path / ".git")

    with host.watch_requests() as requests:
        client.sync("-l")

    assert client.head(path) == foo.rev_parse("main")
    assert (client.top / path / "big2.bin").read_text() == BIG + "2"
    assert client.has_object(path, small_blob)
    assert not client.has_object(path, big_blob)
    # The on-demand blob fetches are the only traffic of the local sync.
    assert host.requested_repos(requests) == {"platform/foo"}

    # Incremental `-n` then `-l` on the existing partial-clone checkout.
    v2 = foo.commit({"small": "s2"})
    s2_blob = foo.git("rev-parse", "main:small")
    client.sync("-n")
    assert (client.top / path / "small").read_text() == "s"
    assert not client.has_object(path, s2_blob)

    with host.watch_requests() as inc_requests:
        client.sync("-l")
    assert client.head(path) == v2
    assert (client.top / path / "small").read_text() == "s2"
    assert client.has_object(path, s2_blob)
    assert host.requested_repos(inc_requests) == {"platform/foo"}
