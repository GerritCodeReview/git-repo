# -*- coding:utf-8 -*-
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

from collections import defaultdict
import sys

from command import Command
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
    p.add_option('-q', '--quiet',
                 action='store_true', default=False,
                 help='be quiet')
    p.add_option('--all',
                 dest='all', action='store_true',
                 help='delete all branches in all projects')

  def ValidateOptions(self, opt, args):
    if not opt.all and not args:
      self.Usage()

    if not opt.all:
      nb = args[0]
      if not git.check_ref_format('heads/%s' % nb):
        self.OptionParser.error("'%s' is not a valid branch name" % nb)
    else:
      args.insert(0, "'All local branches'")

  def Execute(self, opt, args):
    nb = args[0]
    err = defaultdict(list)
    success = defaultdict(list)
    all_projects = self.GetProjects(args[1:])

    pm = Progress('Abandon %s' % nb, len(all_projects))
    for project in all_projects:
      pm.update()

      if opt.all:
        branches = list(project.GetBranches().keys())
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
        err_msg = "error: cannot abandon %s" % br
        print(err_msg, file=sys.stderr)
        for proj in err[br]:
          print(' ' * len(err_msg) + " | %s" % proj.relpath, file=sys.stderr)
      sys.exit(1)
    elif not success:
      print('error: no project has local branch(es) : %s' % nb,
            file=sys.stderr)
      sys.exit(1)
    else:
      # Everything below here is displaying status.
      if opt.quiet:
        return
      print('Abandoned branches:')
      for br in success.keys():
        if len(all_projects) > 1 and len(all_projects) == len(success[br]):
          result = "all project"
        else:
          result = "%s" % (
              ('\n' + ' ' * width + '| ').join(p.relpath for p in success[br]))
        print("%s%s| %s\n" % (br, ' ' * (width - len(br)), result))
