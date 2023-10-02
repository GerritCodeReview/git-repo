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

import pytest
import pytest_home.fixtures

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
def session_tmp_homedir(tmp_path_factory, monkeysession):
    """Set HOME to a temporary directory, avoiding user's .gitconfig.

    b/302797407

    Set home at session scope to take effect prior to
    ``test_wrapper.GitCheckoutTestCase.setUpClass``.
    """
    return pytest_home.set(monkeysession, tmp_path_factory.mktemp("home"))


pytestmark = pytest.mark.usefixtures("alt_home")
"""Set HOME to a temporary directory as a fixture.

Ensures that state doesn't accumulate in $HOME across tests.

Note that in conjunction with session_tmp_homedir, the HOME
dir is patched twice, once at session scope, and then again at
the function scope.
"""
