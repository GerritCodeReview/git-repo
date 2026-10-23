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

"""E2E tests for multi-step workflows, many from past point releases."""

import os
import re
import time
from typing import List

from harness import GIT_DEFAULTS_PARAMS
from harness import GitHost
from harness import manifest_xml
from harness import RepoClient
from harness import run_git
from harness import ServerRepo
import pytest


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
@pytest.mark.parametrize(
    "project_attrs",
    ["", 'clone-depth="1"', 'sync-strategy="stateless"'],
)
def test_two_phase_sync(
    host: GitHost, client: RepoClient, project_attrs: str
) -> None:
    """`repo sync -n` then `repo sync -l` before worktrees exist.

    Regression tests for b/565047698 (v2.68.1, incl. e1e215a for stateless
    syncs).
    """
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(
        manifest_xml(
            f'<project name="platform/foo" path="foo" {project_attrs} />'
        )
    )
    client.init(host.manifest_url)

    # The b/565047698 regression only logs a warning & still exits 0, so also
    # require a clean stderr.
    assert client.sync("-n").stderr == ""
    assert not (client.top / "foo").exists()
    # A second network-only sync (after upstream moved) with no worktree yet.
    latest = foo.commit({"f": "2"})
    assert client.sync("-n").stderr == ""
    assert not (client.top / "foo").exists()

    client.sync("-l")
    assert client.head("foo") == latest
    assert (client.top / "foo/f").read_text() == "2"

    # And the checkout keeps working with regular syncs afterwards.
    latest = foo.commit({"f": "3"})
    client.sync()
    assert client.head("foo") == latest


@pytest.mark.parametrize(
    "extra_init_args", [[], ["--manifest-upstream-branch", "main"]]
)
def test_init_manifest_commit(
    host: GitHost, client: RepoClient, extra_init_args: List[str]
) -> None:
    """`repo init -b <sha>` pins the manifest to a raw commit.

    Regression test for b/544041102 (v2.66.1).
    """
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_repo("platform/bar", {"f": "bar"})
    manifest = host.create_manifest(
        manifest_xml('<project name="platform/foo" />')
    )
    pinned = manifest.rev_parse("main")
    host.update_manifest(
        manifest_xml(
            '<project name="platform/foo" />',
            '<project name="platform/bar" />',
        )
    )

    client.init(host.manifest_url, "-b", pinned, *extra_init_args)
    client.sync()

    assert client.list_projects() == {"platform/foo": "platform/foo"}
    assert client.git(".repo/manifests", "rev-parse", "HEAD") == pinned


@pytest.mark.parametrize("git_defaults", GIT_DEFAULTS_PARAMS)
def test_mirror(host: GitHost, client: RepoClient) -> None:
    """`repo init --mirror && repo sync` creates bare mirrors (v2.57.1)."""
    foo = host.create_repo("platform/foo", {"f": "1"})
    foo.commit({"f": "other"}, branch="other")
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))

    client.init(host.manifest_url, "--mirror")
    client.sync()

    mirror = client.top / "platform/foo.git"

    def mirror_rev(ref: str) -> str:
        return run_git(f"--git-dir={mirror}", "rev-parse", ref, env=client.env)

    assert not (client.top / "platform/foo").exists()
    assert mirror_rev("refs/heads/main") == foo.rev_parse("main")
    assert mirror_rev("refs/heads/other") == foo.rev_parse("other")

    latest = foo.commit({"f": "2"})
    client.sync()
    assert mirror_rev("refs/heads/main") == latest


def test_incremental_sync(host: GitHost, client: RepoClient) -> None:
    """Syncs pick up new commits, new projects & removed projects."""
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_repo("platform/bar", {"f": "bar"})
    host.create_repo("platform/baz", {"f": "baz"})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/bar" path="bar" />',
        )
    )
    client.init(host.manifest_url)
    client.sync()

    latest = foo.commit({"f": "2", "new": "new"})
    host.update_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            '<project name="platform/baz" path="baz" />',
        )
    )
    client.sync()

    assert client.head("foo") == latest
    assert (client.top / "foo/new").read_text() == "new"
    assert (client.top / "baz/f").read_text() == "baz"
    assert not (client.top / "bar").exists()
    assert client.list_projects() == {
        "baz": "platform/baz",
        "foo": "platform/foo",
    }


def test_rebase_local_work(host: GitHost, client: RepoClient) -> None:
    """Local commits on a `repo start` branch are rebased by sync."""
    foo = host.create_repo("platform/foo", {"f": "1"})
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))
    client.init(host.manifest_url)
    client.sync()

    path = "platform/foo"
    client.run("start", "topic", "--all")
    (client.top / path / "local").write_text("local")
    client.git(path, "add", "local")
    client.git(path, "commit", "-q", "-m", "local change")
    latest = foo.commit({"f": "2"})

    client.sync()

    assert client.git(path, "symbolic-ref", "--short", "HEAD") == "topic"
    assert client.git(path, "rev-parse", "HEAD~1") == latest
    assert (client.top / path / "local").read_text() == "local"


def test_switch_manifest_branch(host: GitHost, client: RepoClient) -> None:
    """Re-running `repo init -b` on an existing checkout switches branches."""
    foo = host.create_repo("platform/foo", {"f": "main"})
    release = foo.commit({"f": "release"}, branch="release")
    host.create_manifest(
        manifest_xml('<project name="platform/foo" path="foo" />')
    )
    host.update_manifest(
        manifest_xml(
            '<project name="platform/foo" path="foo" />',
            default='remote="origin" revision="release"',
        ),
        branch="release",
    )
    client.init(host.manifest_url)
    client.sync()
    assert client.head("foo") == foo.rev_parse("main")

    client.init(host.manifest_url, "-b", "release")
    client.sync()

    assert client.head("foo") == release


@pytest.mark.parametrize(
    "command",
    [
        ["selfupdate", "--no-repo-verify"],
        ["sync", "--no-repo-verify"],
    ],
)
def test_selfupdate(
    host: GitHost,
    client: RepoClient,
    repo_source: ServerRepo,
    command: List[str],
) -> None:
    """repo upgrades itself when its source moves forward."""
    source = host.fork(repo_source, "git-repo")
    client.repo_url = source.url
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))
    # Start from an existing synced checkout before publishing the repo update.
    client.init(host.manifest_url)
    client.sync()

    latest = source.commit({"E2E_SELFUPDATE_MARKER": "new"})
    # sync only checks for updates once a day.
    fetch_head = client.repodir / "repo/.git/FETCH_HEAD"
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(fetch_head, (old, old))

    result = client.run(*command)

    assert "A new version of repo is available" in result.stderr
    assert client.git(".repo/repo", "rev-parse", "HEAD") == latest
    assert (client.repodir / "repo/E2E_SELFUPDATE_MARKER").exists()
    # The restarted (upgraded) repo keeps working.
    assert "v99.0-e2e-1-g" in client.run("version").stdout


def test_commands_after_sync(host: GitHost, client: RepoClient) -> None:
    """Common read-only commands work on a freshly synced checkout."""
    host.create_repo("platform/foo", {"f": "foo"})
    host.create_manifest(manifest_xml('<project name="platform/foo" />'))
    client.init(host.manifest_url)
    client.sync()

    for command, expected in (
        (["status"], r"nothing to commit"),
        (["info"], r"Manifest branch: main"),
        (["branches"], r"\(no branches\)"),
        # No local changes, so no output.
        (["diff"], r"\A\Z"),
        (["forall", "-c", "git", "log", "-1"], r"platform/foo: initial"),
        # Projects are pinned to commit ids.
        (["manifest", "-r"], r'revision="[0-9a-f]{40}"'),
    ):
        output = client.run(*command).output
        assert re.search(expected, output), (
            f"`repo {' '.join(command)}` output {output!r} "
            f"did not match {expected!r}"
        )
