# -*- coding:utf-8 -*-
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

from __future__ import print_function

import glob
import multiprocessing
import os

try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading

from command import PagedCommand

from color import Coloring
import platform_utils


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
in parallel.

The -o/--orphans option can be used to show objects that are in
the working directory, but not associated with a repo project.
This includes unmanaged top-level files and directories, but also
includes deeper items.  For example, if dir/subdir/proj1 and
dir/subdir/proj2 are repo projects, dir/subdir/proj3 will be shown
if it is not known to repo.

# Status Display

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
                 dest='jobs', action='store', type='int', default=2,
                 help="number of projects to check simultaneously")
    p.add_option('-o', '--orphans',
                 dest='orphans', action='store_true',
                 help="include objects in working directory outside of repo projects")
    p.add_option('-q', '--quiet', action='store_true',
                 help="only print the name of modified projects")

  def _StatusHelper(self, all_projects, clean_counter, next_project_index, quiet):
    """Obtains the status for some projects.

    Obtains the status for projects, redirecting the output to
    the specified object.

    Args:
      all_projects: Projects to get status of.
      clean_counter: Counter for clean projects.
      next_project_index: Index of the next project to be processed. This is used like a queue.
      quiet: Where to output the status.
    """
    while True:
      with next_project_index.get_lock():
        if next_project_index.value >= len(all_projects):
          break
        i = next_project_index.value
        next_project_index.value += 1
      project = all_projects[i]
      state = project.PrintWorkTreeStatus(quiet=quiet)
      if state == 'CLEAN':
        with clean_counter.get_lock():
          clean_counter.value += 1

  def _FindOrphans(self, dirs, proj_dirs, proj_dirs_parents, outstring):
    """find 'dirs' that are present in 'proj_dirs_parents' but not in 'proj_dirs'"""
    status_header = ' --\t'
    for item in dirs:
      if not platform_utils.isdir(item):
        outstring.append(''.join([status_header, item]))
        continue
      if item in proj_dirs:
        continue
      if item in proj_dirs_parents:
        self._FindOrphans(glob.glob('%s/.*' % item) +
                          glob.glob('%s/*' % item),
                          proj_dirs, proj_dirs_parents, outstring)
        continue
      outstring.append(''.join([status_header, item, '/']))

  def Execute(self, opt, args):
    all_projects = self.GetProjects(args)
    counter = multiprocessing.Value('i', 0)

    if opt.jobs == 1:
      for project in all_projects:
        state = project.PrintWorkTreeStatus(quiet=opt.quiet)
        if state == 'CLEAN':
          with counter.get_lock():
            counter.value += 1
    else:
      # The objects of the Project class are not pickle-able. So we cannot pass
      # them to other child processes except at the fork timing.
      if multiprocessing.get_start_method() == 'fork':
        processes = []
        next_project_index = multiprocessing.Value('i', 0)
        for _ in range(opt.jobs):
          p = multiprocessing.Process(target=self._StatusHelper,
                                      args=(all_projects, counter, next_project_index, opt.quiet))
          processes.append(p)
          p.daemon = True
          p.start()
        for p in processes:
          p.join()
      else:
        # Threads are slower than processes due to the global interpreter lock.
        threads = []
        next_project_index = multiprocessing.Value('i', 0)
        for _ in range(opt.jobs):
          t = _threading.Thread(target=self._StatusHelper,
                                args=(all_projects, counter, next_project_index, opt.quiet))
          threads.append(t)
          t.daemon = True
          t.start()
        for t in threads:
          t.join()
    if not opt.quiet and len(all_projects) == counter.value:
      print('nothing to commit (working directory clean)')

    if opt.orphans:
      proj_dirs = set()
      proj_dirs_parents = set()
      for project in self.GetProjects(None, missing_ok=True):
        proj_dirs.add(project.relpath)
        (head, _tail) = os.path.split(project.relpath)
        while head != "":
          proj_dirs_parents.add(head)
          (head, _tail) = os.path.split(head)
      proj_dirs.add('.repo')

      class StatusColoring(Coloring):
        def __init__(self, config):
          Coloring.__init__(self, config, 'status')
          self.project = self.printer('header', attr='bold')
          self.untracked = self.printer('untracked', fg='red')

      orig_path = os.getcwd()
      try:
        os.chdir(self.manifest.topdir)

        outstring = []
        self._FindOrphans(glob.glob('.*') +
                          glob.glob('*'),
                          proj_dirs, proj_dirs_parents, outstring)

        if outstring:
          output = StatusColoring(self.manifest.globalConfig)
          output.project('Objects not within a project (orphans)')
          output.nl()
          for entry in outstring:
            output.untracked(entry)
            output.nl()
        else:
          print('No orphan files or directories')

      finally:
        # Restore CWD.
        os.chdir(orig_path)
