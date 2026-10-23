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

"""E2E tests for `repo sync` modes (`-n`, `-l`) & sync flags."""

from typing import List

from harness import GIT_DEFAULTS_PARAMS
from harness import GitHost
from harness import Gitlink
from harness import manifest_xml
from harness import RepoClient
import pytest


# Interleaved (the default) & phased syncs implement `-n` & `-l` separately.
SYNC_MODES = [[], ["--no-interleaved"]]


@pytest.mark.parametrize("mode_args", SYNC_MODES, ids=["interleaved", "phased"])
def test_network_only_then_local_only(
    host: GitHost, client: RepoClient, mode_args: List[str]
) -> None:
    """`sync -n` on an existing checkout updates objects & remote refs only.

    The worktree, HEAD & local branches don't change until `sync -l`, which
    checks out what `-n` fetched without touching the network.
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    bar = host.create_repo("platform/bar", {"f": "1"})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="bar" />',
        )
    )
    client.init(host.manifest_url)
    client.sync(*mode_args)
    old_foo = foo.rev_parse("main")
    # Local work on a topic branch in bar.
    client.run("start", "topic", "bar")
    (client.top / "bar/local").write_text("local")
    client.git("bar", "add", "local")
    client.git("bar", "commit", "-q", "-m", "local change")
    local_commit = client.head("bar")
    fetched = {"foo": foo.commit({"f": "2"}), "bar": bar.commit({"f": "2"})}

    assert client.sync("-n", *mode_args).stderr == ""

    assert client.head("foo") == old_foo
    assert (client.top / "foo/f").read_text() == "1"
    assert client.head("bar") == local_commit
    assert client.git("bar", "symbolic-ref", "--short", "HEAD") == "topic"
    for path, commit in fetched.items():
        assert client.has_object(path, commit)
        assert client.git(path, "rev-parse", "refs/remotes/origin/main") == (
            commit
        )
        assert client.git(path, "status", "--porcelain") == ""

    # The server moves on, but `-l` must only use what `-n` fetched.
    foo.commit({"f": "3"})
    with host.watch_requests() as requests, host.offline():
        client.sync("-l", *mode_args)

    assert requests == []
    assert client.head("foo") == fetched["foo"]
    assert (client.top / "foo/f").read_text() == "2"
    # The local commit on `bar` was rebased onto what `-n` fetched.
    assert client.git("bar", "symbolic-ref", "--short", "HEAD") == "topic"
    assert client.git("bar", "rev-parse", "HEAD~1") == fetched["bar"]
    assert (client.top / "bar/local").read_text() == "local"


def test_local_only_unfetched_project(
    host: GitHost, client: RepoClient
) -> None:
    """`sync -l` fails clearly for a project that was never fetched.

    The other projects are still checked out, no network requests are made,
    and the error says how to fix it.
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_repo("platform/bar", {"f": "bar"})
    host.create_manifest(
        manifest_xml('<project name="platform/foo" path="foo" />')
    )
    client.init(host.manifest_url)
    client.sync()
    v2 = foo.commit({"f": "2"})
    host.update_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="bar" />',
        )
    )
    # Update the manifest & fetch foo, but not the new project.
    client.sync("-n", "platform/foo")
    assert not (client.repodir / "projects/bar.git").exists()

    with host.watch_requests() as requests, host.offline():
        result = client.sync("-l", check=False)

    assert requests == []
    assert result.returncode != 0
    assert (
        "Cannot checkout platform/bar due to missing network sync; Run "
        "`repo sync -n platform/bar` first." in result.stderr
    )
    assert not (client.top / "bar").exists()
    # The already-fetched project still got checked out.
    assert client.head("foo") == v2
    assert (client.top / "foo/f").read_text() == "2"

    # Fetching the missing project fixes it.
    client.sync("-n", "platform/bar")
    with host.watch_requests() as requests, host.offline():
        client.sync("-l")
    assert requests == []
    assert (client.top / "bar/f").read_text() == "bar"
    assert client.list_projects() == {
        "bar": "platform/bar",
        "foo": "platform/foo",
    }


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
def test_two_phase_sync_superproject(host: GitHost, client: RepoClient) -> None:
    """`sync -n` pins projects via the superproject; `sync -l` reuses the pins.

    The local phase must not hit the network, even to re-read the
    superproject after the server's superproject moved on.
    """
    foo = host.create_repo("platform/foo", {"f": "v1"})
    pinned = foo.rev_parse("main")
    superproject = host.create_repo("superproject", {"foo": Gitlink(pinned)})
    foo.commit({"f": "v2"})
    host.create_manifest(
        manifest_xml(
            '<superproject name="superproject" />',
            '<project name="platform/foo" path="foo" />',
        )
    )
    client.init(host.manifest_url, "--use-superproject")

    assert client.sync("-n").stderr == ""
    assert not (client.top / "foo").exists()
    assert (
        client.repodir / "exp-superproject/superproject_override.xml"
    ).exists()

    # Advance the superproject on the server before running `sync -l`.
    new_pin = foo.commit({"f": "v3"})
    superproject.commit({"foo": Gitlink(new_pin)})

    with host.watch_requests() as requests, host.offline():
        client.sync("-l")

    assert requests == []
    assert client.head("foo") == pinned
    assert (client.top / "foo/f").read_text() == "v1"

    # The next two-phase sync picks up the new superproject pin.
    client.sync("-n")
    assert client.head("foo") == pinned
    with host.watch_requests() as requests, host.offline():
        client.sync("-l")
    assert requests == []
    assert client.head("foo") == new_pin
    assert (client.top / "foo/f").read_text() == "v3"


@pytest.mark.parametrize(
    "sync_args,project_attrs,expect_tags",
    [
        # Despite `repo sync --help` calling `--no-tags` the default.
        ([], "", True),
        # `-c` only limits branches: tags on other branches are still fetched
        # unless `--no-tags` is passed.
        (["-c"], "", True),
        (["--tags"], "", True),
        (["-c", "--no-tags"], "", False),
        (["-c"], 'sync-tags="false"', False),
        (["-c", "--tags"], 'sync-tags="false"', True),
    ],
)
def test_tags(
    host: GitHost,
    client: RepoClient,
    sync_args: List[str],
    project_attrs: str,
    expect_tags: bool,
) -> None:
    """Tags are fetched unless `--no-tags` or the manifest says `sync-tags`."""
    foo = host.create_repo("platform/foo", {"f": "1"})
    foo.tag("v1", "main")
    # A tag that isn't on the synced branch, like release tags usually are.
    foo.commit({"f": "release"}, branch="release")
    foo.tag("v2", "release")
    host.create_manifest(
        manifest_xml(f'<project name="platform/foo" {project_attrs} />')
    )

    client.init(host.manifest_url)
    client.sync(*sync_args)

    assert client.tags("platform/foo") == (
        {"v1", "v2"} if expect_tags else set()
    )
    expected_branches = {"main"} if "-c" in sync_args else {"main", "release"}
    assert client.remote_branches("platform/foo") == expected_branches


def test_prune(host: GitHost, client: RepoClient) -> None:
    """Remote-tracking branches deleted on the server are pruned by default.

    `--no-prune` keeps them.
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    foo.commit({"f": "stale"}, branch="stale")
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))
    client.init(host.manifest_url)
    client.sync()
    path = "platform/foo"
    assert client.remote_branches(path) == {"main", "stale"}

    foo.git("update-ref", "-d", "refs/heads/stale")
    client.sync("--no-prune")
    assert client.remote_branches(path) == {"main", "stale"}

    client.sync()
    assert client.remote_branches(path) == {"main"}


def test_force_sync(host: GitHost, client: RepoClient) -> None:
    """`--force-sync` re-creates a path whose project changed in the manifest.

    The old gitdir points at another project's object dir, which sync refuses
    to overwrite unless forced.
    """
    host.create_repo("platform/foo", {"f": "foo"})
    foo_v2 = host.create_repo("platform/foo-v2", {"f": "foo-v2"})
    host.create_manifest(
        manifest_xml('<project name="platform/foo" path="foo" />')
    )
    client.init(host.manifest_url)
    client.sync()
    host.update_manifest(
        manifest_xml('<project name="platform/foo-v2" path="foo" />')
    )

    result = client.sync(check=False)

    assert result.returncode != 0
    assert "--force-sync not enabled" in result.stderr
    assert "`repo sync --force-sync foo`" in result.stderr
    assert (client.top / "foo/f").read_text() == "foo"

    client.sync("--force-sync")

    assert client.head("foo") == foo_v2.rev_parse("main")
    assert (client.top / "foo/f").read_text() == "foo-v2"
    assert client.list_projects() == {"foo": "platform/foo-v2"}
    assert client.git("foo", "status", "--porcelain") == ""


def test_force_remove_dirty(host: GitHost, client: RepoClient) -> None:
    """Removed projects with uncommitted changes need `--force-remove-dirty`."""
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_repo("platform/bar", {"f": "bar"})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="bar" />',
        )
    )
    client.init(host.manifest_url)
    client.sync()
    (client.top / "bar/f").write_text("dirty")
    host.update_manifest(
        manifest_xml('<project name="platform/foo" path="foo" />')
    )

    # Repeat to check that the project stays tracked in project.list (rather
    # than forgotten & left behind) after the first failure.
    for _ in range(2):
        result = client.sync(check=False)
        assert result.returncode != 0
        assert (
            "bar: Cannot remove project: uncommitted changes are present"
            in result.stderr
        )
        assert (client.top / "bar/f").read_text() == "dirty"

    result = client.sync("--force-remove-dirty")
    assert "bar: Removing dirty project" in result.stderr
    assert not (client.top / "bar").exists()
    assert client.list_projects() == {"foo": "platform/foo"}


def test_detach(host: GitHost, client: RepoClient) -> None:
    """`sync -d` detaches projects on a topic branch at the manifest revision.

    The topic branch & its local commit are left alone.
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(
        manifest_xml('<project name="platform/foo" path="foo" />')
    )
    client.init(host.manifest_url)
    client.sync()
    client.run("start", "topic", "--all")
    (client.top / "foo/local").write_text("local")
    client.git("foo", "add", "local")
    client.git("foo", "commit", "-q", "-m", "local change")
    local = client.head("foo")
    latest = foo.commit({"f": "2"})

    client.sync("-d")

    assert client.is_detached("foo")
    assert client.head("foo") == latest
    assert (client.top / "foo/f").read_text() == "2"
    assert not (client.top / "foo/local").exists()
    assert client.git("foo", "rev-parse", "topic") == local
    # A regular sync afterwards stays detached.
    client.sync()
    assert client.is_detached("foo")
