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
import socket
import tempfile
import threading
import unittest
from unittest import mock

import git_trace2_event_log
import platform_utils


def serverLoggingThread(socket_path, server_ready, received_traces):
  """Helper function to receive logs over a Unix domain socket.

  Appends received messages on the provided socket and appends to received_traces.

  Args:
    socket_path: path to a Unix domain socket on which to listen for traces
    server_ready: a threading.Condition used to signal to the caller that this thread is ready to
        accept connections
    received_traces: a list to which received traces will be appended (after decoding to a utf-8
        string).
  """
  platform_utils.remove(socket_path, missing_ok=True)
  data = b''
  with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.bind(socket_path)
    sock.listen(0)
    with server_ready:
      server_ready.notify()
    with sock.accept()[0] as conn:
      while True:
        recved = conn.recv(4096)
        if not recved:
          break
        data += recved
  received_traces.extend(data.decode('utf-8').splitlines())


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

  def verifyCommonKeys(self, log_entry, expected_event_name=None, full_sid=True):
    """Helper function to verify common event log keys."""
    self.assertIn('event', log_entry)
    self.assertIn('sid', log_entry)
    self.assertIn('thread', log_entry)
    self.assertIn('time', log_entry)

    # Do basic data format validation.
    if expected_event_name:
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

  def remove_prefix(self, s, prefix):
    """Return a copy string after removing |prefix| from |s|, if present or the original string."""
    if s.startswith(prefix):
        return s[len(prefix):]
    else:
        return s

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

  def test_data_event_config(self):
    """Test 'data' event data outputs all config keys.

    Expected event log:
    <version event>
    <data event>
    <data event>
    """
    config = {
        'git.foo': 'bar',
        'repo.partialclone': 'false',
        'repo.syncstate.superproject.hassuperprojecttag': 'true',
        'repo.syncstate.superproject.sys.argv': ['--', 'sync', 'protobuf'],
    }
    prefix_value = 'prefix'
    self._event_log_module.LogDataConfigEvents(config, prefix_value)

    with tempfile.TemporaryDirectory(prefix='event_log_tests') as tempdir:
      log_path = self._event_log_module.Write(path=tempdir)
      self._log_data = self.readLog(log_path)

    self.assertEqual(len(self._log_data), 5)
    data_events = self._log_data[1:]
    self.verifyCommonKeys(self._log_data[0], expected_event_name='version')

    for event in data_events:
      self.verifyCommonKeys(event)
      # Check for 'data' event specific fields.
      self.assertIn('key', event)
      self.assertIn('value', event)
      key = event['key']
      key = self.remove_prefix(key, f'{prefix_value}/')
      value = event['value']
      self.assertEqual(self._event_log_module.GetDataEventName(value), event['event'])
      self.assertTrue(key in config and value == config[key])

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

  def test_write_socket(self):
    """Test Write() with Unix domain socket for |path| and validate received traces."""
    received_traces = []
    with tempfile.TemporaryDirectory(prefix='test_server_sockets') as tempdir:
      socket_path = os.path.join(tempdir, "server.sock")
      server_ready = threading.Condition()
      # Start "server" listening on Unix domain socket at socket_path.
      try:
        server_thread = threading.Thread(
            target=serverLoggingThread,
            args=(socket_path, server_ready, received_traces))
        server_thread.start()

        with server_ready:
          server_ready.wait(timeout=120)

        self._event_log_module.StartEvent()
        path = self._event_log_module.Write(path=f'af_unix:{socket_path}')
      finally:
        server_thread.join(timeout=5)

    self.assertEqual(path, f'af_unix:stream:{socket_path}')
    self.assertEqual(len(received_traces), 2)
    version_event = json.loads(received_traces[0])
    start_event = json.loads(received_traces[1])
    self.verifyCommonKeys(version_event, expected_event_name='version')
    self.verifyCommonKeys(start_event, expected_event_name='start')
    # Check for 'start' event specific fields.
    self.assertIn('argv', start_event)
    self.assertIsInstance(start_event['argv'], list)
