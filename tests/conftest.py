# Copyright (C) 2022 The Android Open Source Project
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

"""Common fixtures for pytests."""

import pathlib
from typing import Any, Generator

import pytest

import color
import platform_utils
import repo_trace


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--fail-on-skip",
        action="store_true",
        help="fail skipped tests (run_tests sets this in CQ)",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, Any, None]:
    """Fail skipped tests with --fail-on-skip.

    A skip in CQ usually means the builder is missing a dependency (e.g. a new
    enough git), which would otherwise silently drop coverage.  Tests that
    should not run in CQ are deselected via the `skip_cq` marker instead.
    """
    outcome = yield
    report = outcome.get_result()
    if (
        item.config.getoption("fail_on_skip")
        and report.skipped
        # xfail outcomes are also reported as skipped.
        and not hasattr(report, "wasxfail")
    ):
        reason = report.longrepr
        if isinstance(reason, tuple):
            # (path, lineno, reason)
            reason = reason[2]
        report.outcome = "failed"
        report.longrepr = f"Not allowed with --fail-on-skip: {reason}"


@pytest.fixture(autouse=True)
def disable_repo_trace(tmp_path):
    """Set an environment marker to relax certain strict checks for test code."""  # noqa: E501
    repo_trace.SetTrace(False)
    repo_trace._TRACE_FILE = str(tmp_path / "TRACE_FILE_from_test")


@pytest.fixture(autouse=True)
def restore_default_coloring() -> None:
    """Force disable color for reproducible test behavior.

    The few tests that cover color behavior can still reset/change the color as
    needed.
    """
    color.SetDefaultColoring("never")


# adapted from pytest-home 0.5.1
def _set_home(monkeypatch, path: pathlib.Path):
    """
    Set the home dir using a pytest monkeypatch context.
    """
    win = platform_utils.isWindows()
    vars = ["HOME"] + win * ["USERPROFILE"]
    for var in vars:
        monkeypatch.setenv(var, str(path))
    return path


# copied from
# https://github.com/pytest-dev/pytest/issues/363#issuecomment-1335631998
@pytest.fixture(scope="session")
def monkeysession():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


@pytest.fixture(autouse=True, scope="session")
def session_tmp_home_dir(tmp_path_factory, monkeysession):
    """Set HOME to a temporary directory, avoiding user's .gitconfig.

    b/302797407

    Set home at session scope to take effect prior to
    ``test_wrapper.GitCheckoutTestCase.setUpClass``.
    """
    return _set_home(monkeysession, tmp_path_factory.mktemp("home"))


# adapted from pytest-home 0.5.1
@pytest.fixture(autouse=True)
def tmp_home_dir(monkeypatch, tmp_path_factory):
    """Set HOME to a temporary directory.

    Ensures that state doesn't accumulate in $HOME across tests.

    Note that in conjunction with session_tmp_homedir, the HOME
    dir is patched twice, once at session scope, and then again at
    the function scope.
    """
    return _set_home(monkeypatch, tmp_path_factory.mktemp("home"))


@pytest.fixture(autouse=True)
def setup_user_identity(monkeysession, scope="session"):
    """Set env variables for author and committer name and email."""
    monkeysession.setenv("GIT_AUTHOR_NAME", "Foo Bar")
    monkeysession.setenv("GIT_COMMITTER_NAME", "Foo Bar")
    monkeysession.setenv("GIT_AUTHOR_EMAIL", "foo@bar.baz")
    monkeysession.setenv("GIT_COMMITTER_EMAIL", "foo@bar.baz")
