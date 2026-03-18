# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the editor.py module."""

import pytest

from editor import Editor


@pytest.fixture(autouse=True)
def reset_editor() -> None:
    """Take care of resetting Editor state across tests."""
    Editor._editor = None
    yield
    Editor._editor = None


def test_basic() -> None:
    """Basic checking of _GetEditor."""
    Editor._editor = ":"
    assert Editor._GetEditor() == ":"


def test_no_editor() -> None:
    """Check behavior when no editor is available."""
    Editor._editor = ":"
    assert Editor.EditString("foo") == "foo"


def test_cat_editor() -> None:
    """Check behavior when editor is `cat`."""
    Editor._editor = "cat"
    assert Editor.EditString("foo") == "foo"
