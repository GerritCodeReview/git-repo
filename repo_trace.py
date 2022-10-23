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

_TRACE = os.environ.get(REPO_TRACE) == '1'


def IsTrace():
  return _TRACE


def SetTrace():
  global _TRACE
  _TRACE = True


class Trace(ContextDecorator):
    def __init__(self, fmt, *args):
      self._fmt = fmt
      self._args = args

    def __enter__(self):
        if IsTrace():
          print(f"PID: {os.getpid()} START: {time.time_ns()} :" + self._fmt % self._args, file=sys.stderr)
        return self

    def __exit__(self, *exc):
        if IsTrace():
          print(f"PID: {os.getpid()} END: {time.time_ns()} :" + self._fmt % self._args, file=sys.stderr)
        return False
