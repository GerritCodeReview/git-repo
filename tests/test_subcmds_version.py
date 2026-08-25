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

"""Unittests for subcmds/version.py."""

from unittest import mock

import pytest

from subcmds import version


def test_repo_version_uses_one_pretty_format_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = mock.MagicMock()
    project.bare_git.log.return_value = "v2.0-1-g12345678\nTue, 25 Aug\n"
    monkeypatch.setattr(version, "git_require", lambda _version: True)

    result = version.Version._RepoVersion(project)

    assert result == ("v2.0-1-g12345678", "Tue, 25 Aug")
    project.bare_git.log.assert_called_once_with(
        "-1", "--format=%(describe)%n%cD", "HEAD"
    )
    project.bare_git.describe.assert_not_called()


def test_repo_version_keeps_old_git_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = mock.MagicMock()
    project.bare_git.describe.return_value = "v2.0"
    project.bare_git.log.return_value = "Tue, 25 Aug"
    monkeypatch.setattr(version, "git_require", lambda _version: False)

    result = version.Version._RepoVersion(project)

    assert result == ("v2.0", "Tue, 25 Aug")
    project.bare_git.describe.assert_called_once_with("HEAD")
    project.bare_git.log.assert_called_once_with("-1", "--format=%cD", "HEAD")
