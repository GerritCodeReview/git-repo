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

# TODO: When python2 is no longer supported, delete the following block of code
# BEGIN PYTHON2 DUCK PUNCHING, etc
from __future__ import print_function
# END PYTHON2 DUCK PUNCHING, etc

import sys
from command import Command, MirrorSafeCommand
from git_command import git
from project import HEAD

class Version(Command, MirrorSafeCommand):
  common = False
  helpSummary = "Display the version of repo"
  helpUsage = """
%prog
"""

  def Execute(self, opt, args):
    rp = self.manifest.repoProject
    rem = rp.GetRemote(rp.remote.name)

    print('repo version %s' % rp.work_git.describe(HEAD))
    print('       (from %s)' % rem.url)
    print(git.version().strip())
    print('Python %s' % sys.version)
