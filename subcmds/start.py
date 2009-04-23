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

import sys
from command import Command
from git_command import git
from progress import Progress

class Start(Command):
  common = True
  helpSummary = "Start a new branch for development"
  helpUsage = """
%prog <newbranchname> [--all | <project>...]
"""
  helpDescription = """
'%prog' begins a new branch of development, starting from the
revision specified in the manifest.
"""

  def _Options(self, p):
    p.add_option('--all',
                 dest='all', action='store_true',
                 help='begin branch in all projects')

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    if not git.check_ref_format('heads/%s' % nb):
      print >>sys.stderr, "error: '%s' is not a valid name" % nb
      sys.exit(1)

    err = []
    projects = []
    if not opt.all:
      projects = args[1:]
      if len(projects) < 1:
        print >>sys.stderr, "error: at least one project must be specified"
        sys.exit(1)

    all = self.GetProjects(projects)

    pm = Progress('Starting %s' % nb, len(all))
    for project in all:
      pm.update()
      if not project.StartBranch(nb):
        err.append(project)
    pm.end()

    if err:
      for p in err:
        print >>sys.stderr,\
          "error: %s/: cannot start %s" \
          % (p.relpath, nb)
      sys.exit(1)
