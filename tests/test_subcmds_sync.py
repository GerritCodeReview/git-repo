# Copyright (C) 2020 The Android Open Source Project
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

"""Unittests for the subcmds/sync.py module."""

import collections
import unittest.mock

import pytest

from subcmds import sync


Options = collections.namedtuple('Options', ['current_branch_only'])


@pytest.mark.parametrize(
  'use_superproject, get_current_branch_cli, result',
  [
    (True, True, True),
    (True, False, True),
    (True, None, True),
    (False, True, True),
    (False, False, False),
    (False, None, None),
  ]
)
def test_get_current_branch_only(use_superproject, get_current_branch_cli, result):
  """
  sync._GetCurrentBranchOnly should return True if a superproject is requested,
  and otherwise the value of the current_branch_only option.
  """
  opt = Options(current_branch_only=get_current_branch_cli)
  with unittest.mock.patch('git_superproject.UseSuperproject', return_value=use_superproject):
    assert sync.Sync()._GetCurrentBranchOnly(opt) == result
