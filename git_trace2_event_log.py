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

"""Event logging in the git trace2 EVENT format."""

from git_command import GetEventTargetPath
from git_command import RepoSourceVersion
from git_trace2_event_log_base import BaseEventLog


class EventLog(BaseEventLog):
    """Event log that records events that occurred during a repo invocation.

    Events are written to the log as a consecutive JSON entries, one per line.
    Entries follow the git trace2 EVENT format.

    Each entry contains the following common keys:
    - event: The event name
    - sid: session-id - Unique string to allow process instance to be
          identified.
    - thread: The thread name.
    - time: is the UTC time of the event.

    Valid 'event' names and event specific fields are documented here:
    https://git-scm.com/docs/api-trace2#_event_format
    """

    def __init__(self, **kwargs):
        super().__init__(repo_source_version=RepoSourceVersion(), **kwargs)

    def Write(self, path=None, **kwargs):
        if path is None:
            path = self._GetEventTargetPath()
        return super().Write(path=path, **kwargs)

    def _GetEventTargetPath(self):
        return GetEventTargetPath()
