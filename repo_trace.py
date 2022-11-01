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

"""Logic for tracing repo interactions."""

import sys
import os
import time
from contextlib import ContextDecorator

# Env var to implicitly turn on tracing.
REPO_TRACE = 'REPO_TRACE'

# Temporarily set tracing to always on.
_TRACE = os.environ.get(REPO_TRACE) == '1' or True

MAX_SIZE = 1  # in mb
TRACE_FILE = 'TRACE_FILE'
NEW_COMMAND_SEP = '+++++++++++++++++++++++++++++++++++'


def IsTrace():
  return _TRACE

def SetTrace():
  global _TRACE
  _TRACE = True


class Trace(ContextDecorator):

    def _time(self):
      """Generate nanoseconds of time in a py3.6 safe way"""
      return int(time.time()*1e+9)

    def __init__(self, fmt, *args, **kwargs):
      if not IsTrace():
        return
      self._trace_msg = fmt % args
      self.old_stderr = None
      self.trace_file_obj = None
      if kwargs.get('firstTrace') == 'true':
        trace_file = _GetTraceFile()
        ClearOldTraces(trace_file)
        self.trace_file_obj = open(trace_file, 'w')
        self.old_stderr = sys.stderr
        sys.stderr = self.trace_file_obj
        self._trace_msg = '%s %s' % (NEW_COMMAND_SEP, self._trace_msg)


    def __enter__(self):
      if not IsTrace():
        return self

      print(f"PID: {os.getpid()} START: {self._time()} :" + self._trace_msg + '\n', file=sys.stderr)
      return self

    def __exit__(self, *exc):
      if not IsTrace():
        return False

      print(f"PID: {os.getpid()} END: {self._time()} :" + self._trace_msg + '\n', file=sys.stderr)
      if self.trace_file_obj:
        self.trace_file_obj.close()
        sys.stderr = self.old_stderr
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
  trace_file = os.path.join(curdir, repodir, TRACE_FILE)
  return trace_file

def ClearOldTraces(trace_file):
    if os.path.isfile(trace_file) and os.path.getsize(trace_file)/(1024*1024) > MAX_SIZE:
      temp_file = trace_file + 'tmp'
      with open(trace_file, 'r') as fin:
        with open(temp_file, 'w') as tf:
          trace_lines = fin.readlines()
          for i , l in enumerate(trace_lines):
            if 'END:' in l and NEW_COMMAND_SEP in l:
              tf.writelines(trace_lines[i+1:])
              break
      os.replace(temp_file, trace_file)
