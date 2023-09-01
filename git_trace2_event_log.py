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
