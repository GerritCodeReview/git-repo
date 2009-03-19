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

import re
import sys

from command import InteractiveCommand
from editor import Editor
from error import UploadError

def _die(fmt, *args):
  msg = fmt % args
  print >>sys.stderr, 'error: %s' % msg
  sys.exit(1)

def _SplitEmails(values):
  result = []
  for str in values:
    result.extend([s.strip() for s in str.split(',')])
  return result

class Upload(InteractiveCommand):
  common = True
  helpSummary = "Upload changes for code review"
  helpUsage="""
%prog [--re --cc] {[<project>]... | --replace <project>}
"""
  helpDescription = """
The '%prog' command is used to send changes to the Gerrit code
review system.  It searches for changes in local projects that do
not yet exist in the corresponding remote repository.  If multiple
changes are found, '%prog' opens an editor to allow the
user to choose which change to upload.  After a successful upload,
repo prints the URL for the change in the Gerrit code review system.

'%prog' searches for uploadable changes in all projects listed
at the command line.  Projects can be specified either by name, or
by a relative or absolute path to the project's local directory. If
no projects are specified, '%prog' will search for uploadable
changes in all projects listed in the manifest.

If the --reviewers or --cc options are passed, those emails are
added to the respective list of users, and emails are sent to any
new users.  Users passed to --reviewers must be already registered
with the code review system, or the upload will fail.

If the --replace option is passed the user can designate which
existing change(s) in Gerrit match up to the commits in the branch
being uploaded.  For each matched pair of change,commit the commit
will be added as a new patch set, completely replacing the set of
files and description associated with the change in Gerrit.
"""

  def _Options(self, p):
    p.add_option('--replace',
                 dest='replace', action='store_true',
                 help='Upload replacement patchesets from this branch')
    p.add_option('--re', '--reviewers',
                 type='string',  action='append', dest='reviewers',
                 help='Request reviews from these people.')
    p.add_option('--cc',
                 type='string',  action='append', dest='cc',
                 help='Also send email to these email addresses.')

  def _SingleBranch(self, branch, people):
    project = branch.project
    name = branch.name
    date = branch.date
    list = branch.commits

    print 'Upload project %s/:' % project.relpath
    print '  branch %s (%2d commit%s, %s):' % (
                  name,
                  len(list),
                  len(list) != 1 and 's' or '',
                  date)
    for commit in list:
      print '         %s' % commit

    sys.stdout.write('(y/n)? ')
    answer = sys.stdin.readline().strip()
    if answer in ('y', 'Y', 'yes', '1', 'true', 't'):
      self._UploadAndReport([branch], people)
    else:
      _die("upload aborted by user")

  def _MultipleBranches(self, pending, people):
    projects = {}
    branches = {}

    script = []
    script.append('# Uncomment the branches to upload:')
    for project, avail in pending:
      script.append('#')
      script.append('# project %s/:' % project.relpath)

      b = {}
      for branch in avail:
        name = branch.name
        date = branch.date
        list = branch.commits

        if b:
          script.append('#')
        script.append('#  branch %s (%2d commit%s, %s):' % (
                      name,
                      len(list),
                      len(list) != 1 and 's' or '',
                      date))
        for commit in list:
          script.append('#         %s' % commit)
        b[name] = branch

      projects[project.relpath] = project
      branches[project.name] = b
    script.append('')

    script = Editor.EditString("\n".join(script)).split("\n")

    project_re = re.compile(r'^#?\s*project\s*([^\s]+)/:$')
    branch_re = re.compile(r'^\s*branch\s*([^\s(]+)\s*\(.*')

    project = None
    todo = []

    for line in script:
      m = project_re.match(line)
      if m:
        name = m.group(1)
        project = projects.get(name)
        if not project:
          _die('project %s not available for upload', name)
        continue

      m = branch_re.match(line)
      if m:
        name = m.group(1)
        if not project:
          _die('project for branch %s not in script', name)
        branch = branches[project.name].get(name)
        if not branch:
          _die('branch %s not in %s', name, project.relpath)
        todo.append(branch)
    if not todo:
      _die("nothing uncommented for upload")
    self._UploadAndReport(todo, people)

  def _ReplaceBranch(self, project, people):
    branch = project.CurrentBranch
    if not branch:
      print >>sys.stdout, "no branches ready for upload"
      return
    branch = project.GetUploadableBranch(branch)
    if not branch:
      print >>sys.stdout, "no branches ready for upload"
      return

    script = []
    script.append('# Replacing from branch %s' % branch.name)
    for commit in branch.commits:
      script.append('[      ] %s' % commit)
    script.append('')
    script.append('# Insert change numbers in the brackets to add a new patch set.')
    script.append('# To create a new change record, leave the brackets empty.')

    script = Editor.EditString("\n".join(script)).split("\n")

    change_re = re.compile(r'^\[\s*(\d{1,})\s*\]\s*([0-9a-f]{1,}) .*$')
    to_replace = dict()
    full_hashes = branch.unabbrev_commits

    for line in script:
      m = change_re.match(line)
      if m:
        c = m.group(1)
        f = m.group(2)
        try:
          f = full_hashes[f]
        except KeyError:
          print 'fh = %s' % full_hashes
          print >>sys.stderr, "error: commit %s not found" % f
          sys.exit(1)
        if c in to_replace:
          print >>sys.stderr,\
            "error: change %s cannot accept multiple commits" % c
          sys.exit(1)
        to_replace[c] = f

    if not to_replace:
      print >>sys.stderr, "error: no replacements specified"
      print >>sys.stderr, "       use 'repo upload' without --replace"
      sys.exit(1)

    branch.replace_changes = to_replace
    self._UploadAndReport([branch], people)

  def _UploadAndReport(self, todo, people):
    have_errors = False
    for branch in todo:
      try:
        branch.UploadForReview(people)
        branch.uploaded = True
      except UploadError, e:
        branch.error = e
        branch.uploaded = False
        have_errors = True

    print >>sys.stderr, ''
    print >>sys.stderr, '--------------------------------------------'

    if have_errors:
      for branch in todo:
        if not branch.uploaded:
          print >>sys.stderr, '[FAILED] %-15s %-15s  (%s)' % (
                 branch.project.relpath + '/', \
                 branch.name, \
                 branch.error)
      print >>sys.stderr, ''

    for branch in todo:
        if branch.uploaded:
          print >>sys.stderr, '[OK    ] %-15s %s' % (
                 branch.project.relpath + '/',
                 branch.name)

    if have_errors:
      sys.exit(1)

  def Execute(self, opt, args):
    project_list = self.GetProjects(args)
    pending = []
    reviewers = []
    cc = []

    if opt.reviewers:
      reviewers = _SplitEmails(opt.reviewers)
    if opt.cc:
      cc = _SplitEmails(opt.cc)
    people = (reviewers,cc)

    if opt.replace:
      if len(project_list) != 1:
        print >>sys.stderr, \
              'error: --replace requires exactly one project'
        sys.exit(1)
      self._ReplaceBranch(project_list[0], people)
      return

    for project in project_list:
      avail = project.GetUploadableBranches()
      if avail:
        pending.append((project, avail))

    if not pending:
      print >>sys.stdout, "no branches ready for upload"
    elif len(pending) == 1 and len(pending[0][1]) == 1:
      self._SingleBranch(pending[0][1][0], people)
    else:
      self._MultipleBranches(pending, people)
