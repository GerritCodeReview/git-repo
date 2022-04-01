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
import unittest
import unittest.mock

from subcmds import sync


Options = collections.namedtuple('Options', ['current_branch_only'])


class SyncCommand(unittest.TestCase):
  """Tests for the sync command."""

  def setUp(self):
    self.cmd = sync.Sync()

  def test_get_current_branch_only_cli_absent_superproject_no(self):
    """
    sync._GetCurrentBranchOnly should return None if no command-line flag is
    given and no superproject is requested.
    """
    opt = Options(current_branch_only=None)
    with unittest.mock.patch('git_superproject.UseSuperproject', return_value=False):
      self.assertIsNone(self.cmd._GetCurrentBranchOnly(opt))

  def test_get_current_branch_only_cli_true_superproject_no(self):
    """
    sync._GetCurrentBranchOnly should return True if --currrent-branch is given
    on the command-line and no superproject is requested.
    """
    opt = Options(current_branch_only=True)
    with unittest.mock.patch('git_superproject.UseSuperproject', return_value=False):
      self.assertTrue(self.cmd._GetCurrentBranchOnly(opt))

  def test_get_current_branch_only_cli_false_superproject_no(self):
    """
    sync._GetCurrentBranchOnly should return False if --no-currrent-branch is
    given on the command-line and no superproject is requested.
    """
    opt = Options(current_branch_only=False)
    with unittest.mock.patch('git_superproject.UseSuperproject', return_value=False):
      self.assertFalse(self.cmd._GetCurrentBranchOnly(opt))

  def test_get_current_branch_only_cli_absent_superproject_yes(self):
    """
    sync._GetCurrentBranchOnly should return True if no command-line flag is
    given and a superproject is requested.
    """
    opt = Options(current_branch_only=None)
    with unittest.mock.patch('git_superproject.UseSuperproject', return_value=True):
      self.assertTrue(self.cmd._GetCurrentBranchOnly(opt))

  def test_get_current_branch_only_cli_true_superproject_yes(self):
    """
    sync._GetCurrentBranchOnly should return True if --currrent-branch is given
    on the command-line and no superproject is requested.
    """
    opt = Options(current_branch_only=True)
    with unittest.mock.patch('git_superproject.UseSuperproject', return_value=True):
      self.assertTrue(self.cmd._GetCurrentBranchOnly(opt))

  def test_get_current_branch_only_cli_false_superproject_yes(self):
    """
    sync._GetCurrentBranchOnly should return True if --no-currrent-branch is
    given on the command-line and no superproject is
    requested.
    """
    opt = Options(current_branch_only=False)
    with unittest.mock.patch('git_superproject.UseSuperproject', return_value=True):
      self.assertTrue(self.cmd._GetCurrentBranchOnly(opt))
