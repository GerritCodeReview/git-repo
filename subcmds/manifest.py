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

import os
import sys

from command import Command

class Manifest(Command):
  common = False
  helpSummary = "Manifest file"
  helpUsage = """
%prog
"""
  _helpDescription = """
The repo manifest file describes the projects mapped into the client.
"""

  @property
  def helpDescription(self):
    help = self._helpDescription + '\n'
    r = os.path.dirname(__file__)
    r = os.path.dirname(r)
    fd = open(os.path.join(r, 'docs', 'manifest-format.txt'))
    for line in fd:
      help += line
    fd.close()
    return help

  def Execute(self, opt, args):
    print >>sys.stderr, 'error: see repo help manifest'
    sys.exit(1)
