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

"""Tests for the release/update-manpages wrapper."""

import runpy
import sys
from types import ModuleType
from unittest import mock

import pytest
import utils_for_test


UPDATE_MANPAGES_SCRIPT = (
    utils_for_test.THIS_DIR.parent / "release" / "update-manpages"
)


def test_wrapper_does_not_run_main_for_multiprocessing_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not rerun main when multiprocessing loads the wrapper."""
    fake_update_manpages = ModuleType("update_manpages")
    main_mock = mock.Mock(return_value=0)
    fake_update_manpages.main = main_mock
    exit_mock = mock.Mock()

    monkeypatch.setitem(sys.modules, "update_manpages", fake_update_manpages)
    monkeypatch.setattr(sys, "exit", exit_mock)

    runpy.run_path(
        str(UPDATE_MANPAGES_SCRIPT),
        run_name="__mp_main__",
    )

    main_mock.assert_not_called()
    exit_mock.assert_not_called()
