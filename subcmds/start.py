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

class Start(Command):
  common = True
  helpSummary = "Start a new branch for development"
  helpUsage = """
%prog <newbranchname> [<project>...]

This subcommand starts a new branch of development that is automatically
pulled from a remote branch.

It is equivalent to the following git commands:

"git branch --track <newbranchname> m/<codeline>",
or 
"git checkout --track -b <newbranchname> m/<codeline>".

All three forms set up the config entries that repo bases some of its
processing on.  Use %prog or git branch or checkout with --track to ensure
the configuration data is set up properly.

"""

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    if not git.check_ref_format('heads/%s' % nb):
      print >>sys.stderr, "error: '%s' is not a valid name" % nb
      sys.exit(1)

    err = []
    for project in self.GetProjects(args[1:]):
      if not project.StartBranch(nb):
        err.append(project)

    if err:
      err.sort()
      for p in err:
        print >>sys.stderr, "error: cannot start in %s" % p.relpath
      sys.exit(1)
