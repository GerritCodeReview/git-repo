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
from typing import NamedTuple

from command import Command
from command import DEFAULT_LOCAL_JOBS
from error import GitError
from error import RepoExitError
from progress import Progress
from repo_logging import RepoLogger


logger = RepoLogger(__file__)


class CheckoutBranchResult(NamedTuple):
    # Whether the Project is on the branch (i.e. branch exists and no errors)
    result: bool
    project_idx: int
    error: Exception


class CheckoutCommandError(RepoExitError):
    """Exception thrown when checkout command fails."""


class MissingBranchError(RepoExitError):
    """Exception thrown when no project has specified branch."""


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

    @classmethod
    def _ExecuteOne(cls, nb, project_idx):
        """Checkout one project."""
        error = None
        result = None
        project = cls.get_parallel_context()["projects"][project_idx]
        try:
            result = project.CheckoutBranch(nb)
        except GitError as e:
            error = e
        return CheckoutBranchResult(result, project_idx, error)

    def Execute(self, opt, args):
        nb = args[0]
        err = []
        err_projects = []
        success = []
        all_projects = self.GetProjects(
            args[1:], all_manifests=not opt.this_manifest_only
        )

        def _ProcessResults(_pool, pm, results):
            for result in results:
                project = all_projects[result.project_idx]
                if result.error is not None:
                    err.append(result.error)
                    err_projects.append(project)
                elif result.result:
                    success.append(project)
                pm.update(msg="")

        with self.ParallelContext():
            self.get_parallel_context()["projects"] = all_projects
            self.ExecuteInParallel(
                opt.jobs,
                functools.partial(self._ExecuteOne, nb),
                range(len(all_projects)),
                callback=_ProcessResults,
                output=Progress(
                    f"Checkout {nb}", len(all_projects), quiet=opt.quiet
                ),
            )

        if err_projects:
            for p in err_projects:
                logger.error("error: %s/: cannot checkout %s", p.relpath, nb)
            raise CheckoutCommandError(aggregate_errors=err)
        elif not success:
            msg = f"error: no project has branch {nb}"
            logger.error(msg)
            raise MissingBranchError(msg)
