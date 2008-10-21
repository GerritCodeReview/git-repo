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

class Upload(InteractiveCommand):
  common = True
  helpSummary = "Upload changes for code review"
  helpUsage="""
%prog [<project>]...
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
"""

  def _SingleBranch(self, branch):
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
      self._UploadAndReport([branch])
    else:
      _die("upload aborted by user")

  def _MultipleBranches(self, pending):
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
    self._UploadAndReport(todo)

  def _UploadAndReport(self, todo):
    have_errors = False
    for branch in todo:
      try:
        branch.UploadForReview()
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
          print >>sys.stderr, '%s' % branch.tip_url
          print >>sys.stderr, ''

    if have_errors:
      sys.exit(1)

  def Execute(self, opt, args):
    project_list = self.GetProjects(args)
    pending = []

    for project in project_list:
      avail = project.GetUploadableBranches()
      if avail:
        pending.append((project, avail))

    if not pending:
      print >>sys.stdout, "no branches ready for upload"
    elif len(pending) == 1 and len(pending[0][1]) == 1:
      self._SingleBranch(pending[0][1][0])
    else:
      self._MultipleBranches(pending)
