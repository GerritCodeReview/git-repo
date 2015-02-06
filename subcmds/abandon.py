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
from git_command import git
from progress import Progress

class Abandon(Command):
  common = True
  opt = None
  args = None
  helpSummary = "Permanently abandon a development branch"
  helpUsage = """
%prog [<branchname> [<project>...] | --all] [--confirm]

This subcommand permanently abandons a development branch by
deleting it (and all its history) from your local repository.

It is equivalent to "git branch -D <branchname>".
"""

  def _Options(self, p):
    p.add_option('--all', default=False,
                 action='store_true', dest='abandon_all',
                 help='Abandon all branches detected.')
    p.add_option('--confirm', default=False,
                 action='store_true', dest='abandon_deputed',
                 help='Branch will only be abandoned after confirmation')

  def _validate_parameters(self):
    if not self.args and not self.opt.abandon_all:
      self.Usage()

    if self.args and self.opt.abandon_all:
      self.OptionParser.error("[<branchname> [<project>...]] and [--all] are mutually exclusive.")

    if self.args:
      branch_name = self.args[0]
      if not git.check_ref_format('heads/%s' % branch_name):
        self.OptionParser.error("'%s' is not a valid name" % branch_name)

  def _collect_branches(self):
    branches = {}
    project_names = []
    if not self.opt.abandon_all:
      project_names = self.args[1:]

    all_projects = self.GetProjects(project_names)

    if self.opt.abandon_all:
      for project in all_projects:
        for name in project.GetBranches():
          branches.setdefault(name, [])
          branches[name].append(project)
    else:
      branch_name = self.args[0]
      branches[branch_name] = all_projects

    return branches

  def _request_to_skip(self, branch):
    if not self.opt.abandon_deputed:
      return False
    while True:
      print('Abandon %s\t[Y/n]? ' % branch, end='')
      result = raw_input().strip().lower()
      if not result or 'y' == result:
        return False
      if 'n' == result:
        return True

  def Execute(self, opt, args):
    self.opt, self.args = opt, args
    self._validate_parameters()
    branches = self._collect_branches()

    for current_branch in branches:
      if self._request_to_skip(current_branch):
        continue
      err = []
      success = []
      all_projects = branches[current_branch]

      pm = Progress('Abandon %s' % current_branch, len(all_projects))
      for project in all_projects:
        pm.update()

        status = project.AbandonBranch(current_branch)
        if status is not None:
          if status:
            success.append(project)
          else:
            err.append(project)
      pm.end()

      if err:
        for p in err:
          print("error: %s/: cannot abandon %s" % (p.relpath, current_branch),
                file=sys.stderr)
        sys.exit(1)
      elif not success:
        print('error: no project has branch %s' % current_branch, file=sys.stderr)
        sys.exit(1)
      else:
        print('Abandoned in %d project(s):\n  %s'
              % (len(success), '\n  '.join(p.relpath for p in success)),
              file=sys.stderr)
