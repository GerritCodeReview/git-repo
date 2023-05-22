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

from command import Command
from git_command import GitCommand


class SquashError(Exception):
  pass


def hasMatchingBranch(branches, mergeBranch):
  branchName = mergeBranch.split('/')[-1]
  for branch in branches:
    if branchName in branch:
      return True

  return False


# Runs a sequence of commands somewhat like the following:
#
# git branch __repo_autosquash_backup-fontscaling-helpers
#
# find commit directly after preceding branch
# git log --expand-tabs --format=format:"%h %D %gd"
#
# keep finding branches until we hit the master (m/ or goog/)?
#
# git reset --soft 57d6eb0bbef
#
# git commit -a --amend --no-edit
class Autosquasher:
    def __init__(self, project, currentBranch):
        self.project = project
        self.currentBranch = self.project.GetBranch(self.project.CurrentBranch)
        self.backupBranch = "__repo_autosquasher_backup-" + currentBranch
        self.verbose = False

    def Squash(self):
        if self.Git(['branch', self.backupBranch]):
            raise SquashError('Failed to create backup branch')

        commits = self.ListCommitsWithBranches()

        # find commit directly after preceding branch
        # keep finding branches until we hit the master (m/ or goog/)?
        mergeBranch = self.currentBranch.merge
        lastCommit = None
        for i in range(1, len(commits)):
          commit = commits[i]
          if self.verbose:
            print('Found commit %s %s' % (commit["revision"], commit["branches"]))

          if hasMatchingBranch(commit["branches"], mergeBranch):
            lastCommit = commits[i - 1]["revision"]
            break

        if lastCommit is None:
          raise SquashError("Couldn't find any commits after the remote merge branch")

        if self.Git(['reset', '--soft', lastCommit]):
            raise SquashError('Failed to reset branch')

        if self.Git(['commit', '--no-edit', '--amend']):
            raise SquashError('Failed to commit squashed changes')

    def Restore(self):
      if self.verbose:
        print('Restoring branch %s' % (self.backupBranch))

      if self.Git(['reset', '--hard', self.backupBranch]):
          raise SquashError('Failed to restore backup branch %s' % (self.backupBranch))

      if self.Git(['branch', '-d', self.backupBranch]):
         raise SquashError('Failed to delete backup branch %s' % (self.backupBranch))

    def ListCommitsWithBranches(self):
        # git log --expand-tabs --format=format:"%h %D %gd"
      command = GitCommand(
          self.project,
          [
              'log',
              '-n',
              '100',
              '--expand-tabs',
              r'--format=format:"%h %D %gd"'
          ],
          capture_stdout=True,
          capture_stderr=True
      )
      if command.Wait() != 0:
        raise SquashError('Failed to list branches')

      commits = []
      for line in command.stdout.split('\n'):
        line = line.strip(r'"')
        if not line.strip():
          continue
        lineSplit = line.split(None, 1)
        rev = lineSplit[0]
        branchesStr = lineSplit[1] if len(lineSplit) > 1 else None
        if branchesStr:
          branchesStr = branchesStr.replace("->", ",")
          branchesStr = branchesStr.replace(",", "")
          branches = branchesStr.split()
        else:
          branches = []

        commits.append({"revision": rev, "branches": branches})

      return commits

    def Git(self, args):
      if self.verbose:
        print('Running git %s' % (args))

      return GitCommand(self.project, args).Wait() != 0


class Autosquash(Command):
  COMMON = True
  helpSummary = """
Squashes all your commits from your current branch down to the merge branch so they can be uploaded
"""
  helpUsage = """
%prog {[<project>...] | -i <project>...}
"""
  helpDescription = """
'%prog' squashes all your commits in your current branch into a single commit.
This is useful when you are ready to upload, but you only want a single CL from
all your commits in the branch. You can then run '%prog --restore' to unsquash
when you are finished uploading.
"""

  def _Options(self, p):
    p.add_option('-r', '--restore',
                 dest='restore', action='store_true',
                 help='restores the original state before you autosquashed')

  def Execute(self, opt, args):
    projects = self.GetProjects(args, all_manifests=not opt.this_manifest_only)

    autosquasher = None
    try:
      if (len(projects) == 1):
        project = projects[0]
        autosquasher = Autosquasher(project, project.CurrentBranch)
        if opt.restore:
          autosquasher.Restore()
        else:
          autosquasher.Squash()
      else:
        print("WARNING: Autosquash aborted. Autosquash doesn't work on multiple projects. Did you "
              "make sure to specify only the current directory?")
    except SquashError as e:
      print('Autosquash error: %s' % (e))
      if autosquasher is not None:
        autosquasher.Restore()
      return 1
