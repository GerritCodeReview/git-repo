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

"""Fixtures for the hermetic end-to-end tests.

Tests normally only need the `host` fixture (to create server repos) and the
`client` fixture (to run repo).  Override the `git_defaults` fixture via
parametrize to run under Git 3 defaults.
"""

import itertools
from pathlib import Path
from typing import Dict, Iterator, List

import harness
import pytest


# Run before pytest's own `-m` deselection so `-m e2e` & `-m 'not e2e'` see the
# marker.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: List[pytest.Item]) -> None:
    """Mark tests in this directory as `e2e` & run them after unit tests.

    Note: pytest passes every collected item (not just this directory's), so
    this reorders the whole session.
    """
    this_dir = Path(__file__).resolve().parent
    for item in items:
        if this_dir in item.path.resolve().parents:
            item.add_marker(pytest.mark.e2e)
    # Stable sort: unit tests keep their order & come first, then E2E tests.
    items.sort(key=lambda item: item.get_closest_marker("e2e") is not None)


@pytest.fixture(scope="session", autouse=True)
def _require_e2e_support() -> None:
    """Skip the suite when the host can't run it."""
    # The code under test is published from the git checkout (e.g. this isn't
    # the case when running from an unpacked sdist).
    if not (harness.ROOT_DIR / ".git").exists():
        pytest.skip("E2E tests must run from a git checkout")
    if not harness.has_http_backend():
        pytest.skip("git http-backend is not available")
    if harness.git_version() < (2, 28, 0):
        pytest.skip("E2E tests require git 2.28+")


@pytest.fixture(scope="session")
def git_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[harness.GitHttpServer]:
    """A git smart HTTP server shared by all tests in the session."""
    with harness.serve(tmp_path_factory.mktemp("git-server")) as server:
        yield server


@pytest.fixture(scope="session")
def launcher(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A standalone copy of the repo launcher."""
    return harness.install_launcher(tmp_path_factory.mktemp("bin"))


@pytest.fixture(scope="session")
def repo_source(git_server: harness.GitHttpServer) -> harness.ServerRepo:
    """The code under test, published as a repo on `git_server`."""
    return harness.publish_repo_source(
        git_server.root / "git-repo.git", f"{git_server.url}/git-repo"
    )


NAMESPACE_IDS = itertools.count()


@pytest.fixture
def host(git_server: harness.GitHttpServer) -> harness.GitHost:
    """A per-test namespace for creating repos on the server."""
    return harness.GitHost(git_server, f"t{next(NAMESPACE_IDS)}")


@pytest.fixture
def git_defaults() -> str:
    """Client git defaults to emulate; a key of harness.GIT_DEFAULTS."""
    return "git2"


@pytest.fixture
def client_env(tmp_path: Path, git_defaults: str) -> Dict[str, str]:
    """Isolated environment for running repo & git as a client."""
    home = tmp_path / "home"
    home.mkdir()
    settings = {
        "user.name": "E2E User",
        "user.email": "user@example.com",
        "color.ui": "false",
        # Don't let background maintenance race with assertions.
        "maintenance.auto": "false",
        "gc.auto": "0",
    }
    if git_defaults == "git3" and harness.git_version() < (2, 47, 0):
        # init.defaultRefFormat & init.defaultObjectFormat landed in git 2.47.
        pytest.skip("git is too old to emulate Git 3 defaults")
    settings.update(harness.GIT_DEFAULTS[git_defaults])
    harness.write_config(home / ".gitconfig", settings)
    # Python resolves `~` via USERPROFILE on Windows.  The ceiling keeps git
    # from finding a repo above the test dir (e.g. with `--basetemp=./tmp`).
    return dict(
        harness.clean_environ(),
        HOME=str(home),
        USERPROFILE=str(home),
        GIT_CEILING_DIRECTORIES=str(tmp_path),
    )


@pytest.fixture
def client(
    tmp_path: Path,
    launcher: Path,
    repo_source: harness.ServerRepo,
    client_env: Dict[str, str],
) -> harness.RepoClient:
    """A repo client checkout directory that uses the code under test."""
    return harness.RepoClient(
        tmp_path / "client", launcher, client_env, repo_source.url
    )
