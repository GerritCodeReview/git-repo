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

_TRACE = os.environ.get(REPO_TRACE) == '1'

MAX_SIZE = 1  # in mb
TRACE_FILE = 'TRACE_FILE'
NEW_COMMAND_SEP = '+++++++++++++++++++++++++++++++++++'

def IsTrace():
  return True

def SetTrace():
  global _TRACE
  _TRACE = True

class Trace(ContextDecorator):

    def _time(self):
      """Generate nanoseconds of time in a py3.6 safe way"""
      return int(time.time()*1e+9)

    def __init__(self, fmt, *args):
      self._fmt = fmt
      self._args = args
      self._trace_file = _GetTraceFile()
      if os.path.isfile(self._trace_file) and (NEW_COMMAND_SEP in self._fmt % self._args):
        temp_file = self._trace_file + 'tmp'
        with open(self._trace_file, 'r') as fin:
          with open(temp_file, 'w') as tf:
            trace_lines = fin.readlines()
            for i , l in enumerate(trace_lines):
              if 'END:' in l and NEW_COMMAND_SEP in l:
                tf.writelines(trace_lines[i+1:])
                break
        os.replace(temp_file, self._trace_file)

    def __enter__(self):
        if IsTrace():
          with open(self._trace_file, 'a') as f:
            print(f"PID: {os.getpid()} START: {self._time()} :" + self._fmt % self._args, file=f)
        return self

    def __exit__(self, *exc):
        if IsTrace():
          with open(self._trace_file, 'a') as f:
            print(f"PID: {os.getpid()} END: {self._time()} :" + self._fmt % self._args, file=f)
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
