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

"""Unittests for the subcmds/sync.py module."""

from unittest import mock

import pytest

from subcmds import sync


@pytest.mark.parametrize(
  'use_superproject, cli_args, result',
  [
    (True, ['--current-branch'], True),
    (True, ['--no-current-branch'], True),
    (True, [], True),
    (False, ['--current-branch'], True),
    (False, ['--no-current-branch'], False),
    (False, [], None),
  ]
)
def test_get_current_branch_only(use_superproject, cli_args, result):
  """Test Sync._GetCurrentBranchOnly logic.

  Sync._GetCurrentBranchOnly should return True if a superproject is requested,
  and otherwise the value of the current_branch_only option.
  """
  cmd = sync.Sync()
  opts, _ = cmd.OptionParser.parse_args(cli_args)

  with mock.patch('git_superproject.UseSuperproject', return_value=use_superproject):
    assert cmd._GetCurrentBranchOnly(opts, cmd.manifest) == result
