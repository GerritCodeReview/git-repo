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

"""E2E tests for failure paths: sync must fail loudly & leave a usable tree.

Note: repo retries failed fetches once after a few seconds, so each failing
fetch costs about 5s.
"""

from typing import List

from harness import GitHost
from harness import manifest_xml
from harness import RepoClient
import pytest


@pytest.mark.parametrize(
    "sync_args",
    [
        pytest.param(["-j1"], id="interleaved"),
        pytest.param(["-j1", "--fail-fast"], id="fail-fast"),
    ],
)
def test_missing_project(
    host: GitHost, client: RepoClient, sync_args: List[str]
) -> None:
    """A project missing on the server fails the sync with a useful error.

    By default the other projects are still synced & creating the missing repo
    lets the next sync recover; with `--fail-fast` the sync stops at the first
    failure without contacting later repos.
    """
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_repo("platform/bar", {"f": "bar"})
    # Paths sort the missing project first, so `-j1` reaches it first.
    host.create_manifest(
        manifest_xml(
            '<project name="platform/missing" path="missing" />',
            '<project name="platform/foo" path="present-foo" />',
            '<project name="platform/bar" path="present-bar" />',
        )
    )
    client.init(host.manifest_url)

    with host.watch_requests() as requests:
        result = client.sync(*sync_args, check=False)

    assert result.returncode != 0
    # The failing fetch & git's reason are reported either way.
    assert "on platform/missing failed" in result.output
    assert "not found" in result.output
    assert not (client.top / "missing").exists()
    # Repo requested the missing project (it's a 404, not a client bug).
    assert {r.status for r in host.requests_for("platform/missing")} == {404}

    if "--fail-fast" in sync_args:
        assert "SyncFailFastError" in result.stderr
        assert client.checkouts() == set()
        assert host.requested_repos(requests) == {
            "platform/manifest",
            "platform/missing",
        }
        return

    assert client.checkouts() == {"present-bar", "present-foo"}
    assert "error: Unable to fully sync the tree" in result.stderr
    assert "Failing repos (network):\nmissing" in result.stderr
    assert 'Try re-running with "-j1 --fail-fast"' in result.stderr

    # Once the missing project exists on the server, the next sync recovers.
    host.create_repo("platform/missing", {"f": "missing"})
    client.sync(*sync_args)
    assert client.checkouts() == {"missing", "present-bar", "present-foo"}
    assert (client.top / "missing/f").read_text() == "missing"


@pytest.mark.parametrize(
    "revision,error",
    [
        (
            "nonexistent",
            "couldn't find remote ref refs/heads/nonexistent",
        ),
        # A pinned commit that was never pushed.
        ("1" * 40, "1" * 40),
    ],
    ids=["branch", "commit"],
)
def test_missing_project_revision(
    host: GitHost, client: RepoClient, revision: str, error: str
) -> None:
    """A manifest revision that doesn't exist on the server fails the sync."""
    foo = host.create_repo("platform/foo", {"f": "foo"})
    host.create_manifest(
        manifest_xml(
            f'<project name="platform/foo" path="foo" revision="{revision}" />',
            '<project name="platform/foo" path="ok" />',
        )
    )
    client.init(host.manifest_url)

    result = client.sync(check=False)

    assert result.returncode != 0
    assert "error: Unable to fully sync the tree" in result.stderr
    assert "Failing repos (network):\nfoo" in result.stderr
    assert error in result.stderr
    assert not (client.top / "foo").exists()
    assert client.head("ok") == foo.rev_parse("main")

    # Fixing the missing branch on the server recovers on the next sync.
    if revision == "nonexistent":
        fixed = foo.commit({"f": "fixed"}, branch="nonexistent")
        client.sync()
        assert client.head("foo") == fixed


def test_missing_manifest_branch(host: GitHost, client: RepoClient) -> None:
    """`init -b` with a branch the manifest repo doesn't have fails cleanly.

    The half-initialized manifest checkout is removed so a corrected `init`
    starts from scratch.
    """
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))

    result = client.init(host.manifest_url, "-b", "nonexistent", check=False)
    assert result.returncode != 0
    assert "couldn't find remote ref refs/heads/nonexistent" in result.output
    assert "fatal: cannot obtain manifest" in result.stderr
    assert not (client.repodir / "manifests.git").exists()

    client.init(host.manifest_url, "-b", "main")
    client.sync()
    assert (client.top / "platform/foo/f").read_text() == "foo"


@pytest.mark.parametrize("on_branch", [False, True])
def test_dirty_worktree_blocks_sync(
    host: GitHost, client: RepoClient, on_branch: bool
) -> None:
    """Uncommitted changes that conflict with upstream fail the checkout.

    The local change is preserved and the fetched objects are kept, so the
    user can resolve it and run `repo sync -l`.  On a detached HEAD,
    `--force-checkout` discards the local change instead.
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(
        manifest_xml('<project name="platform/foo" path="foo" />')
    )
    client.init(host.manifest_url)
    client.sync()
    old = foo.rev_parse("main")
    if on_branch:
        client.run("start", "topic", "--all")
    (client.top / "foo/f").write_text("local")
    latest = foo.commit({"f": "2"})

    result = client.sync(check=False)

    assert result.returncode != 0
    assert "error: Checking out local projects failed" in result.stderr
    assert "Failing repos (checkout):\nfoo" in result.stderr
    if on_branch:
        assert "contains uncommitted changes" in result.stderr
    else:
        assert f"platform/foo checkout {latest}" in result.stderr
    assert (client.top / "foo/f").read_text() == "local"
    assert client.head("foo") == old
    assert client.git("foo", "rev-parse", "refs/remotes/origin/main") == latest

    if not on_branch:
        client.sync("--force-checkout")
    else:
        # Discarding the edit & running `sync -l` recovers without touching
        # the network.
        client.git("foo", "checkout", "--", "f")
        with host.watch_requests() as requests, host.offline():
            client.sync("-l")
        assert requests == []
    assert client.head("foo") == latest
    assert (client.top / "foo/f").read_text() == "2"
