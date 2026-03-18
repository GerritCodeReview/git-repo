# Copyright (C) 2021 The Android Open Source Project
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

"""Unittests for the platform_utils.py module."""

from pathlib import Path

import pytest

import platform_utils


def test_remove_missing_ok(tmp_path: Path) -> None:
    """Check missing_ok handling."""
    path = tmp_path / "test"

    # Should not fail.
    platform_utils.remove(path, missing_ok=True)

    # Should fail.
    with pytest.raises(OSError):
        platform_utils.remove(path)
    with pytest.raises(OSError):
        platform_utils.remove(path, missing_ok=False)

    # Should not fail if it exists.
    path.touch()
    platform_utils.remove(path, missing_ok=True)
    assert not path.exists()

    path.touch()
    platform_utils.remove(path)
    assert not path.exists()

    path.touch()
    platform_utils.remove(path, missing_ok=False)
    assert not path.exists()
