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

import string
from git_command import GitCommand

from command import Command
from color import Coloring
from error import NoSuchProjectError

class _Coloring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, "repoinfo")

class Info(Command):
  common = True
  helpSummary = "Get info of the current branch and manifest branch"

  def _Options(self, p, show_smart=True):
    self.jobs = self.manifest.default.sync_j

    p.add_option('-a', '--all',
                 dest='all', action='store_true',
                 help="show full info")

  def Execute(self, opt, args):
    self.out = _Coloring(self.manifest.globalConfig)
    self.heading = self.out.printer('heading', attr = 'bold')
    self.headtext = self.out.printer('headtext', fg = 'yellow')
    self.redtext = self.out.printer('redtext', fg = 'red')
    self.sha = self.out.printer("sha", fg = 'yellow')
    self.text = self.out.printer('text')
    self.dimtext = self.out.printer('dimtext', attr = 'dim')

    if len(args) > 0:
      projects = args
    else:
      projects = ["."]

    mergeBranch = self.manifest.manifestProject.config.GetBranch("default").merge

    self.heading("Manifest branch: ")
    self.headtext(self.manifest.default.revisionExpr)
    self.out.nl()
    self.heading("Manifest merge branch: ")
    self.headtext(mergeBranch)
    self.out.nl()

    try:
      projs = self.GetProjects(projects)
    except NoSuchProjectError:
      return

    for p in projs:
      self.heading("Project: ")
      self.headtext(p.name)
      self.out.nl()

      self.heading("Mount path: ")
      self.headtext(p.worktree)
      self.out.nl()

      self.heading("Current revision: ")
      self.headtext(p.revisionExpr)
      self.out.nl()

      localBranches = self.localBranches(p)
      self.heading("Local Branches: ")
      self.redtext(str(len(localBranches)))
      self.text(" [")
      self.text(string.join(localBranches, ", "))
      self.text("]")
      self.out.nl()

      if opt.all:
        self.findRemoteLocalDiff(p)

  def localBranches(self, project):
    #get all the local branches
    gc = GitCommand(project, ["branch"], capture_stdout=True, capture_stderr=True)
    gc.Wait()
    localBranches = []
    for line in gc.stdout.splitlines():
      localBranches.append(line.replace('*','').strip())

    return localBranches

  def findRemoteLocalDiff(self, project):
    #Fetch all the latest commits
    gc = GitCommand(project, ["fetch", "--all"], capture_stdout=True, capture_stderr=True).Wait()

    #Find branches
    gc = GitCommand(project, ["branch", "-r"], capture_stdout=True, capture_stderr=True)
    gc.Wait()
    isOnBranch = False
    for line in gc.stdout.splitlines():
      if "->" in line:
        isOnBranch = True
        break

    #Index the remote commits
    if isOnBranch:
      logTarget = "origin/" + project.revisionExpr
    else:
      logTarget = project.revisionExpr

    #index the local commits
    gc = GitCommand(project, ["log", "--pretty=oneline", logTarget + ".."], capture_stdout=True, capture_stderr=True)
    gc.Wait()
    localCommits = []
    for line in gc.stdout.splitlines():
      localCommits.append(line)

    gc = GitCommand(project, ["log", "--pretty=oneline", ".." + logTarget], capture_stdout=True, capture_stderr=True)
    gc.Wait()
    originCommits = []
    for line in gc.stdout.splitlines():
      originCommits.append(line)

    self.heading("Local Commits: ")
    self.redtext(str(len(localCommits)))
    self.dimtext(" (on current branch)")
    self.out.nl()

    for c in localCommits:
      split = c.split()
      self.sha(split[0] + " ")
      self.text(string.join(split[1:]))
      self.out.nl()

    print "----------------------------"

    self.heading("Remote Commits: ")
    self.redtext(str(len(originCommits)))
    self.out.nl()

    for c in originCommits:
      split = c.split()
      self.sha(split[0] + " ")
      self.text(string.join(split[1:]))
      self.out.nl()
