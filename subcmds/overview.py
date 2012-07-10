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

from color import Coloring
from command import PagedCommand


class Overview(PagedCommand):
  common = True
  helpSummary = "Display overview of unmerged project branches"
  helpUsage = """
%prog [--current-branch] [<project>...]
"""
  helpDescription = """
The '%prog' command is used to display an overview of the projects branches,
and list any local commits that have not yet been merged into the project.

The -b/--current-branch option can be used to restrict the output to only
branches currently checked out in each project.  By default, all branches
are displayed.
"""

  def _Options(self, p):
    p.add_option('-b', '--current-branch',
                 dest="current_branch", action="store_true",
                 help="Consider only checked out branches")

  def Execute(self, opt, args):
      print "Deprecated. See repo info -o"
