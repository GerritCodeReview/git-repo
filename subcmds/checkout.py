# Copyright (C) 2009 The Android Open Source Project
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
import multiprocessing
import sys

from command import Command, DEFAULT_LOCAL_JOBS, WORKER_BATCH_SIZE
from progress import Progress


class Checkout(Command):
  common = True
  helpSummary = "Checkout a branch for development"
  helpUsage = """
%prog <branchname> [<project>...]
"""
  helpDescription = """
The '%prog' command checks out an existing branch that was previously
created by 'repo start'.

The command is equivalent to:

  repo forall [<project>...] -c git checkout <branchname>
"""
  PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

  def ValidateOptions(self, opt, args):
    if not args:
      self.Usage()

  def _ExecuteOne(self, nb, project):
    """Checkout one project."""
    return (project.CheckoutBranch(nb), project)

  def Execute(self, opt, args):
    nb = args[0]
    err = []
    success = []
    all_projects = self.GetProjects(args[1:])

    def _ProcessResults(results):
      for status, project in results:
        if status is not None:
          if status:
            success.append(project)
          else:
            err.append(project)
        pm.update()

    pm = Progress('Checkout %s' % nb, len(all_projects))
    # NB: Multiprocessing is heavy, so don't spin it up for one job.
    if len(all_projects) == 1 or opt.jobs == 1:
      _ProcessResults(self._ExecuteOne(nb, x) for x in all_projects)
    else:
      with multiprocessing.Pool(opt.jobs) as pool:
        results = pool.imap_unordered(
            functools.partial(self._ExecuteOne, nb), all_projects,
            chunksize=WORKER_BATCH_SIZE)
        _ProcessResults(results)
    pm.end()

    if err:
      for p in err:
        print("error: %s/: cannot checkout %s" % (p.relpath, nb),
              file=sys.stderr)
      sys.exit(1)
    elif not success:
      print('error: no project has branch %s' % nb, file=sys.stderr)
      sys.exit(1)
