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

import unittest
from unittest import mock

import pytest

from subcmds import sync


@pytest.mark.parametrize('use_superproject, cli_args, result', [
    (True, ['--current-branch'], True),
    (True, ['--no-current-branch'], True),
    (True, [], True),
    (False, ['--current-branch'], True),
    (False, ['--no-current-branch'], False),
    (False, [], None),
])
def test_get_current_branch_only(use_superproject, cli_args, result):
  """Test Sync._GetCurrentBranchOnly logic.

  Sync._GetCurrentBranchOnly should return True if a superproject is requested,
  and otherwise the value of the current_branch_only option.
  """
  cmd = sync.Sync()
  opts, _ = cmd.OptionParser.parse_args(cli_args)

  with mock.patch('git_superproject.UseSuperproject',
                  return_value=use_superproject):
    assert cmd._GetCurrentBranchOnly(opts, cmd.manifest) == result


class GetPreciousObjectsState(unittest.TestCase):
  """Tests for _GetPreciousObjectsState."""

  def setUp(self):
    """Common setup."""
    self.cmd = sync.Sync()
    self.project = p = mock.MagicMock(use_git_worktrees=False,
                                      UseAlternates=False)
    p.manifest.GetProjectsWithName.return_value = [p]

    self.opt = mock.Mock(spec_set=['this_manifest_only'])
    self.opt.this_manifest_only = False

  def test_worktrees(self):
    """False for worktrees."""
    self.project.use_git_worktrees = True
    self.assertFalse(self.cmd._GetPreciousObjectsState(self.project, self.opt))

  def test_not_shared(self):
    """Singleton project."""
    self.assertFalse(self.cmd._GetPreciousObjectsState(self.project, self.opt))

  def test_shared(self):
    """Shared project."""
    self.project.manifest.GetProjectsWithName.return_value = [
        self.project, self.project
    ]
    self.assertTrue(self.cmd._GetPreciousObjectsState(self.project, self.opt))

  def test_shared_with_alternates(self):
    """Shared project, with alternates."""
    self.project.manifest.GetProjectsWithName.return_value = [
        self.project, self.project
    ]
    self.project.UseAlternates = True
    self.assertFalse(self.cmd._GetPreciousObjectsState(self.project, self.opt))

  def test_not_found(self):
    """Project not found in manifest."""
    self.project.manifest.GetProjectsWithName.return_value = []
    self.assertFalse(self.cmd._GetPreciousObjectsState(self.project, self.opt))
