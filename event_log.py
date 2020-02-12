# -*- coding:utf-8 -*-
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
import multiprocessing

TASK_COMMAND = 'command'
TASK_SYNC_NETWORK = 'sync-network'
TASK_SYNC_LOCAL = 'sync-local'


class EventLog(object):
  """Event log that records events that occurred during a repo invocation.

  Events are written to the log as a consecutive JSON entries, one per line.
  Each entry contains the following keys:
  - id: A ('RepoOp', ID) tuple, suitable for storing in a datastore.
        The ID is only unique for the invocation of the repo command.
  - name: Name of the object being operated upon.
  - task_name: The task that was performed.
  - start: Timestamp of when the operation started.
  - finish: Timestamp of when the operation finished.
  - success: Boolean indicating if the operation was successful.
  - try_count: A counter indicating the try count of this task.

  Optionally:
  - parent: A ('RepoOp', ID) tuple indicating the parent event for nested
            events.

  Valid task_names include:
  - command: The invocation of a subcommand.
  - sync-network: The network component of a sync command.
  - sync-local: The local component of a sync command.

  Specific tasks may include additional informational properties.
  """

  def __init__(self):
    """Initializes the event log."""
    self._log = []
    self._parent = None

  def Add(self, name, task_name, start, finish=None, success=None,
          try_count=1, kind='RepoOp'):
    """Add an event to the log.

    Args:
      name: Name of the object being operated upon.
      task_name: A sub-task that was performed for name.
      start: Timestamp of when the operation started.
      finish: Timestamp of when the operation finished.
      success: Boolean indicating if the operation was successful.
      try_count: A counter indicating the try count of this task.
      kind: The kind of the object for the unique identifier.

    Returns:
      A dictionary of the event added to the log.
    """
    event = {
        'id': (kind, _NextEventId()),
        'name': name,
        'task_name': task_name,
        'start_time': start,
        'try': try_count,
    }

    if self._parent:
      event['parent'] = self._parent['id']

    if success is not None or finish is not None:
        self.FinishEvent(event, finish, success)

    self._log.append(event)
    return event

  def AddSync(self, project, task_name, start, finish, success):
    """Add a event to the log for a sync command.

    Args:
      project: Project being synced.
      task_name: A sub-task that was performed for name.
                 One of (TASK_SYNC_NETWORK, TASK_SYNC_LOCAL)
      start: Timestamp of when the operation started.
      finish: Timestamp of when the operation finished.
      success: Boolean indicating if the operation was successful.

    Returns:
      A dictionary of the event added to the log.
    """
    event = self.Add(project.relpath, task_name, start, finish, success)
    if event is not None:
      event['project'] = project.name
      if project.revisionExpr:
        event['revision'] = project.revisionExpr
      if project.remote.url:
        event['project_url'] = project.remote.url
      if project.remote.fetchUrl:
        event['remote_url'] = project.remote.fetchUrl
      try:
        event['git_hash'] = project.GetCommitRevisionId()
      except Exception:
        pass
    return event

  def GetStatusString(self, success):
    """Converst a boolean success to a status string.

    Args:
      success: Boolean indicating if the operation was successful.

    Returns:
      status string.
    """
    return 'pass' if success else 'fail'

  def FinishEvent(self, event, finish, success):
    """Finishes an incomplete event.

    Args:
      event: An event that has been added to the log.
      finish: Timestamp of when the operation finished.
      success: Boolean indicating if the operation was successful.

    Returns:
      A dictionary of the event added to the log.
    """
    event['status'] = self.GetStatusString(success)
    event['finish_time'] = finish
    return event

  def SetParent(self, event):
    """Set a parent event for all new entities.

    Args:
      event: The event to use as a parent.
    """
    self._parent = event

  def Write(self, filename):
    """Writes the log out to a file.

    Args:
      filename: The file to write the log to.
    """
    with open(filename, 'w+') as f:
      for e in self._log:
        json.dump(e, f, sort_keys=True)
        f.write('\n')


# An integer id that is unique across this invocation of the program.
_EVENT_ID = multiprocessing.Value('i', 1)


def _NextEventId():
  """Helper function for grabbing the next unique id.

  Returns:
    A unique, to this invocation of the program, integer id.
  """
  with _EVENT_ID.get_lock():
    val = _EVENT_ID.value
    _EVENT_ID.value += 1
  return val
