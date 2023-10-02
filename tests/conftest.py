# Copyright 2022 The Android Open Source Project
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

import shutil

import pytest

import platform_utils
import repo_trace


@pytest.fixture(autouse=True)
def disable_repo_trace(tmp_path):
    """Set an environment marker to relax certain strict checks for test code."""  # noqa: E501
    repo_trace._TRACE_FILE = str(tmp_path / "TRACE_FILE_from_test")


# copied from
# https://github.com/pytest-dev/pytest/issues/363#issuecomment-1335631998
@pytest.fixture(scope="session")
def monkeysession():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


@pytest.fixture(autouse=True, scope="session")
def alt_home(tmp_path_factory, monkeysession):
    """Set HOME to a temporary directory, avoiding user's .gitconfig.

    b/302797407

    Modeled after PyPI:pytest-home, but with session scope. Session
    scope is necessary to take effect prior to
    ``test_wrapper.GitCheckoutTestCase.setUpClass``.
    """
    vars = ["HOME"] + platform_utils.isWindows() * ["USERPROFILE"]
    home = tmp_path_factory.mktemp("home")
    for var in vars:
        monkeysession.setenv(var, str(home))
    return home


@pytest.fixture(autouse=True)
def clean_home(alt_home):
    """Ensure HOME is cleaned after each test."""
    yield alt_home
    shutil.rmtree(alt_home)
    alt_home.mkdir()
