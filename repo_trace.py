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
"""

import sys
import os
import time
from contextlib import ContextDecorator

# Env var to implicitly turn on tracing.
REPO_TRACE = 'REPO_TRACE'

# Temporarily set tracing to always on.
_TRACE = os.environ.get(REPO_TRACE) == '1' or True

_TRACE_TO_STDERR = False

_TRACE_FILE = None

_MAX_SIZE = 1  # in mb
_TRACE_FILE = 'TRACE_FILE'
_NEW_COMMAND_SEP = '+++++++++++++++NEW COMMAND+++++++++++++++++++'


def IsStraceToStderr():
  return _TRACE_TO_STDERR


def IsTrace():
  return _TRACE


def SetTraceToStderr():
  global _TRACE_TO_STDERR
  _TRACE_TO_STDERR = True


def SetTrace():
  global _TRACE
  _TRACE = True


def _SetTraceFile():
  global _TRACE_FILE
  _TRACE_FILE = _GetTraceFile()


class Trace(ContextDecorator):

    def _time(self):
      """Generate nanoseconds of time in a py3.6 safe way"""
      return int(time.time()*1e+9)

    def __init__(self, fmt, *args, **kwargs):
      if not IsTrace():
        return
      self._trace_msg = fmt % args

      if kwargs.get('firstTrace') == 'true':
        _SetTraceFile()
        _ClearOldTraces()
        self._trace_msg = '%s %s' % (_NEW_COMMAND_SEP, self._trace_msg)


    def __enter__(self):
      if not IsTrace():
        return self

      print_msg = f"PID: {os.getpid()} START: {self._time()} :" + self._trace_msg + '\n'

      with open(_TRACE_FILE, 'a') as f:
        print(print_msg, file=f)

      if _TRACE_TO_STDERR:
        print(print_msg, file=sys.stderr)

      return self

    def __exit__(self, *exc):
      if not IsTrace():
        return False

      print_msg = f"PID: {os.getpid()} END: {self._time()} :" + self._trace_msg + '\n'

      with open(_TRACE_FILE, 'a') as f:
        print(print_msg, file=f)

      if _TRACE_TO_STDERR:
        print(print_msg, file=sys.stderr)

      return False


def _GetTraceFile():
  """Get the trace file or create one."""
  curdir = os.getcwd()
  repodir = '.repo'
  repo = None

  olddir = None
  while curdir != olddir and not repo:
    repo = os.path.join(curdir, repodir, 'repo/main.py')
    if not os.path.isfile(repo):
      repo = None
      olddir = curdir
      curdir = os.path.dirname(curdir)
  trace_file = os.path.join(curdir, repodir, _TRACE_FILE)
  return trace_file

def _ClearOldTraces():
  """Clear traces from old commands if trace file is too big."""
  if os.path.isfile(_TRACE_FILE):
    while os.path.getsize(_TRACE_FILE)/(1024*1024) > _MAX_SIZE:
      temp_file = _TRACE_FILE + 'tmp'
      with open(_TRACE_FILE, 'r', errors='ignore') as fin:
        with open(temp_file, 'w') as tf:
          trace_lines = fin.readlines()
          for i , l in enumerate(trace_lines):
            if 'END:' in l and _NEW_COMMAND_SEP in l:
              tf.writelines(trace_lines[i+1:])
              break
      os.replace(temp_file, _TRACE_FILE)
