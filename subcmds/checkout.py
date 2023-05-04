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
import sys

from command import Command, DEFAULT_LOCAL_JOBS
from progress import Progress


class Checkout(Command):
    COMMON = True
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
        all_projects = self.GetProjects(
            args[1:], all_manifests=not opt.this_manifest_only
        )

        def _ProcessResults(_pool, pm, results):
            for status, project in results:
                if status is not None:
                    if status:
                        success.append(project)
                    else:
                        err.append(project)
                pm.update(msg="")

        self.ExecuteInParallel(
            opt.jobs,
            functools.partial(self._ExecuteOne, nb),
            all_projects,
            callback=_ProcessResults,
            output=Progress(
                "Checkout %s" % (nb,), len(all_projects), quiet=opt.quiet
            ),
        )

        if err:
            for p in err:
                print(
                    "error: %s/: cannot checkout %s" % (p.relpath, nb),
                    file=sys.stderr,
                )
            sys.exit(1)
        elif not success:
            print("error: no project has branch %s" % nb, file=sys.stderr)
            sys.exit(1)
