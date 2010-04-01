#
# Copyright (C) 2010 The Android Open Source Project
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
from git_command import GitCommand
from git_refs import GitRefs, HEAD, R_HEADS, R_TAGS, R_PUB, R_M
from error import GitError

class Rebase(Command):
  common = True
  helpSummary = "Rebase local branches on upstream branch"
  helpUsage = """
%prog {[<project>...] | -i <project>...}
"""
  helpDescription = """
'%prog' uses git rebase to move local changes in the current topic branch to
the HEAD of the upstream history, useful when you have made commits in a topic
branch but need to incorporate new upstream changes "underneath" them.
"""

  def _Options(self, p):
    p.add_option('-i', '--interactive',
                dest="interactive", action="store_true",
                help="interactive rebase (single project only)")

  def Execute(self, opt, args):
    all = self.GetProjects(args)
    one_project = len(all) == 1

    if opt.interactive and not one_project:
      print >>sys.stderr, 'error: interactive rebase not supported with multiple projects'
      return -1

    for project in all:
      cb = project.CurrentBranch
      if not cb:
        if one_project:
          print >>sys.stderr, "error: project %s has a detatched HEAD" % project.name
          return -1
        # ignore branches with detatched HEADs
        continue

      upbranch = project.GetBranch(cb)
      if not upbranch.LocalMerge:
        if one_project:
          print >>sys.stderr, "error: project %s does not track any remote branches" % project.name
          return -1
        # ignore branches without remotes
        continue

      upstream = project.GetRevisionId()

      args = ["rebase"]
      if opt.interactive:
        args.append("-i")
      args.append(upstream)

      print '# project %s: rebasing branch %s -> %s (%s)' % (
        project.relpath, cb, upbranch.LocalMerge, upstream[0:7])
      if GitCommand(project, args).Wait() != 0:
        return -1
