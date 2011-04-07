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
from command import Command
from progress import Progress

class Checkout(Command):
  common = True
  helpSummary = "Checkout a branch for development"
  helpUsage = """
%prog <branchname> [<project>...]
"""
  helpDescription = """
The '%prog' command checks out an existing branch that was previously
created by 'repo start'.

The command is equivalent to:

  repo forall [<project>...] -c git checkout <branchname>
"""

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    err = []
    success = []
    all = self.GetProjects(args[1:])

    pm = Progress('Checkout %s' % nb, len(all))
    for project in all:
      pm.update()

      status = project.CheckoutBranch(nb)
      if status is not None:
        if status:
          success.append(project)
        else:
          err.append(project)
    pm.end()

    if err:
      for p in err:
        print >>sys.stderr,\
          "error: %s/: cannot checkout %s" \
          % (p.relpath, nb)
      sys.exit(1)
    elif not success:
      print >>sys.stderr, 'error: no project has branch %s' % nb
      sys.exit(1)
