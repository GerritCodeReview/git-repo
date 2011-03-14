#
# Copyright (C) 2011 The Android Open Source Project
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

from command import Command, MirrorSafeCommand

class List(Command, MirrorSafeCommand):
  common = True
  helpSummary = "List projects and their associated directories"
  helpUsage = """
%prog [<project>...]
"""
  helpDescription = """
List all projects; pass '.' to list the project for the cwd.

This is similar to running: repo forall -c 'echo "$REPO_PATH : $REPO_PROJECT"'.
"""

  def Execute(self, opt, args):
    """List all projects and the associated directories.

    This may be possible to do with 'repo forall', but repo newbies have
    trouble figuring that out.  The idea here is that it should be more
    discoverable.

    Args:
      opt: The options.  We don't take any.
      args: Positional args.  Can be a list of projects to list, or empty.
    """
    projects = self.GetProjects(args)

    lines = []
    for project in projects:
      lines.append("%s : %s" % (project.relpath, project.name))

    lines.sort()
    print '\n'.join(lines)
