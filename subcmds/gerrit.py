#
# Copyright (C) 2012 The Android Open Source Project
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
import json
import re
import sys

from command import InteractiveCommand
from gerrit_command import GerritCommand
from git_command import GitCommand

class Gerrit(InteractiveCommand):
  common = True
  helpSummary = "Interact with the Gerrit server"
  helpUsage = """
%prog [options] [<project>]
"""
  helpDescription = """
The "%prog" command is a way to interact with the Gerrit review server
via the command line.

--query -q
-------------

The query command lets you execute queries from the command line. It
lets you specify a search string such as the one you would enter into
the gerrit search box. It also has a number of shorthand commands for
frequently used options such as open and your own patch sets.

  Example:
    %prog -q -s "status:open branch:master"
      Will show you all open patch sets on branch master
    %prog -q -m -o
      Will give you a list of all your own open patch sets.

It is also possible to specify project, so extending the last example
will give you:

  %prog -q -m -o .
    Will show your own open patch sets in the current project.

--add-reviewers --re
-------------

The add-reviewers command lets you add reviewers to already uploaded
patch sets. While repo upload lets you specify uploaders the first
time you upload a change you might want to be able to add reviewers
later on as well. When you have many patches maybe on multiple
branches this can become quite inconvenient to do in the web gui.

This command is interactive and will ask for your permission for
every patch.

  Example:
    %prog --re "one.user@example.com another.user@example.com"
      This command will loop through all your commits that are under
      review and add the mentioned reviewers to the review.

Just like the query command this can be limited to a project by:
  Example:
    %prog --re "one.user@example.com another.user@example.com" .
    Will limit the command to the current project.

--abandon -a
-------------

Will let you abandon your patches.

This command is interactive and will ask for your permission for
every patch.

  Example:
    %prog -a
      Will go through your local repository and ask you if you want to abandon every patch.

Other options:
-------------

--remote

For --abandon and --reviewers you can add this option to make the command operate against
your open patches on the Gerrit review server instead.

  Example:
    %prog --remote -a
"""

  def _Options(self, p):
    g = p.add_option_group('Commands')
    g.add_option('-q', '--query',
                 dest='query', action='store_true',
                 help='Run a query towards the Gerrit server')
    g.add_option('--re', '--reviewers',
                 dest='reviewers', action='store',
                 help='Add reviewers to your patches')
    g.add_option('-a', '--abandon',
                 dest='abandon', action='store_true',
                 help='Abandon patches')

    g = p.add_option_group('Query options')
    g.add_option('-m', '--mine',
                 dest='mine',action='store_true',
                 help='Show your own patches')
    g.add_option('-o', '--open',
                 dest='open',action='store_true',
                 help='Show only open patches. Short for status: open')
    g.add_option('-b', '--all-branches',
                 dest='branch',action='store_true',
                 help='Expand search to all branches.')
    g.add_option('-r', '--reviewing',
                 dest='reviewing',action='store_true',
                 help='Show patches with you as a reviewer')
    g.add_option('-s', '--query-string',
                 dest='querystring', type='string', action='store', metavar='string',
                 help='Gerrit search string')

    g = p.add_option_group('Other options')
    g.add_option('--remote',
                 dest='remote', action='store_true',
                 help='Find commits on the review server rather than in your local repository')

  def Execute(self, opt, args):
    self.opt = opt
    self.args = args

    projects = self.GetProjects("")
    p = projects[0]
    r = p.GetRemote('origin')
    self.reviewUrl = r.ReviewUrl(p.UserEmail)
    self.userEmail = p.UserEmail

    if self.opt.query:
      self._doQuery()

    if self.opt.reviewers:
      self._addReviewers(self.opt.reviewers, args)

    if self.opt.abandon:
      self._abandonPatches(args)

  def _findCommits(self, args):
    commits = []
    all_branches = []
    changeIds = []
    for project in self.GetProjects(args):
      br = [project.GetUploadableBranch(x)
            for x in project.GetBranches().keys()]
      br = [x for x in br if x]
      br = [x for x in br if x.name == project.CurrentBranch]
      all_branches.extend(br)

    for branch in all_branches:
      for commit in branch.commits:
        commits.append((branch.project, commit))

    for (project, commit) in commits:
      sha = commit.split()[0]
      cid = self._getChangeIdFromCommit(project, sha)
      if cid:
        changeIds.append(cid)
    return changeIds

  def _findReviews(self):
    qs = "owner:{0} status:open".format(self.userEmail)
    gargs = ['query', '--format=JSON', '--current-patch-set', qs]
    gc = GerritCommand(self.reviewUrl, gargs, capture_stdout = True)
    gc.Wait()
    results = gc.stdout
    results = results.strip().split('\n')
    results = results[:-1] #last line is only stats
    results = [json.loads(result) for result in results]
    results.sort(key=lambda result: result['number'])
    results = [result['id'] for result in results]
    return results

  def _getChangeIdFromCommit(self, project, sha):
    cmd = ['log', '-n 1', '--pretty=format:%b', sha]
    gc = GitCommand(project, cmd, capture_stdout = True)
    gc.Wait()
    result = gc.stdout
    CHANGEID_RE = re.compile(r'.*Change-Id:(.*?)$', re.IGNORECASE | re.MULTILINE | re.DOTALL)
    m = CHANGEID_RE.match(result)
    if m:
      changeId = m.group(1).strip()
      return changeId

  def _abandonPatches(self, args):
    if self.opt.remote:
      changeIds = self._findReviews()
    else:
      changeIds = self._findCommits(args)

    question = "Abandon patch (y/N)? "
    for cid in changeIds:
      patch = self._queryCommit(cid)
      print("")
      if not patch:
        print("No review uploaded for change id {0}".format(cid))
        continue
      if self._askAboutPatch(patch, question):
        self._abandonPatch(patch['currentPatchSet']['revision'])
      else:
        print("Not abandoning patch")

  def _abandonPatch(self, revision):
    gargs = ['review', '--abandon', revision]
    GerritCommand(self.reviewUrl, gargs).Wait()

  def _addReviewers(self, people, args):
    if self.opt.remote:
      changeIds = self._findReviews()
    else:
      changeIds = self._findCommits(args)

    people = people.split(' ')
    self._askAddReview(changeIds, people)

  def _askAddReview(self, cids, people):
    question = "Add reviewer(s): {0} to commit (y/N)? ".format(", ".join(people))
    for cid in cids:
      patch = self._queryCommit(cid)
      print("")
      if not patch:
        print("No review uploaded for change id {0}".format(cid))
        continue
      if self._askAboutPatch(patch, question):
        self._gerritAddReviewers(patch['id'], people)
      else:
        print("Not adding any reviewers to patch")

  def _gerritAddReviewers(self, changeId, people):
    gargs = ['set-reviewers']
    for p in people:
      gargs.extend(['--add {0}'.format(p)])

    gargs.extend([changeId])
    gc = GerritCommand(self.reviewUrl, gargs, capture_stdout = True)
    gc.Wait()
    print(gc.stdout)

  def _askAboutPatch(self, patch, question):
    print("Subject: {0}".format(patch['subject']))
    print("Change-Id: {0}".format(patch['id']))
    sys.stdout.write(question)
    answer = sys.stdin.readline().strip().lower()
    answer = answer in ('y', 'yes', '1', 'true', 't')
    return answer

  def _queryCommit(self, changeId):
    gargs = ['query', '--current-patch-set', '--format=JSON']
    gargs.extend([changeId])
    gc = GerritCommand(self.reviewUrl, gargs, capture_stdout = True)
    gc.Wait()
    results = gc.stdout.split('\n')
    results = results[:-1]
    results = [json.loads(result) for result in results]
    if len(results) > 0:
      if 'id' in results[0]:
        return results[0]
      else:
        return None

  def _doQuery(self):
    gargs = ['query', '--all-approvals']
    qs = ''
    if self.opt.querystring:
      qs = self.opt.querystring
    if self.opt.mine:
      qs = "{0} owner:{1}".format(qs, self.userEmail)
    if self.opt.reviewing:
      qs = "{0} {1}".format(qs, self.userEmail)
    if self.opt.open:
      qs = "{0} {1}".format(qs, 'status: open')
    if len(self.args) > 0:
      project = self.GetProjects(self.args)[0]
      qs = "{0} project:{1}".format(qs, project.name)
      if not self.opt.branch:
        qs = "{0} branch:{1}".format(qs, project.revisionExpr)

    gargs.extend([qs])
    gargs.extend(['--format=JSON'])

    gc = GerritCommand(self.reviewUrl, gargs, capture_stdout = True)
    gc.Wait()
    results = gc.stdout
    results = results.strip().split('\n')
    results = results[:-1] #last line is only stats
    results = [json.loads(result) for result in results]
    results.sort(key=lambda result: result['number'])
    map(self._printResult, results)

  def _printResult(self, result):
    p = len(result['patchSets'])
    verified, code = self._getReviews(result)
    print('{0}/{1:<3d} {2: d} {3: d} {space: <3}{4:<90}{5}'.format(
      result['number'],
      p,
      verified,
      code,
      result['subject'],
      result['url'],
      space=' '))

  def _getReviews(self, result):
    p = len(result['patchSets'])
    verified = 100
    code = 100
    last = result['patchSets'][p-1]
    if not 'approvals' in last:
      return (0, 0)

    approvals = last['approvals']
    for approval in approvals:
      new = int(approval['value'])
      if "CRVW" ==  approval['type'] and code != 2:
        if new < code:
          code = new

      if "VRIF" == approval['type'] and verified != -1:
        if new < verified:
          verified = new

    code = 0 if code > 2 else code
    verified = 0 if verified > 2 else verified
    return (verified, code)

