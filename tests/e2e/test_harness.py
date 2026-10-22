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

"""Tests for the E2E harness helpers themselves."""

from pathlib import Path
from typing import Mapping

import harness
import pytest


# `ServerRepo.create` uses `git init --initial-branch`.
pytestmark = pytest.mark.skipif(
    harness.git_version() < (2, 28, 0), reason="requires git 2.28+"
)


@pytest.mark.parametrize(
    "key,value",
    [
        ("core.bare", "true"),
        ('url.C:\\src\\#1;"x".insteadOf', 'C:\\dst\\ #2;"y"'),
        ("alias.multi", "a\nb"),
    ],
)
def test_write_config(tmp_path: Path, key: str, value: str) -> None:
    """Subsections & values round-trip through git's config parser."""
    path = tmp_path / "config"
    harness.write_config(path, {key: value})
    got = harness.run_git("config", "--file", str(path), "--get", key)
    assert got == value


@pytest.mark.parametrize(
    "files",
    [
        {"foo/bar": "x", "foo": None},
        {"foo": None, "foo/bar": "x"},
    ],
)
def test_commit_replace_file_with_dir(
    tmp_path: Path, files: Mapping[str, harness.FileContent]
) -> None:
    """Deletions apply before additions regardless of dict order."""
    repo = harness.ServerRepo.create(tmp_path / "repo.git", "unused")
    repo.commit({"foo": "file"})
    repo.commit(files)
    assert repo.git("ls-tree", "-r", "--name-only", "main") == "foo/bar"
