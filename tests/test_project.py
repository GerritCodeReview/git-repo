# -*- coding:utf-8 -*-
#
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

"""Unittests for the project.py module."""

from __future__ import print_function

import contextlib
import os
import shutil
import subprocess
import tempfile
import unittest

import git_config
import project


@contextlib.contextmanager
def TempGitTree():
  """Create a new empty git checkout for testing."""
  # TODO(vapier): Convert this to tempfile.TemporaryDirectory once we drop
  # Python 2 support entirely.
  try:
    tempdir = tempfile.mkdtemp(prefix='repo-tests')
    subprocess.check_call(['git', 'init'], cwd=tempdir)
    yield tempdir
  finally:
    shutil.rmtree(tempdir)


class RepoHookShebang(unittest.TestCase):
  """Check shebang parsing in RepoHook."""

  def test_no_shebang(self):
    """Lines w/out shebangs should be rejected."""
    DATA = (
        '',
        '# -*- coding:utf-8 -*-\n',
        '#\n# foo\n',
        '# Bad shebang in script\n#!/foo\n'
    )
    for data in DATA:
      self.assertIsNone(project.RepoHook._ExtractInterpFromShebang(data))

  def test_direct_interp(self):
    """Lines whose shebang points directly to the interpreter."""
    DATA = (
        ('#!/foo', '/foo'),
        ('#! /foo', '/foo'),
        ('#!/bin/foo ', '/bin/foo'),
        ('#! /usr/foo ', '/usr/foo'),
        ('#! /usr/foo -args', '/usr/foo'),
    )
    for shebang, interp in DATA:
      self.assertEqual(project.RepoHook._ExtractInterpFromShebang(shebang),
                       interp)

  def test_env_interp(self):
    """Lines whose shebang launches through `env`."""
    DATA = (
        ('#!/usr/bin/env foo', 'foo'),
        ('#!/bin/env foo', 'foo'),
        ('#! /bin/env /bin/foo ', '/bin/foo'),
    )
    for shebang, interp in DATA:
      self.assertEqual(project.RepoHook._ExtractInterpFromShebang(shebang),
                       interp)


class FakeProject(object):
  """A fake for Project for basic functionality."""

  def __init__(self, worktree):
    self.worktree = worktree
    self.gitdir = os.path.join(worktree, '.git')
    self.name = 'fakeproject'
    self.work_git = project.Project._GitGetByExec(self, bare=False, gitdir=self.gitdir)
    self.bare_git = project.Project._GitGetByExec(self, bare=True, gitdir=self.gitdir)
    self.config = git_config.GitConfig.ForRepository(gitdir=self.gitdir)


class ReviewableBranchTests(unittest.TestCase):
  """Check ReviewableBranch behavior."""

  def test_smoke(self):
    """A quick run through everything."""
    with TempGitTree() as tempdir:
      fakeproj = FakeProject(tempdir)

      # Generate some commits.
      with open(os.path.join(tempdir, 'readme'), 'w') as fp:
        fp.write('txt')
      fakeproj.work_git.add('readme')
      fakeproj.work_git.commit('-mAdd file')
      fakeproj.work_git.checkout('-b', 'work')
      fakeproj.work_git.rm('-f', 'readme')
      fakeproj.work_git.commit('-mDel file')

      # Start off with the normal details.
      rb = project.ReviewableBranch(
          fakeproj, fakeproj.config.GetBranch('work'), 'master')
      self.assertEqual('work', rb.name)
      self.assertEqual(1, len(rb.commits))
      self.assertIn('Del file', rb.commits[0])
      d = rb.unabbrev_commits
      self.assertEqual(1, len(d))
      short, long = next(iter(d.items()))
      self.assertTrue(long.startswith(short))
      self.assertTrue(rb.base_exists)
      # Hard to assert anything useful about this.
      self.assertTrue(rb.date)

      # Now delete the tracking branch!
      fakeproj.work_git.branch('-D', 'master')
      rb = project.ReviewableBranch(
          fakeproj, fakeproj.config.GetBranch('work'), 'master')
      self.assertEqual(0, len(rb.commits))
      self.assertFalse(rb.base_exists)
      # Hard to assert anything useful about this.
      self.assertTrue(rb.date)
