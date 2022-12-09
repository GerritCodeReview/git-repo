# Copyright (C) 2008 The Android Open Source Project
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

"""Logic for tracing repo interactions.

Activated via `repo --trace ...` or `REPO_TRACE=1 repo ...`.

Temporary: Tracing is always on. Set `REPO_TRACE=0` to turn off.
To also include trace outputs in stderr do `repo --trace_to_stderr ...`
"""

import sys
import os
import time
import tempfile
from contextlib import ContextDecorator

import platform_utils

# Env var to implicitly turn on tracing.
REPO_TRACE = 'REPO_TRACE'

# Temporarily set tracing to always on unless user expicitly sets to 0.
_TRACE = os.environ.get(REPO_TRACE) != '0'
_TRACE_TO_STDERR = False
_TRACE_FILE = None
_TRACE_FILE_NAME = 'TRACE_FILE'
_MAX_SIZE = 70  # in MiB
_NEW_COMMAND_SEP = '+++++++++++++++NEW COMMAND+++++++++++++++++++'


def IsTraceToStderr():
  """Whether traces are written to stderr."""
  return _TRACE_TO_STDERR


def IsTrace():
  """Whether tracing is enabled."""
  return _TRACE


def SetTraceToStderr():
  """Enables tracing logging to stderr."""
  global _TRACE_TO_STDERR
  _TRACE_TO_STDERR = True


def SetTrace():
  """Enables tracing."""
  global _TRACE
  _TRACE = True


def _SetTraceFile(quiet):
  """Sets the trace file location."""
  global _TRACE_FILE
  _TRACE_FILE = _GetTraceFile(quiet)


class Trace(ContextDecorator):
  """Used to capture and save git traces."""

  def _time(self):
    """Generate nanoseconds of time in a py3.6 safe way"""
    return int(time.time() * 1e+9)

  def __init__(self, fmt, *args, first_trace=False, quiet=True):
    """Initialize the object.

    Args:
      fmt: The format string for the trace.
      *args: Arguments to pass to formatting.
      first_trace: Whether this is the first trace of a `repo` invocation.
      quiet: Whether to suppress notification of trace file location.
    """
    if not IsTrace():
      return
    self._trace_msg = fmt % args

    if not _TRACE_FILE:
      _SetTraceFile(quiet)

    if first_trace:
      _ClearOldTraces()
      self._trace_msg = f'{_NEW_COMMAND_SEP} {self._trace_msg}'

  def __enter__(self):
    if not IsTrace():
      return self

    print_msg = f'PID: {os.getpid()} START: {self._time()} :{self._trace_msg}\n'

    with open(_TRACE_FILE, 'a') as f:
      print(print_msg, file=f)

    if _TRACE_TO_STDERR:
      print(print_msg, file=sys.stderr)

    return self

  def __exit__(self, *exc):
    if not IsTrace():
      return False

    print_msg = f'PID: {os.getpid()} END: {self._time()} :{self._trace_msg}\n'

    with open(_TRACE_FILE, 'a') as f:
      print(print_msg, file=f)

    if _TRACE_TO_STDERR:
      print(print_msg, file=sys.stderr)

    return False


def _GetTraceFile(quiet):
  """Get the trace file or create one."""
  # TODO: refactor to pass repodir to Trace.
  repo_dir = os.path.dirname(os.path.dirname(__file__))
  trace_file = os.path.join(repo_dir, _TRACE_FILE_NAME)
  if not quiet:
    print(f'Trace outputs in {trace_file}', file=sys.stderr)
  return trace_file


def _ClearOldTraces():
  """Clear the oldest commands if trace file is too big."""
  try:
    with open(_TRACE_FILE, 'r', errors='ignore') as f:
      if os.path.getsize(f.name) / (1024 * 1024) <= _MAX_SIZE:
        return
      trace_lines = f.readlines()
  except FileNotFoundError:
    return

  while sum(len(x) for x in trace_lines) / (1024 * 1024) > _MAX_SIZE:
    for i, line in enumerate(trace_lines):
      if 'END:' in line and _NEW_COMMAND_SEP in line:
        trace_lines = trace_lines[i + 1:]
        break
    else:
      # The last chunk is bigger than _MAX_SIZE, so just throw everything away.
      trace_lines = []

  while trace_lines and trace_lines[-1] == '\n':
    trace_lines = trace_lines[:-1]
  # Write to a temporary file with a unique name in the same filesystem
  # before replacing the original trace file.
  temp_dir, temp_prefix = os.path.split(_TRACE_FILE)
  with tempfile.NamedTemporaryFile('w',
                                   dir=temp_dir,
                                   prefix=temp_prefix,
                                   delete=False) as f:
    f.writelines(trace_lines)
  platform_utils.rename(f.name, _TRACE_FILE)
