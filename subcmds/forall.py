#
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

import re
import os
import sys
import subprocess
from command import Command

class Forall(Command):
  common = False
  helpSummary = "Run a shell command in each project"
  helpUsage = """
%prog [<project>...] -c <command> [<arg>...]
"""
  helpDescription = """
Executes the same shell command in each project.

Environment
-----------
pwd is the project's working directory.

REPO_PROJECT is set to the unique name of the project.

shell positional arguments ($1, $2, .., $#) are set to any arguments
following <command>.

stdin, stdout, stderr are inherited from the terminal and are
not redirected.
"""

  def _Options(self, p):
    def cmd(option, opt_str, value, parser):
      setattr(parser.values, option.dest, list(parser.rargs))
      while parser.rargs:
        del parser.rargs[0]
    p.add_option('-c', '--command',
                 help='Command (and arguments) to execute',
                 dest='command',
                 action='callback',
                 callback=cmd)

  def Execute(self, opt, args):
    if not opt.command:
      self.Usage()

    cmd = [opt.command[0]]

    shell = True
    if re.compile(r'^[a-z0-9A-Z_/\.-]+$').match(cmd[0]):
      shell = False

    if shell:
      cmd.append(cmd[0])
    cmd.extend(opt.command[1:])

    rc = 0
    for project in self.GetProjects(args):
      env = dict(os.environ.iteritems())
      env['REPO_PROJECT'] = project.name

      p = subprocess.Popen(cmd,
                           cwd = project.worktree,
                           shell = shell,
                           env = env)
      r = p.wait()
      if r != 0 and r != rc:
        rc = r
    if rc != 0:
      sys.exit(rc)
