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

import sys
from command import Command
from git_command import git
from progress import Progress

class Abandon(Command):
  common = True
  helpSummary = "Permanently abandon a development branch"
  helpUsage = """
%prog <branchname> [<project>...]

This subcommand permanently abandons a development branch by
deleting it (and all its history) from your local repository.

It is equivalent to "git branch -D <branchname>".
"""

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    if not git.check_ref_format('heads/%s' % nb):
      print >>sys.stderr, "error: '%s' is not a valid name" % nb
      sys.exit(1)

    nb = args[0]
    err = []
    all = self.GetProjects(args[1:])

    pm = Progress('Abandon %s' % nb, len(all))
    for project in all:
      pm.update()
      if not project.AbandonBranch(nb):
        err.append(project)
    pm.end()

    if err:
      if len(err) == len(all):
        print >>sys.stderr, 'error: no project has branch %s' % nb
      else:
        for p in err:
          print >>sys.stderr,\
            "error: %s/: cannot abandon %s" \
            % (p.relpath, nb)
      sys.exit(1)
