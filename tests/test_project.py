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

import error
import git_config
import platform_utils
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
    platform_utils.rmtree(tempdir)


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
    self.work_git = project.Project._GitGetByExec(
        self, bare=False, gitdir=self.gitdir)
    self.bare_git = project.Project._GitGetByExec(
        self, bare=True, gitdir=self.gitdir)
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


class CopyLinkTestCase(unittest.TestCase):
  """TestCase for stub repo client checkouts.

  It'll have a layout like:
    tempdir/          # self.tempdir
      checkout/       # self.topdir
        git-project/  # self.worktree

  Attributes:
    tempdir: A dedicated temporary directory.
    worktree: The top of the repo client checkout.
    topdir: The top of a project checkout.
  """

  def setUp(self):
    self.tempdir = tempfile.mkdtemp(prefix='repo_tests')
    self.topdir = os.path.join(self.tempdir, 'checkout')
    self.worktree = os.path.join(self.topdir, 'git-project')
    os.makedirs(self.topdir)
    os.makedirs(self.worktree)

  def tearDown(self):
    shutil.rmtree(self.tempdir, ignore_errors=True)

  @staticmethod
  def touch(path):
    with open(path, 'w'):
      pass

  def assertExists(self, path, msg=None):
    """Make sure |path| exists."""
    if os.path.exists(path):
      return

    if msg is None:
      msg = ['path is missing: %s' % path]
      while path != '/':
        path = os.path.dirname(path)
        if not path:
          # If we're given something like "foo", abort once we get to "".
          break
        result = os.path.exists(path)
        msg.append('\tos.path.exists(%s): %s' % (path, result))
        if result:
          msg.append('\tcontents: %r' % os.listdir(path))
          break
      msg = '\n'.join(msg)

    raise self.failureException(msg)


class CopyFile(CopyLinkTestCase):
  """Check _CopyFile handling."""

  def CopyFile(self, src, dest):
    return project._CopyFile(self.worktree, src, self.topdir, dest)

  def test_basic(self):
    """Basic test of copying a file from a project to the toplevel."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    cf = self.CopyFile('foo.txt', 'foo')
    cf._Copy()
    self.assertExists(os.path.join(self.topdir, 'foo'))

  def test_src_subdir(self):
    """Copy a file from a subdir of a project."""
    src = os.path.join(self.worktree, 'bar', 'foo.txt')
    os.makedirs(os.path.dirname(src))
    self.touch(src)
    cf = self.CopyFile('bar/foo.txt', 'new.txt')
    cf._Copy()
    self.assertExists(os.path.join(self.topdir, 'new.txt'))

  def test_dest_subdir(self):
    """Copy a file to a subdir of a checkout."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    cf = self.CopyFile('foo.txt', 'sub/dir/new.txt')
    self.assertFalse(os.path.exists(os.path.join(self.topdir, 'sub')))
    cf._Copy()
    self.assertExists(os.path.join(self.topdir, 'sub', 'dir', 'new.txt'))

  def test_update(self):
    """Make sure changed files get copied again."""
    src = os.path.join(self.worktree, 'foo.txt')
    dest = os.path.join(self.topdir, 'bar')
    with open(src, 'w') as f:
      f.write('1st')
    cf = self.CopyFile('foo.txt', 'bar')
    cf._Copy()
    self.assertExists(dest)
    with open(dest) as f:
      self.assertEqual(f.read(), '1st')

    with open(src, 'w') as f:
      f.write('2nd!')
    cf._Copy()
    with open(dest) as f:
      self.assertEqual(f.read(), '2nd!')

  def test_src_block_symlink(self):
    """Do not allow reading from a symlinked path."""
    src = os.path.join(self.worktree, 'foo.txt')
    sym = os.path.join(self.worktree, 'sym')
    self.touch(src)
    platform_utils.symlink('foo.txt', sym)
    self.assertExists(sym)
    cf = self.CopyFile('sym', 'foo')
    self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

  def test_src_block_symlink_traversal(self):
    """Do not allow reading through a symlink dir."""
    realfile = os.path.join(self.tempdir, 'file.txt')
    self.touch(realfile)
    src = os.path.join(self.worktree, 'bar', 'file.txt')
    platform_utils.symlink(self.tempdir, os.path.join(self.worktree, 'bar'))
    self.assertExists(src)
    cf = self.CopyFile('bar/file.txt', 'foo')
    self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

  def test_src_block_copy_from_dir(self):
    """Do not allow copying from a directory."""
    src = os.path.join(self.worktree, 'dir')
    os.makedirs(src)
    cf = self.CopyFile('dir', 'foo')
    self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

  def test_dest_block_symlink(self):
    """Do not allow writing to a symlink."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    platform_utils.symlink('dest', os.path.join(self.topdir, 'sym'))
    cf = self.CopyFile('foo.txt', 'sym')
    self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

  def test_dest_block_symlink_traversal(self):
    """Do not allow writing through a symlink dir."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    platform_utils.symlink(tempfile.gettempdir(),
                           os.path.join(self.topdir, 'sym'))
    cf = self.CopyFile('foo.txt', 'sym/foo.txt')
    self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

  def test_src_block_copy_to_dir(self):
    """Do not allow copying to a directory."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    os.makedirs(os.path.join(self.topdir, 'dir'))
    cf = self.CopyFile('foo.txt', 'dir')
    self.assertRaises(error.ManifestInvalidPathError, cf._Copy)


class LinkFile(CopyLinkTestCase):
  """Check _LinkFile handling."""

  def LinkFile(self, src, dest):
    return project._LinkFile(self.worktree, src, self.topdir, dest)

  def test_basic(self):
    """Basic test of linking a file from a project into the toplevel."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    lf = self.LinkFile('foo.txt', 'foo')
    lf._Link()
    dest = os.path.join(self.topdir, 'foo')
    self.assertExists(dest)
    self.assertTrue(os.path.islink(dest))
    self.assertEqual(os.path.join('git-project', 'foo.txt'), os.readlink(dest))

  def test_src_subdir(self):
    """Link to a file in a subdir of a project."""
    src = os.path.join(self.worktree, 'bar', 'foo.txt')
    os.makedirs(os.path.dirname(src))
    self.touch(src)
    lf = self.LinkFile('bar/foo.txt', 'foo')
    lf._Link()
    self.assertExists(os.path.join(self.topdir, 'foo'))

  def test_src_self(self):
    """Link to the project itself."""
    dest = os.path.join(self.topdir, 'foo', 'bar')
    lf = self.LinkFile('.', 'foo/bar')
    lf._Link()
    self.assertExists(dest)
    self.assertEqual(os.path.join('..', 'git-project'), os.readlink(dest))

  def test_dest_subdir(self):
    """Link a file to a subdir of a checkout."""
    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    lf = self.LinkFile('foo.txt', 'sub/dir/foo/bar')
    self.assertFalse(os.path.exists(os.path.join(self.topdir, 'sub')))
    lf._Link()
    self.assertExists(os.path.join(self.topdir, 'sub', 'dir', 'foo', 'bar'))

  def test_src_block_relative(self):
    """Do not allow relative symlinks."""
    BAD_SOURCES = (
        './',
        '..',
        '../',
        'foo/.',
        'foo/./bar',
        'foo/..',
        'foo/../foo',
    )
    for src in BAD_SOURCES:
      lf = self.LinkFile(src, 'foo')
      self.assertRaises(error.ManifestInvalidPathError, lf._Link)

  def test_update(self):
    """Make sure changed targets get updated."""
    dest = os.path.join(self.topdir, 'sym')

    src = os.path.join(self.worktree, 'foo.txt')
    self.touch(src)
    lf = self.LinkFile('foo.txt', 'sym')
    lf._Link()
    self.assertEqual(os.path.join('git-project', 'foo.txt'), os.readlink(dest))

    # Point the symlink somewhere else.
    os.unlink(dest)
    platform_utils.symlink(self.tempdir, dest)
    lf._Link()
    self.assertEqual(os.path.join('git-project', 'foo.txt'), os.readlink(dest))
