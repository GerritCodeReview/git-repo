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

"""E2E tests for manifest groups beyond `repo init -g`."""

import platform
from typing import Dict, List, Optional, Set

from harness import GitHost
from harness import Gitlink
from harness import manifest_xml
from harness import RepoClient
from harness import ServerRepo
import pytest


# `a` & `b` are in the default group; `c` & `d` are not.
GROUPED_MANIFEST = manifest_xml(
    '<project name="platform/a" path="a" />',
    '<project name="platform/b" path="b" groups="g1" />',
    '<project name="platform/c" path="c" groups="g2,notdefault" />',
    '<project name="platform/d" path="d" groups="notdefault" />',
)


def create_grouped_projects(host: GitHost) -> Dict[str, ServerRepo]:
    """Create the projects of `GROUPED_MANIFEST` & the manifest itself."""
    repos = {}
    for name in "abcd":
        repos[name] = host.create_repo(f"platform/{name}", {"f": name})
    host.create_manifest(GROUPED_MANIFEST)
    return repos


def listed(client: RepoClient, *args: str) -> Set[str]:
    """The project paths printed by `repo list <args>`."""
    return set(client.list_projects(*args))


def test_reinit_groups(host: GitHost, client: RepoClient) -> None:
    """Re-running `init -g` adds & removes projects on the next sync."""
    create_grouped_projects(host)
    this_platform = f"platform-{platform.system().lower()}"
    client.init(host.manifest_url)
    client.sync()
    assert client.checkouts() == {"a", "b"}
    assert client.config(".repo/manifests", "manifest.groups") is None

    client.init(host.manifest_url, "-g", "default,g2")
    client.sync()

    assert client.checkouts() == {"a", "b", "c"}
    assert (
        client.config(".repo/manifests", "manifest.groups")
        == f"default,g2,{this_platform}"
    )

    client.init(host.manifest_url, "-g", "g2")
    client.sync()

    assert client.checkouts() == {"c"}
    assert client.list_projects() == {"c": "platform/c"}
    assert (
        client.config(".repo/manifests", "manifest.groups")
        == f"g2,{this_platform}"
    )
    # The object dirs of removed projects are kept for a later re-add.
    assert (client.repodir / "project-objects/platform/a.git").is_dir()

    # Back to the default groups.
    client.init(host.manifest_url, "-g", "default")
    client.sync()
    assert client.checkouts() == {"a", "b"}
    assert (client.top / "a/f").read_text() == "a"


@pytest.mark.parametrize(
    "init_args,expected",
    [
        ([], {"base"}),
        (["-g", "default,extra"], {"base", "extra", "extra2"}),
        (["-g", "default,extra,-g2"], {"base", "extra"}),
        (["-g", "g2"], {"extra2"}),
    ],
)
def test_include_groups(
    host: GitHost, client: RepoClient, init_args: List[str], expected: Set[str]
) -> None:
    """`<include groups=...>` adds its groups to every included project."""
    for name in ("base", "extra", "extra2"):
        host.create_repo(f"platform/{name}", {"f": name})
    host.create_manifest(
        {
            "default.xml": manifest_xml(
                '<project name="platform/base" path="base" />',
                '<include name="extra.xml" groups="notdefault,extra" />',
            ),
            "extra.xml": (
                "<manifest>\n"
                '  <project name="platform/extra" path="extra" />\n'
                '  <project name="platform/extra2" path="extra2" '
                'groups="g2" />\n'
                "</manifest>\n"
            ),
        }
    )

    client.init(host.manifest_url, *init_args)
    client.sync()

    assert client.checkouts() == expected
    assert set(client.list_projects()) == expected
    # The include's groups are merged with the project's own.
    assert listed(client, "-a", "-g", "extra") == {"extra", "extra2"}
    assert listed(client, "-a", "-g", "g2") == {"extra2"}


@pytest.mark.parametrize(
    "init_args,platforms",
    [
        # None means the platform the test runs on.
        ([], None),
        (["--platform=all"], {"linux", "darwin", "windows"}),
        (["--platform=none"], set()),
        (["-p", "darwin"], {"darwin"}),
        (["-g", "default,platform-linux", "--platform=none"], {"linux"}),
    ],
)
def test_platform_groups(
    host: GitHost,
    client: RepoClient,
    init_args: List[str],
    platforms: Optional[Set[str]],
) -> None:
    """`platform-*` groups follow the host OS unless `--platform` is given."""
    names = ("linux", "darwin", "windows")
    host.create_repo("platform/base", {"f": "base"})
    for name in names:
        host.create_repo(f"platform/{name}", {"f": name})
    host.create_manifest(
        manifest_xml(
            '<project name="platform/base" path="base" />',
            *(
                f'<project name="platform/{name}" path="{name}" '
                f'groups="notdefault,platform-{name}" />'
                for name in names
            ),
        )
    )
    if platforms is None:
        platforms = {platform.system().lower()}

    client.init(host.manifest_url, *init_args)
    client.sync()

    assert client.checkouts() == {"base"} | platforms
    assert set(client.list_projects()) == {"base"} | platforms


def test_groups_with_superproject(host: GitHost, client: RepoClient) -> None:
    """Group selection applies on top of superproject pinning."""
    pins = {}
    for name in "ab":
        repo = host.create_repo(f"platform/{name}", {"f": "v1"})
        pins[name] = repo.rev_parse("main")
        repo.commit({"f": "v2"})
    host.create_repo(
        "superproject", {name: Gitlink(rev) for name, rev in pins.items()}
    )
    host.create_manifest(
        manifest_xml(
            '<superproject name="superproject" />',
            '<project name="platform/a" path="a" />',
            '<project name="platform/b" path="b" groups="notdefault,g1" />',
        )
    )

    client.init(host.manifest_url, "--use-superproject")
    assert client.sync().stderr == ""

    assert client.checkouts() == {"a"}
    assert client.head("a") == pins["a"]
    assert host.requests_for("platform/b") == []

    client.init(host.manifest_url, "-g", "all")
    assert client.sync().stderr == ""

    assert client.checkouts() == {"a", "b"}
    assert client.head("b") == pins["b"]
    assert (client.top / "b/f").read_text() == "v1"
