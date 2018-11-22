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
import sys
from command import Command
from progress import Progress

class Checkout(Command):
  common = True
  helpSummary = "Checkout a branch for development"
  helpUsage = """
%prog [-d] [<branchname>] [<project>...]
"""
  helpDescription = """
The '%prog' command checks out an existing branch that was previously
created by 'repo start'.

Without -d/--detach, the command is equivalent to:

  repo forall [<project>...] -c git checkout <branchname>

except that projects that do not have the branch are skipped.

With -d/--detach, checks out the branch in detached mode. <branchname> may be
either a local branch (refs/heads/*) or a remote one (refs/remotes/*). If the
branch is "" or unspecified, it defaults to the remote branch or revision in the
manifest, which means it can be used to "un-checkout" local development branches.
"""

  def _Options(self, p):
    p.add_option('-d', '--detach',
                 dest='detach_head', action='store_true',
                 help='Make a detached checkout. May be used with remote branches.')

  def Execute(self, opt, args):
    nb = args[0] if args else None
    if not nb and not opt.detach_head:
      self.Usage()

    err = []
    success = []
    all_projects = self.GetProjects(args[1:])

    pm = Progress('Checkout %s' % nb, len(all_projects))
    for project in all_projects:
      pm.update()

      status = (project.CheckoutDetached(nb) if opt.detach_head else
                project.CheckoutBranch(nb))
      if status is not None:
        if status:
          success.append(project)
        else:
          err.append(project)
    pm.end()

    if err:
      for p in err:
        print("error: %s/: cannot checkout %s" % (p.relpath, nb),
              file=sys.stderr)
      sys.exit(1)
    elif not success:
      print('error: no project has branch %s' % nb, file=sys.stderr)
      sys.exit(1)
