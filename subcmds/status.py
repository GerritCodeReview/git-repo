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

try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading

import sys

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

The -j/--jobs option can be used to run multiple status queries
in parallel. If this option is used, the order of the projects
in the output will be non-deterministic.

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

  def _Options(self, p):
    p.add_option('-j', '--jobs',
                 dest='jobs', action='store', type='int', default=1,
                 help="number of projects to check simultaneously")

  def _StatusHelper(self, project, lock, sem):
    """Obtains the status for a specific project, handling locks
    and semaphores for threading. Communicates to the main
    thread using self._clean.

    Args:
      project: Project to get status of.
      lock: Lock for output and shared state.
      sem: Semaphore, will call release() when complete.
    """
    try:
      state = project.PrintWorkTreeStatus(lock)
      if state == 'CLEAN':
        lock.acquire()
        self._clean += 1
        lock.release()
    finally:
      sem.release()

  def Execute(self, opt, args):
    all = self.GetProjects(args)
    self._clean = 0

    on = {}
    for project in all:
      cb = project.CurrentBranch
      if cb:
        if cb not in on:
          on[cb] = []
        on[cb].append(project)

    branch_names = list(on.keys())
    branch_names.sort()
    for cb in branch_names:
      print '# on branch %s' % cb

    if opt.jobs == 1:
      for project in all:
        state = project.PrintWorkTreeStatus()
        if state == 'CLEAN':
          self._clean += 1
    else:
      threads = set()
      lock = _threading.Lock()
      sem = _threading.Semaphore(opt.jobs)
      for project in all:
        sem.acquire()
        t = _threading.Thread(target=self._StatusHelper,
                              args=(project, lock, sem))
        threads.add(t)
        t.start()
      for t in threads:
        t.join()
    if len(all) == self._clean:
      print 'nothing to commit (working directory clean)'
