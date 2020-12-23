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

import datetime
import json
import os
import sys
import tempfile
import threading

from git_command import GitCommand, RepoSourceVersion


class EventLog(object):
  """Event log that records events that occurred during a repo invocation.

  Events are written to the log as a consecutive JSON entries, one per line.
  Entries follow the git trace2 EVENT format at:
  https://git-scm.com/docs/api-trace2#_event_format

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
    # Try to get session-id from environment (setup in repo launcher).
    KEY = 'GIT_TRACE2_PARENT_SID'
    self._sid = os.environ.get(KEY)
    # If it is not set, generate a new session-id.
    if self._sid is None:
      now = datetime.datetime.utcnow()
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
    return {
        'event': event_name,
        'sid': self._sid,
        'threading': threading.currentThread().getName(),
        'time': datetime.datetime.utcnow().isoformat() + 'Z',
    }

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

    # Consider 'None' success (consistent with event_log result handling).
    if result is None:
      result = 0
    exit_event['code'] = result
    self._log.append(exit_event)

  def Write(self, path=None):
    """Writes the log out to a file.

    Log is only written if 'path' or 'git config --get trace2.eventtarget' provide a
    valid path to write logs to.

    Logging filename format follows the git trace2 style of being a unique (exclusive writable)
    file.

    Args:
      path: Path to where logs should be written.

    Returns:
      True if log is written, False otherwise.
    """
    # If no logging path is specified, get the path from 'trace2.eventtarget'.
    if path is None:
      cmd = ['config', '--get', 'trace2.eventtarget']
      p = GitCommand(None, cmd, capture_stdout=True, capture_stderr=True,
                     bare=True)
      if p.Wait() == 0:
        path = p.stdout.rstrip('\n')  # Strip trailing carriage-return in path.

    if isinstance(path, str):
      # Get absolute path
      path = os.path.abspath(os.path.expanduser(path))
    else:
      raise TypeError('Expected %r from |path|, got %r.' % (type(str()), type(path)))

    # Git trace2 requires a directory to write log to.

    if not os.path.isdir(path):
      print('repo: warning: git trace2 logging path %r is not a directory' % path,
            file=sys.stderr)
      return False

    # Use NamedTemporaryFile to generate a unique filename as required by git trace2.
    try:
      with tempfile.NamedTemporaryFile(mode='x', prefix=self._sid, dir=path,
                                       delete=False) as f:
        for e in self._log:
          json.dump(e, f)
          f.write('\n')
    except FileExistsError as err:
      print('repo: warning: git trace2 logging failed with: %r' % err,
            file=sys.stderr)
      return False
    return True
