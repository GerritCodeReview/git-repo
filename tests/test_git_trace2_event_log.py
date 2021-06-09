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

"""Unittests for the git_trace2_event_log.py module."""

import json
import os
import tempfile
import unittest
from unittest import mock

import git_trace2_event_log


class EventLogTestCase(unittest.TestCase):
  """TestCase for the EventLog module."""

  PARENT_SID_KEY = 'GIT_TRACE2_PARENT_SID'
  PARENT_SID_VALUE = 'parent_sid'
  SELF_SID_REGEX = r'repo-\d+T\d+Z-.*'
  FULL_SID_REGEX = r'^%s/%s' % (PARENT_SID_VALUE, SELF_SID_REGEX)

  def setUp(self):
    """Load the event_log module every time."""
    self._event_log_module = None
    # By default we initialize with the expected case where
    # repo launches us (so GIT_TRACE2_PARENT_SID is set).
    env = {
        self.PARENT_SID_KEY: self.PARENT_SID_VALUE,
    }
    self._event_log_module = git_trace2_event_log.EventLog(env=env)
    self._log_data = None

  def verifyCommonKeys(self, log_entry, expected_event_name, full_sid=True):
    """Helper function to verify common event log keys."""
    self.assertIn('event', log_entry)
    self.assertIn('sid', log_entry)
    self.assertIn('thread', log_entry)
    self.assertIn('time', log_entry)

    # Do basic data format validation.
    self.assertEqual(expected_event_name, log_entry['event'])
    if full_sid:
      self.assertRegex(log_entry['sid'], self.FULL_SID_REGEX)
    else:
      self.assertRegex(log_entry['sid'], self.SELF_SID_REGEX)
    self.assertRegex(log_entry['time'], r'^\d+-\d+-\d+T\d+:\d+:\d+\.\d+Z$')

  def readLog(self, log_path):
    """Helper function to read log data into a list."""
    log_data = []
    with open(log_path, mode='rb') as f:
      for line in f:
        log_data.append(json.loads(line))
    return log_data

  def test_initial_state_with_parent_sid(self):
    """Test initial state when 'GIT_TRACE2_PARENT_SID' is set by parent."""
    self.assertRegex(self._event_log_module.full_sid, self.FULL_SID_REGEX)

  def test_initial_state_no_parent_sid(self):
    """Test initial state when 'GIT_TRACE2_PARENT_SID' is not set."""
    # Setup an empty environment dict (no parent sid).
    self._event_log_module = git_trace2_event_log.EventLog(env={})
    self.assertRegex(self._event_log_module.full_sid, self.SELF_SID_REGEX)

  def test_version_event(self):
    """Test 'version' event data is valid.

    Verify that the 'version' event is written even when no other
    events are addded.

    Expected event log:
    <version event>
    """
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    # A log with no added events should only have the version entry.
    self.assertEqual(len(self._log_data), 1)
    version_event = self._log_data[0]
    self.verifyCommonKeys(version_event, expected_event_name='version')
    # Check for 'version' event specific fields.
    self.assertIn('evt', version_event)
    self.assertIn('exe', version_event)
    # Verify "evt" version field is a string.
    self.assertIsInstance(version_event['evt'], str)

  def test_start_event(self):
    """Test and validate 'start' event data is valid.

    Expected event log:
    <version event>
    <start event>
    """
    self._event_log_module.StartEvent()
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 2)
    start_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(start_event, expected_event_name='start')
    # Check for 'start' event specific fields.
    self.assertIn('argv', start_event)
    self.assertTrue(isinstance(start_event['argv'], list))

  def test_exit_event_result_none(self):
    """Test 'exit' event data is valid when result is None.

    We expect None result to be converted to 0 in the exit event data.

    Expected event log:
    <version event>
    <exit event>
    """
    self._event_log_module.ExitEvent(None)
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 2)
    exit_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(exit_event, expected_event_name='exit')
    # Check for 'exit' event specific fields.
    self.assertIn('code', exit_event)
    # 'None' result should convert to 0 (successful) return code.
    self.assertEqual(exit_event['code'], 0)

  def test_exit_event_result_integer(self):
    """Test 'exit' event data is valid when result is an integer.

    Expected event log:
    <version event>
    <exit event>
    """
    self._event_log_module.ExitEvent(2)
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 2)
    exit_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(exit_event, expected_event_name='exit')
    # Check for 'exit' event specific fields.
    self.assertIn('code', exit_event)
    self.assertEqual(exit_event['code'], 2)

  def test_command_event(self):
    """Test and validate 'command' event data is valid.

    Expected event log:
    <version event>
    <command event>
    """
    name = 'repo'
    subcommands = ['init' 'this']
    self._event_log_module.CommandEvent(name='repo', subcommands=subcommands)
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 2)
    command_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(command_event, expected_event_name='command')
    # Check for 'command' event specific fields.
    self.assertIn('name', command_event)
    self.assertIn('subcommands', command_event)
    self.assertEqual(command_event['name'], name)
    self.assertEqual(command_event['subcommands'], subcommands)

  def test_def_params_event_repo_config(self):
    """Test 'def_params' event data outputs only repo config keys.

    Expected event log:
    <version event>
    <def_param event>
    <def_param event>
    """
    config = {
        'git.foo': 'bar',
        'repo.partialclone': 'true',
        'repo.partialclonefilter': 'blob:none',
    }
    self._event_log_module.DefParamRepoEvents(config)

    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 3)
    def_param_events = self._log_data[1:]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')

    for event in def_param_events:
      self.verifyCommonKeys(event, expected_event_name='def_param')
      # Check for 'def_param' event specific fields.
      self.assertIn('param', event)
      self.assertIn('value', event)
      self.assertTrue(event['param'].startswith('repo.'))

  def test_def_params_event_no_repo_config(self):
    """Test 'def_params' event data won't output non-repo config keys.

    Expected event log:
    <version event>
    """
    config = {
        'git.foo': 'bar',
        'git.core.foo2': 'baz',
    }
    self._event_log_module.DefParamRepoEvents(config)

    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 1)
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')

  def test_error_event(self):
    """Test and validate 'error' event data is valid.

    Expected event log:
    <version event>
    <error event>
    """
    msg = 'invalid option: --cahced'
    fmt = 'invalid option: %s'
    self._event_log_module.ErrorEvent(msg, fmt)
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 2)
    error_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(error_event, expected_event_name='error')
    # Check for 'error' event specific fields.
    self.assertIn('msg', error_event)
    self.assertIn('fmt', error_event)
    self.assertEqual(error_event['msg'], msg)
    self.assertEqual(error_event['fmt'], fmt)

  def test_write_with_filename(self):
    """Test Write() with a path to a file exits with None."""
    self.assertIsNone(self._event_log_module.Write(path='path/to/file'))

  def test_write_with_git_config(self):
    """Test Write() uses the git config path when 'git config' call succeeds."""
    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      with mock.patch.object(self._event_log_module,
                             '_GetEventTargetPath', return_value=tempdir):
        self.assertEqual(os.path.dirname(self._event_log_module.Write()), tempdir)

  def test_write_no_git_config(self):
    """Test Write() with no git config variable present exits with None."""
    with mock.patch.object(self._event_log_module,
                           '_GetEventTargetPath', return_value=None):
      self.assertIsNone(self._event_log_module.Write())

  def test_write_non_string(self):
    """Test Write() with non-string type for |path| throws TypeError."""
    with self.assertRaises(TypeError):
      self._event_log_module.Write(path=1234)


if __name__ == '__main__':
  unittest.main()
