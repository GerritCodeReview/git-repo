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
FILE_NAME = 'foo'

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

    def __enter__(self):
        if IsTrace():
          print(sys.stderr)
          print(f"PID: {os.getpid()} START: {self._time()} :" + self._fmt % self._args)
          print(f"PID: {os.getpid()} START: {self._time()} :" + self._fmt % self._args, file=sys.stderr)
        return self

    def __exit__(self, *exc):
        if IsTrace():
          print(sys.stderr)
          print(f"PID: {os.getpid()} END: {self._time()} :" + self._fmt % self._args)
          print(f"PID: {os.getpid()} END: {self._time()} :" + self._fmt % self._args, file=sys.stderr)
        return False
