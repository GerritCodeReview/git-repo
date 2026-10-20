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

from harness import GIT_DEFAULTS_PARAMS
from harness import GitHost
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
