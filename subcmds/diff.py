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

import functools
import io
import multiprocessing

from command import DEFAULT_LOCAL_JOBS, PagedCommand, WORKER_BATCH_SIZE


class Diff(PagedCommand):
  common = True
  helpSummary = "Show changes between commit and working tree"
  helpUsage = """
%prog [<project>...]

The -u option causes '%prog' to generate diff output with file paths
relative to the repository root, so the output can be applied
to the Unix 'patch' command.
"""
  PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

  def _Options(self, p):
    super()._Options(p)
    p.add_option('-u', '--absolute',
                 dest='absolute', action='store_true',
                 help='Paths are relative to the repository root')

  def _DiffHelper(self, absolute, project):
    """Obtains the diff for a specific project.

    Args:
      absolute: Paths are relative to the root.
      project: Project to get status of.

    Returns:
      The status of the project.
    """
    buf = io.StringIO()
    ret = project.PrintWorkTreeDiff(absolute, output_redir=buf)
    return (ret, buf.getvalue())

  def Execute(self, opt, args):
    ret = 0
    all_projects = self.GetProjects(args)

    # NB: Multiprocessing is heavy, so don't spin it up for one job.
    if len(all_projects) == 1 or opt.jobs == 1:
      for project in all_projects:
        if not project.PrintWorkTreeDiff(opt.absolute):
          ret = 1
    else:
      with multiprocessing.Pool(opt.jobs) as pool:
        states = pool.imap(functools.partial(self._DiffHelper, opt.absolute),
                           all_projects, WORKER_BATCH_SIZE)
        for (state, output) in states:
          if output:
            print(output, end='')
          if not state:
            ret = 1

    return ret
