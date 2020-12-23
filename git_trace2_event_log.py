# -*- coding:utf-8 -*-
#
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

import json
import os
import tempfile
import sys
import threading
import wrapper

from datetime import datetime
from git_command import RepoSourceVersion


class GitTrace2EventLog(object):
  """Event log that records events that occurred during a repo invocation.

  Events are written to the log as a consecutive JSON entries, one per line.
  Entries follow the git trace2 EVENT format at: https://git-scm.com/docs/api-trace2#_event_format

  Each entry contains the following common keys:
  - event: The event name
  - sid: session-id - Unique string to allow process instance to be identified.
  - thread: The thread name.
  - time: is the UTC time of the event.

  Valid 'event' names and event specific fields are documented here:
  https://git-scm.com/docs/api-trace2#_event_format

  Usage:
  git_trace_log = GitTrace2EventLog()
  git_trace_log.Add_<event>_Entry
  ...
  git_trace_log.Write()
  """

  def __init__(self):
    """Initializes the event log."""
    self._enabled = False
    self._log = []
    # Try to get session-id from environment (setup in repo launcher)
    KEY = 'GIT_TRACE2_PARENT_SID'
    self._sid = os.environ.get(KEY)
    # If it is not set, generate a new session-id
    if self._sid is None:
      now = datetime.utcnow()
      self._sid = 'repo-%s-P%08x' % (now.strftime('%Y%m%dT%H%M%SZ'), os.getpid())
    # Add a version event to front of the log.
    self._AddVersionEvent()

  def _AddVersionEvent(self):
    """Adds a 'version' event at the beginning of current log."""
    version_event = self._CreateEventDict('version')
    version_event['evt'] = 2
    version_event['exe'] = RepoSourceVersion()
    self._log.insert(0, version_event)

  def _CreateEventDict(self, event_name):
    """Returns a dictionary with the common keys/values for git trace2 events.

      Args:
        event_name: The event name.

      Returns:
        Dictionary with the common event fields populated.
    """
    git_trace2_event = {
        'event': event_name,
        'sid': self._sid,
        'threading': threading.currentThread().getName(),
        'time': datetime.utcnow().isoformat() + 'Z',
    }
    return git_trace2_event

  def StartEvent(self):
    """Append a 'start' event to the current log."""
    start_event = self._CreateEventDict('start')
    start_event['argv'] = sys.argv
    self._log.append(start_event)

  def ExitEvent(self, result):
    """Append an 'exit' event to the current log.

      Args:
        result: Exit code of the event
    """
    exit_event = self._CreateEventDict('exit')

  # Consider 'None' success (consistent with event_log result handling)
    if result is None:
      result = 0
    exit_event['code'] = result
    self._log.append(exit_event)

  def Write(self, logging_path=None):
    """Writes the log out to a file.

    Log is only written if 'logging_path' or 'git config --get trace2.eventtarget' provide a
    valid path to write logs to.

    Logging filename format follows the git trace2 style of being a unique (exclusive writable)
    file.

    Args:
      logging_path: Path to where logs should be written.

    Returns:
      True if log is written, False otherwise.
    """
    # If no logging path is specified, get the path from 'trace2.eventtarget'
    if logging_path is None:
      cmd = ['config', '--get', 'trace2.eventtarget']
      ret = wrapper.Wrapper().run_git(*cmd, check=False)
      if ret.returncode == 0:
        logging_path = ret.stdout.rstrip('\n')

    if isinstance(logging_path, str):
      # Get absolute path
      logging_path = os.path.abspath(os.path.expanduser(logging_path))
    else:
      return False

    # Git trace2 requires a directory to write log to.

    if not os.path.isdir(logging_path):
      print('repo: warning: git trace2 logging path {0!r} is not a directory'.format(logging_path))
      return False

    # Use NamedTemporaryFile to gaurantee a unique filename as required by git trace2.
    try:
      with tempfile.NamedTemporaryFile(mode='x', prefix=self._sid, dir=logging_path,
                                       delete=False) as f:
        for e in self._log:
          json.dump(e, f)
          f.write('\n')
    except FileExistsError as err:
      print('repo: warning: git trace2 logging failed with: {0}'.format(err))
      return False
    return True
