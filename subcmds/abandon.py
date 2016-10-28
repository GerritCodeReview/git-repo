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

from __future__ import print_function
import sys
from command import Command
from collections import defaultdict
from git_command import git
from progress import Progress

class Abandon(Command):
  common = True
  helpSummary = "Permanently abandon a development branch"
  helpUsage = """
%prog [--all | <branchname>] [<project>...]

This subcommand permanently abandons a development branch by
deleting it (and all its history) from your local repository.

It is equivalent to "git branch -D <branchname>".
"""
  def _Options(self, p):
    p.add_option('--all',
                 dest='all', action='store_true',
                 help='delete all branches in all projects')

  def Execute(self, opt, args):
    if not opt.all and not args:
      self.Usage()

    if not opt.all:
      nb = args[0]
      if not git.check_ref_format('heads/%s' % nb):
        print("error: '%s' is not a valid name" % nb, file=sys.stderr)
        sys.exit(1)
    else:
      args.insert(0,None)
      nb = "'All local branches'"

    err = defaultdict(list)
    success = defaultdict(list)
    all_projects = self.GetProjects(args[1:])

    pm = Progress('Abandon %s' % nb, len(all_projects))
    for project in all_projects:
      pm.update()

      if opt.all:
        branches = project.GetBranches().keys()
      else:
        branches = [nb]

      for name in branches:
        status = project.AbandonBranch(name)
        if status is not None:
          if status:
            success[name].append(project)
          else:
            err[name].append(project)
    pm.end()

    width = 25
    for name in branches:
      if width < len(name):
        width = len(name)

    if err:
      for br in err.keys():
        err_msg = "error: cannot abandon %s" %br
        print(err_msg, file=sys.stderr)
        for proj in err[br]:
          print(' '*len(err_msg) + " | %s" % p.relpath, file=sys.stderr)
      sys.exit(1)
    elif not success:
      print('error: no project has local branch(es) : %s' % nb,
            file=sys.stderr)
      sys.exit(1)
    else:
      print('Abandoned branches:', file=sys.stderr)
      for br in success.keys():
        if len(all_projects) > 1 and len(all_projects) == len(success[br]):
          result = "all project"
        else:
          result = "%s" % (
            ('\n'+' '*width + '| ').join(p.relpath for p in success[br]))
        print("%s%s| %s\n" % (br,' '*(width-len(br)), result),file=sys.stderr)
