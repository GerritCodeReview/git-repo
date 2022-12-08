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

import os
import tempfile
import unittest

import git_config


def fixture(*paths):
  """Return a path relative to test/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)


class GitConfigReadOnlyTests(unittest.TestCase):
  """Read-only tests of the GitConfig class."""

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

  def test_GetBoolean_undefined(self):
    """Test GetBoolean on key that doesn't exist."""
    self.assertIsNone(self.config.GetBoolean('section.missing'))

  def test_GetBoolean_invalid(self):
    """Test GetBoolean on invalid boolean value."""
    self.assertIsNone(self.config.GetBoolean('section.boolinvalid'))

  def test_GetBoolean_true(self):
    """Test GetBoolean on valid true boolean."""
    self.assertTrue(self.config.GetBoolean('section.booltrue'))

  def test_GetBoolean_false(self):
    """Test GetBoolean on valid false boolean."""
    self.assertFalse(self.config.GetBoolean('section.boolfalse'))

  def test_GetInt_undefined(self):
    """Test GetInt on key that doesn't exist."""
    self.assertIsNone(self.config.GetInt('section.missing'))

  def test_GetInt_invalid(self):
    """Test GetInt on invalid integer value."""
    self.assertIsNone(self.config.GetBoolean('section.intinvalid'))

  def test_GetInt_valid(self):
    """Test GetInt on valid integers."""
    TESTS = (
        ('inthex', 16),
        ('inthexk', 16384),
        ('int', 10),
        ('intk', 10240),
        ('intm', 10485760),
        ('intg', 10737418240),
    )
    for key, value in TESTS:
      self.assertEqual(value, self.config.GetInt('section.%s' % (key,)))


class GitConfigReadWriteTests(unittest.TestCase):
  """Read/write tests of the GitConfig class."""

  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    self.config = self.get_config()

  def get_config(self):
    """Get a new GitConfig instance."""
    return git_config.GitConfig(self.tmpfile.name)

  def test_SetString(self):
    """Test SetString behavior."""
    # Set a value.
    self.assertIsNone(self.config.GetString('foo.bar'))
    self.config.SetString('foo.bar', 'val')
    self.assertEqual('val', self.config.GetString('foo.bar'))

    # Make sure the value was actually written out.
    config = self.get_config()
    self.assertEqual('val', config.GetString('foo.bar'))

    # Update the value.
    self.config.SetString('foo.bar', 'valll')
    self.assertEqual('valll', self.config.GetString('foo.bar'))
    config = self.get_config()
    self.assertEqual('valll', config.GetString('foo.bar'))

    # Delete the value.
    self.config.SetString('foo.bar', None)
    self.assertIsNone(self.config.GetString('foo.bar'))
    config = self.get_config()
    self.assertIsNone(config.GetString('foo.bar'))

  def test_SetBoolean(self):
    """Test SetBoolean behavior."""
    # Set a true value.
    self.assertIsNone(self.config.GetBoolean('foo.bar'))
    for val in (True, 1):
      self.config.SetBoolean('foo.bar', val)
      self.assertTrue(self.config.GetBoolean('foo.bar'))

    # Make sure the value was actually written out.
    config = self.get_config()
    self.assertTrue(config.GetBoolean('foo.bar'))
    self.assertEqual('true', config.GetString('foo.bar'))

    # Set a false value.
    for val in (False, 0):
      self.config.SetBoolean('foo.bar', val)
      self.assertFalse(self.config.GetBoolean('foo.bar'))

    # Make sure the value was actually written out.
    config = self.get_config()
    self.assertFalse(config.GetBoolean('foo.bar'))
    self.assertEqual('false', config.GetString('foo.bar'))

    # Delete the value.
    self.config.SetBoolean('foo.bar', None)
    self.assertIsNone(self.config.GetBoolean('foo.bar'))
    config = self.get_config()
    self.assertIsNone(config.GetBoolean('foo.bar'))

  def test_GetSyncAnalysisStateData(self):
    """Test config entries with a sync state analysis data."""
    superproject_logging_data = {}
    superproject_logging_data['test'] = False
    options = type('options', (object,), {})()
    options.verbose = 'true'
    options.mp_update = 'false'
    TESTS = (
        ('superproject.test', 'false'),
        ('options.verbose', 'true'),
        ('options.mpupdate', 'false'),
        ('main.version', '1'),
    )
    self.config.UpdateSyncAnalysisState(options, superproject_logging_data)
    sync_data = self.config.GetSyncAnalysisStateData()
    for key, value in TESTS:
      self.assertEqual(sync_data[f'{git_config.SYNC_STATE_PREFIX}{key}'], value)
    self.assertTrue(sync_data[f'{git_config.SYNC_STATE_PREFIX}main.synctime'])
