# -*- coding:utf-8 -*-
#
# Copyright (C) 2015 The Android Open Source Project
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

"""Unittests for the wrapper.py module."""

from __future__ import print_function

import os
import re
import unittest

from pyversion import is_python3
import wrapper


if is_python3():
  from unittest import mock
  from io import StringIO
else:
  import mock
  from StringIO import StringIO


def fixture(*paths):
  """Return a path relative to tests/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)


class RepoWrapperTestCase(unittest.TestCase):
  """TestCase for the wrapper module."""

  def setUp(self):
    """Load the wrapper module every time."""
    wrapper._wrapper_module = None
    self.wrapper = wrapper.Wrapper()

    if not is_python3():
      self.assertRegex = self.assertRegexpMatches


class RepoWrapperUnitTest(RepoWrapperTestCase):
  """Tests helper functions in the repo wrapper
  """

  def test_version(self):
    """Make sure _Version works."""
    with self.assertRaises(SystemExit) as e:
      with mock.patch('sys.stdout', new_callable=StringIO) as stdout:
        with mock.patch('sys.stderr', new_callable=StringIO) as stderr:
          self.wrapper._Version()
    self.assertEqual(0, e.exception.code)
    self.assertEqual('', stderr.getvalue())
    self.assertIn('repo launcher version', stdout.getvalue())

  def test_init_parser(self):
    """Make sure 'init' GetParser works."""
    parser = self.wrapper.GetParser(gitc_init=False)
    opts, args = parser.parse_args([])
    self.assertEqual([], args)
    self.assertIsNone(opts.manifest_url)

  def test_gitc_init_parser(self):
    """Make sure 'gitc-init' GetParser works."""
    parser = self.wrapper.GetParser(gitc_init=True)
    opts, args = parser.parse_args([])
    self.assertEqual([], args)
    self.assertIsNone(opts.manifest_file)

  def test_get_gitc_manifest_dir_no_gitc(self):
    """
    Test reading a missing gitc config file
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('missing_gitc_config')
    val = self.wrapper.get_gitc_manifest_dir()
    self.assertEqual(val, '')

  def test_get_gitc_manifest_dir(self):
    """
    Test reading the gitc config file and parsing the directory
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('gitc_config')
    val = self.wrapper.get_gitc_manifest_dir()
    self.assertEqual(val, '/test/usr/local/google/gitc')

  def test_gitc_parse_clientdir_no_gitc(self):
    """
    Test parsing the gitc clientdir without gitc running
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('missing_gitc_config')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/something'), None)
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test'), 'test')

  def test_gitc_parse_clientdir(self):
    """
    Test parsing the gitc clientdir
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('gitc_config')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/something'), None)
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test/'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test/extra'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/test'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/test/'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/test/extra'),
                     'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/'), None)
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/'), None)


class SetGitTrace2ParentSid(RepoWrapperTestCase):
  """Check SetGitTrace2ParentSid behavior."""

  KEY = 'GIT_TRACE2_PARENT_SID'
  VALID_FORMAT = re.compile(r'^repo-[0-9]{8}T[0-9]{6}Z-P[0-9a-f]{8}$')

  def test_first_set(self):
    """Test env var not yet set."""
    env = {}
    self.wrapper.SetGitTrace2ParentSid(env)
    self.assertIn(self.KEY, env)
    value = env[self.KEY]
    self.assertRegex(value, self.VALID_FORMAT)

  def test_append(self):
    """Test env var is appended."""
    env = {self.KEY: 'pfx'}
    self.wrapper.SetGitTrace2ParentSid(env)
    self.assertIn(self.KEY, env)
    value = env[self.KEY]
    self.assertTrue(value.startswith('pfx/'))
    self.assertRegex(value[4:], self.VALID_FORMAT)

  def test_global_context(self):
    """Check os.environ gets updated by default."""
    os.environ.pop(self.KEY, None)
    self.wrapper.SetGitTrace2ParentSid()
    self.assertIn(self.KEY, os.environ)
    value = os.environ[self.KEY]
    self.assertRegex(value, self.VALID_FORMAT)


if __name__ == '__main__':
  unittest.main()
