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

import os
import unittest
from unittest import mock

import pytest

import command
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


# Used to patch os.cpu_count() for reliable results.
OS_CPU_COUNT = 24

@pytest.mark.parametrize('argv, jobs_manifest, jobs, jobs_net, jobs_check', [
  # No user or manifest settings.
  ([], None, OS_CPU_COUNT, 1, command.DEFAULT_LOCAL_JOBS),
  # No user settings, so manifest settings control.
  ([], 3, 3, 3, 3),
  # User settings, but no manifest.
  (['--jobs=4'], None, 4, 4, 4),
  (['--jobs=4', '--jobs-network=5'], None, 4, 5, 4),
  (['--jobs=4', '--jobs-checkout=6'], None, 4, 4, 6),
  (['--jobs=4', '--jobs-network=5', '--jobs-checkout=6'], None, 4, 5, 6),
  (['--jobs-network=5'], None, OS_CPU_COUNT, 5, command.DEFAULT_LOCAL_JOBS),
  (['--jobs-checkout=6'], None, OS_CPU_COUNT, 1, 6),
  (['--jobs-network=5', '--jobs-checkout=6'], None, OS_CPU_COUNT, 5, 6),
  # User settings with manifest settings.
  (['--jobs=4'], 3, 4, 4, 4),
  (['--jobs=4', '--jobs-network=5'], 3, 4, 5, 4),
  (['--jobs=4', '--jobs-checkout=6'], 3, 4, 4, 6),
  (['--jobs=4', '--jobs-network=5', '--jobs-checkout=6'], 3, 4, 5, 6),
  (['--jobs-network=5'], 3, 3, 5, 3),
  (['--jobs-checkout=6'], 3, 3, 3, 6),
  (['--jobs-network=5', '--jobs-checkout=6'], 3, 3, 5, 6),
  # Settings that exceed rlimits get capped.
  (['--jobs=1000000'], None, 83, 83, 83),
  ([], 1000000, 83, 83, 83),
])
def test_cli_jobs(argv, jobs_manifest, jobs, jobs_net, jobs_check):
  """Tests --jobs option behavior."""
  mp = mock.MagicMock()
  mp.manifest.default.sync_j = jobs_manifest

  cmd = sync.Sync()
  opts, args = cmd.OptionParser.parse_args(argv)
  cmd.ValidateOptions(opts, args)

  with mock.patch.object(sync, '_rlimit_nofile', return_value=(256, 256)):
    with mock.patch.object(os, 'cpu_count', return_value=OS_CPU_COUNT):
      cmd._ValidateOptionsWithManifest(opts, mp)
      assert opts.jobs == jobs
      assert opts.jobs_network == jobs_net
      assert opts.jobs_checkout == jobs_check


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
