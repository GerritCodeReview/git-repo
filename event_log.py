#
# Copyright (C) 2017 The Android Open Source Project
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

from __future__ import print_function

import json

try:
  import multiprocessing
except ImportError:
  multiprocessing = None

TASK_SYNC_NETWORK = 'sync-network'
TASK_SYNC_LOCAL = 'sync-local'

class EventLog(object):
  """Event log that records events that occurred during a repo invocation.

  Events are written to the log as a consecutive JSON entries, one per line.
  Each entry contains the following keys:
  - id: A ('RepoOp', ID) tuple, suitable for storing in a datastore.
        The ID is only unique for the invocation of the repo command.
  - name: Name of the object being operated upon.
  - success: Boolean indicating if the operation was successful.
  - start: Timestamp of when the operation started.
  - finish: Timestamp of when the operation finished.
  - task_name: The task that was performed.  Valid task_names are:
  - try_count: A counter indicating the try count of this task.

  Valid task_names include:
  - command: The invocation of a subcommand.
  - sync-network: The network component of a sync command.
  - sync-local: The local component of a sync command.

  Specific tasks may include additional informational properties.
  """

  def __init__(self):
    """Initializes the event log."""
    self._log = []
    self._next_id = _EventIdGenerator()

  def Add(self, name, success, start, finish,
          task_name, try_count=1, kind='RepoOp'):
    """Add an event to the log.

    Args:
      name: Name of the object being operated upon.
      success: Boolean indicating if the operation was successful.
      start: Timestamp of when the operation started.
      finish: Timestamp of when the operation finished.
      task_name: A sub-task that was performed for name.
      try_count: A counter indicating the try count of this task.
      kind: The kind of the object for the unique identifier.

    Returns:
      A dictionary of the event added to the log.
    """
    event = {
        'id': (kind, self._next_id.next()),
        'name': name,
        'status': 'pass' if success else 'fail',
        'start_time': start,
        'finish_time': finish,
        'task_name': task_name,
        'try': try_count,
    }
    self._log.append(event)
    return event

  def AddSync(self, project, success, start, finish, task_name):
    """Add a event to the log for a sync command.

    Args:
      project: Project being synced.
      success: Boolean indicating if the operation was successful.
      start: Timestamp of when the operation started.
      finish: Timestamp of when the operation finished.
      task_name: A sub-task that was performed for name.
                 One of (TASK_SYNC_NETWORK, TASK_SYNC_LOCAL)

    Returns:
      A dictionary of the event added to the log.
    """
    event = self.Add(project.relpath, success, start, finish, task_name)
    if event is not None:
      event['project'] = project.name
      event['revision'] = project.revisionExpr
      event['remote_url'] = project.remote.url
      try:
        event['git_hash'] = project.GetCommitRevisionId()
      except:
        pass
    return event

  def Write(self, filename):
    """Writes the log out to a file.

    Args:
      filename: The file to write the log to.
    """
    with open(filename, 'w+') as f:
      for e in self._log:
        json.dump(e, f, sort_keys=True)
        f.write('\n')


def _EventIdGenerator():
  """Returns multi-process safe iterator that generates locally unique id."""
  if multiprocessing:
    eid = multiprocessing.Value('i', 1)

    while True:
      with eid.get_lock():
        val = eid.value
        eid.value += 1
      yield val
  else:
    eid = 1
    while True:
      val = eid
      eid += 1
      yield val

