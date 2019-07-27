# -*- coding:utf-8 -*-
#
# Copyright (C) 2009 The Android Open Source Project
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

"""Unittests for the git_config.py module."""

from __future__ import print_function

import os
import unittest

import git_config

def fixture(*paths):
  """Return a path relative to test/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)

class GitConfigUnitTest(unittest.TestCase):
  """Tests the GitConfig class.
  """
  def setUp(self):
    """Create a GitConfig object using the test.gitconfig fixture.
    """
    config_fixture = fixture('test.gitconfig')
    self.config = git_config.GitConfig(config_fixture)

  def test_GetString_with_empty_config_values(self):
    """
    Test config entries with no value.

    [section]
        empty

    """
    val = self.config.GetString('section.empty')
    self.assertEqual(val, None)

  def test_GetString_with_true_value(self):
    """
    Test config entries with a string value.

    [section]
        nonempty = true

    """
    val = self.config.GetString('section.nonempty')
    self.assertEqual(val, 'true')

  def test_GetString_from_missing_file(self):
    """
    Test missing config file
    """
    config_fixture = fixture('not.present.gitconfig')
    config = git_config.GitConfig(config_fixture)
    val = config.GetString('empty')
    self.assertEqual(val, None)

if __name__ == '__main__':
  unittest.main()
