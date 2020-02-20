# -*- coding:utf-8 -*-
#
# Copyright 2019 The Android Open Source Project
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

"""Unittests for the git_command.py module."""

from __future__ import print_function

import re
import unittest

try:
  from unittest import mock
except ImportError:
  import mock

import git_command
import wrapper


class GitCallUnitTest(unittest.TestCase):
  """Tests the _GitCall class (via git_command.git)."""

  def test_version_tuple(self):
    """Check git.version_tuple() handling."""
    ver = git_command.git.version_tuple()
    self.assertIsNotNone(ver)

    # We don't dive too deep into the values here to avoid having to update
    # whenever git versions change.  We do check relative to this min version
    # as this is what `repo` itself requires via MIN_GIT_VERSION.
    MIN_GIT_VERSION = (2, 10, 2)
    self.assertTrue(isinstance(ver.major, int))
    self.assertTrue(isinstance(ver.minor, int))
    self.assertTrue(isinstance(ver.micro, int))

    self.assertGreater(ver.major, MIN_GIT_VERSION[0] - 1)
    self.assertGreaterEqual(ver.micro, 0)
    self.assertGreaterEqual(ver.major, 0)

    self.assertGreaterEqual(ver, MIN_GIT_VERSION)
    self.assertLess(ver, (9999, 9999, 9999))

    self.assertNotEqual('', ver.full)


class UserAgentUnitTest(unittest.TestCase):
  """Tests the UserAgent function."""

  def test_smoke_os(self):
    """Make sure UA OS setting returns something useful."""
    os_name = git_command.user_agent.os
    # We can't dive too deep because of OS/tool differences, but we can check
    # the general form.
    m = re.match(r'^[^ ]+$', os_name)
    self.assertIsNotNone(m)

  def test_smoke_repo(self):
    """Make sure repo UA returns something useful."""
    ua = git_command.user_agent.repo
    # We can't dive too deep because of OS/tool differences, but we can check
    # the general form.
    m = re.match(r'^git-repo/[^ ]+ ([^ ]+) git/[^ ]+ Python/[0-9.]+', ua)
    self.assertIsNotNone(m)

  def test_smoke_git(self):
    """Make sure git UA returns something useful."""
    ua = git_command.user_agent.git
    # We can't dive too deep because of OS/tool differences, but we can check
    # the general form.
    m = re.match(r'^git/[^ ]+ ([^ ]+) git-repo/[^ ]+', ua)
    self.assertIsNotNone(m)


class GitRequireTests(unittest.TestCase):
  """Test the git_require helper."""

  def setUp(self):
    ver = wrapper.GitVersion(1, 2, 3, 4)
    mock.patch.object(git_command.git, 'version_tuple', return_value=ver).start()

  def tearDown(self):
    mock.patch.stopall()

  def test_older_nonfatal(self):
    """Test non-fatal require calls with old versions."""
    self.assertFalse(git_command.git_require((2,)))
    self.assertFalse(git_command.git_require((1, 3)))
    self.assertFalse(git_command.git_require((1, 2, 4)))
    self.assertFalse(git_command.git_require((1, 2, 3, 5)))

  def test_newer_nonfatal(self):
    """Test non-fatal require calls with newer versions."""
    self.assertTrue(git_command.git_require((0,)))
    self.assertTrue(git_command.git_require((1, 0)))
    self.assertTrue(git_command.git_require((1, 2, 0)))
    self.assertTrue(git_command.git_require((1, 2, 3, 0)))

  def test_equal_nonfatal(self):
    """Test require calls with equal values."""
    self.assertTrue(git_command.git_require((1, 2, 3, 4), fail=False))
    self.assertTrue(git_command.git_require((1, 2, 3, 4), fail=True))

  def test_older_fatal(self):
    """Test fatal require calls with old versions."""
    with self.assertRaises(SystemExit) as e:
      git_command.git_require((2,), fail=True)
      self.assertNotEqual(0, e.code)

  def test_older_fatal_msg(self):
    """Test fatal require calls with old versions and message."""
    with self.assertRaises(SystemExit) as e:
      git_command.git_require((2,), fail=True, msg='so sad')
      self.assertNotEqual(0, e.code)
