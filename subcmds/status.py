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

from command import PagedCommand

class Status(PagedCommand):
  common = True
  helpSummary = "Show the working tree status"
  helpUsage = """
%prog [<project>...]
"""
  helpDescription = """
'%prog' compares the working tree to the staging area (aka index),
and the most recent commit on this branch (HEAD), in each project
specified.  A summary is displayed, one line per file where there
is a difference between these three states.

Status Display
--------------

The status display is organized into three columns of information,
for example if the file 'subcmds/status.py' is modified in the
project 'repo' on branch 'devwork':

  project repo/                                   branch devwork
   -m     subcmds/status.py

The first column explains how the staging area (index) differs from
the last commit (HEAD).  Its values are always displayed in upper
case and have the following meanings:

 -:  no difference
 A:  added         (not in HEAD,     in index                     )
 M:  modified      (    in HEAD,     in index, different content  )
 D:  deleted       (    in HEAD, not in index                     )
 R:  renamed       (not in HEAD,     in index, path changed       )
 C:  copied        (not in HEAD,     in index, copied from another)
 T:  mode changed  (    in HEAD,     in index, same content       )
 U:  unmerged; conflict resolution required

The second column explains how the working directory differs from
the index.  Its values are always displayed in lower case and have
the following meanings:

 -:  new / unknown (not in index,     in work tree                )
 m:  modified      (    in index,     in work tree, modified      )
 d:  deleted       (    in index, not in work tree                )

"""

  def Execute(self, opt, args):
    all = self.GetProjects(args)
    clean = 0

    for project in all:
      state = project.PrintWorkTreeStatus()
      if state == 'CLEAN':
        clean += 1
    if len(all) == clean:
      print 'nothing to commit (working directory clean)'
