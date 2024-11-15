# Copyright (C) 2023 The Android Open Source Project
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

import contextlib
import fcntl
import json
import os
import time

_PATH = None
TH = 0


def init_tracing(path: str):
  global _PATH
  _PATH = path
  with open(path, 'w') as f:
    f.write('[\n')


@contextlib.contextmanager
def trace_event(name: str, args: list[str] = []):
  global _PATH, TH
  if _PATH is None:
    yield
  else:
    with open(_PATH, 'a') as f:
      data = json.dumps(
          {
              'pid': os.getpid(),
              'ts': time.time_ns() // 1000,
              'ph': 'B',
              'name': name,
              'args': args,
          },
      )
      fcntl.flock(f.fileno(), fcntl.LOCK_EX)
      f.write(data + ',\n')
      fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    try:
      yield
    finally:
      with open(_PATH, 'a') as f:
        data = json.dumps(
            {
                'pid': os.getpid(),
                'ts': time.time_ns() // 1000,
                'ph': 'E',
                'name': name,
                'args': args,
            },
        )
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(data + ',\n')
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def stop_tracing():
  with open(_PATH, 'rb+') as f:
    f.seek(-2, os.SEEK_END)
    f.write(b'\n]\n')
