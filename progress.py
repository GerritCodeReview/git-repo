#
# Copyright (C) 2009 The Android Open Source Project
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

import sys

class Progress(object):
  def __init__(self, title, total=0):
    self._title = title
    self._total = total
    self._done = 0
    self._lastp = -1

  def update(self, inc=1):
    self._done += inc

    if self._total <= 0:
      sys.stderr.write('\r%s: %d, ' % (
        self._title,
        self._done))
      sys.stderr.flush()
    else:
      p = (100 * self._done) / self._total

      if self._lastp != p:
        self._lastp = p
        sys.stderr.write('\r%s: %3d%% (%d/%d)  ' % (
          self._title,
          p,
          self._done,
          self._total))
        sys.stderr.flush()

  def end(self):
    if self._total <= 0:
      sys.stderr.write('\r%s: %d, done.  \n' % (
        self._title,
        self._done))
      sys.stderr.flush()
    else:
      p = (100 * self._done) / self._total
      sys.stderr.write('\r%s: %3d%% (%d/%d), done.  \n' % (
        self._title,
        p,
        self._done,
        self._total))
      sys.stderr.flush()
