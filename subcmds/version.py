# -*- coding:utf-8 -*-
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

from __future__ import print_function

import platform
import sys

from command import Command, MirrorSafeCommand
from git_command import git, RepoSourceVersion, user_agent
from git_refs import HEAD


class Version(Command, MirrorSafeCommand):
  wrapper_version = None
  wrapper_path = None

  common = False
  helpSummary = "Display the version of repo"
  helpUsage = """
%prog
"""

  def Execute(self, opt, args):
    rp = self.manifest.repoProject
    rem = rp.GetRemote(rp.remote.name)

    # These might not be the same.  Report them both.
    src_ver = RepoSourceVersion()
    rp_ver = rp.bare_git.describe(HEAD)
    print('repo version %s' % rp_ver)
    print('       (from %s)' % rem.url)

    if Version.wrapper_path is not None:
      print('repo launcher version %s' % Version.wrapper_version)
      print('       (from %s)' % Version.wrapper_path)

      if src_ver != rp_ver:
        print('       (currently at %s)' % src_ver)

    print('repo User-Agent %s' % user_agent.repo)
    print('git %s' % git.version_tuple().full)
    print('git User-Agent %s' % user_agent.git)
    print('Python %s' % sys.version)
    uname = platform.uname()
    print('OS %s %s (%s)' % (uname.system, uname.release, uname.version))
    print('CPU %s (%s)' %
          (uname.machine, uname.processor if uname.processor else 'unknown'))
