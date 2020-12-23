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

"""Unittests for the git_trace2_event_log.py module."""

from __future__ import print_function

import contextlib
import json
import tempfile
import unittest

import platform_utils
from pyversion import is_python3
import git_trace2_event_log


@contextlib.contextmanager
def TemporaryDirectory():
  """Create a new empty git checkout for testing."""
  # TODO(vapier): Convert this to tempfile.TemporaryDirectory once we drop
  # Python 2 support entirely.
  try:
    tempdir = tempfile.mkdtemp(prefix='event_log_tests')
    yield tempdir
  finally:
    platform_utils.rmtree(tempdir)


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
        self.PARENT_SID_KEY: self.PARENT_SID_VALUE
    }
    self._event_log_module = git_trace2_event_log.EventLog(env=env)
    self._log_data = None
    if not is_python3():
      self.assertRegex = self.assertRegexpMatches

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
    with open(log_path) as f:
      for line in f:
        log_data.append(json.loads(line))
    return log_data

  def test_initial_state(self):
    self.assertRegex(self._event_log_module.full_sid, self.FULL_SID_REGEX)

  def test_initial_state_no_parent_sid(self):
    # Setup an empty environment dict (no parent sid).
    self._event_log_module = git_trace2_event_log.EventLog(env={})
    self.assertRegex(self._event_log_module.full_sid, self.SELF_SID_REGEX)

  def test_version_event(self):
    with TemporaryDirectory() as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    # A log with no added events should only have the version entry.
    self.assertEqual(len(self._log_data), 1)
    version_event = self._log_data[0]
    self.verifyCommonKeys(version_event, expected_event_name='version')
    # Check for 'version' event specific fields.
    self.assertIn('evt', version_event)
    self.assertIn('exe', version_event)

  def test_start_event(self):
    self._event_log_module.StartEvent()
    with TemporaryDirectory() as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    # Event log should look like:
    # <version event>
    # <start event>
    self.assertEqual(len(self._log_data), 2)
    start_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(start_event, expected_event_name='start')
    # Check for 'start' event specific fields.
    self.assertIn('argv', start_event)
    self.assertTrue(isinstance(start_event['argv'], list))

  def test_exit_event_result_none(self):
    self._event_log_module.ExitEvent(None)
    with TemporaryDirectory() as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    # Event log should look like:
    # <version event>
    # <start event>
    self.assertEqual(len(self._log_data), 2)
    exit_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(exit_event, expected_event_name='exit')
    # Check for 'exit' event specific fields.
    self.assertIn('code', exit_event)
    # 'None' result should convert to 0 (successful) return code.
    self.assertEqual(exit_event['code'], 0)

  def test_exit_event_result_integer(self):
    self._event_log_module.ExitEvent(2)
    with TemporaryDirectory() as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    # Event log should look like:
    # <version event>
    # <exit event>
    self.assertEqual(len(self._log_data), 2)
    exit_event = self._log_data[1]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')
    self.verifyCommonKeys(exit_event, expected_event_name='exit')
    # Check for 'exit' event specific fields.
    self.assertIn('code', exit_event)
    self.assertEqual(exit_event['code'], 2)

  # TODO(https://crbug.com/gerrit/13706): Add additional test coverage for
  # Write() where:
  # - path=None (using git config call)
  # - path=<Non-String type> (raises TypeError)
  # - path=<Non-Directory> (should return None)
  # - tempfile.NamedTemporaryFile errors with FileExistsError (should return  None)


if __name__ == '__main__':
  unittest.main()
