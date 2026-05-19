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

import collections
import functools
import itertools

from command import Command
from command import DEFAULT_LOCAL_JOBS
from error import RepoError
from error import RepoExitError
from git_command import git
from progress import Progress
from repo_logging import RepoLogger


logger = RepoLogger(__file__)


class AbandonError(RepoExitError):
    """Exit error when abandon command fails."""


class Abandon(Command):
    COMMON = True
    helpSummary = "Permanently abandon a development branch"
    helpUsage = """
%prog [--all | <branchname>] [<project>...]

This subcommand permanently abandons a development branch by
deleting it (and all its history) from your local repository.

It is equivalent to "git branch -D <branchname>".
"""
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

    def _Options(self, p):
        p.add_option(
            "--all",
            action="store_true",
            help="delete all branches in all projects",
        )

    def ValidateOptions(self, opt, args):
        if not opt.all and not args:
            self.Usage()

        if not opt.all:
            branches = args[0].split()
            invalid_branches = [
                x for x in branches if not git.check_ref_format(f"heads/{x}")
            ]

            if invalid_branches:
                self.OptionParser.error(
                    f"{invalid_branches} are not valid branch names"
                )
        else:
            args.insert(0, "'All local branches'")

    @classmethod
    def _ExecuteOne(cls, all_branches, nb, project_idx):
        """Abandon one project."""
        project = cls.get_parallel_context()["projects"][project_idx]
        if all_branches:
            branches = project.GetBranches()
        else:
            branches = nb

        ret = {}
        errors = []
        for name in branches:
            status = None
            try:
                status = project.AbandonBranch(name)
            except RepoError as e:
                status = False
                errors.append(e)
            if status is not None:
                ret[name] = status

        return (ret, project_idx, errors)

    def Execute(self, opt, args):
        nb = args[0].split()
        err = collections.defaultdict(list)
        success = collections.defaultdict(list)
        aggregate_errors = []
        all_projects = self.GetProjects(
            args[1:], all_manifests=not opt.this_manifest_only
        )
        _RelPath = lambda p: p.RelPath(local=opt.this_manifest_only)

        def _ProcessResults(_pool, pm, states):
            for results, project_idx, errors in states:
                project = all_projects[project_idx]
                for branch, status in results.items():
                    if status:
                        success[branch].append(project)
                    else:
                        err[branch].append(project)
                aggregate_errors.extend(errors)
                pm.update(msg="")

        with self.ParallelContext():
            self.get_parallel_context()["projects"] = all_projects
            self.ExecuteInParallel(
                opt.jobs,
                functools.partial(self._ExecuteOne, opt.all, nb),
                range(len(all_projects)),
                callback=_ProcessResults,
                output=Progress(
                    f"Abandon {nb}", len(all_projects), quiet=opt.quiet
                ),
                chunksize=1,
            )

        width = max(
            itertools.chain(
                [25], (len(x) for x in itertools.chain(success, err))
            )
        )
        if err:
            for br in err.keys():
                err_msg = "error: cannot abandon %s" % br
                logger.error(err_msg)
                for proj in err[br]:
                    logger.error(" " * len(err_msg) + " | %s", _RelPath(proj))
            raise AbandonError(aggregate_errors=aggregate_errors)
        elif not success:
            logger.error("error: no project has local branch(es) : %s", nb)
            raise AbandonError(aggregate_errors=aggregate_errors)
        else:
            # Everything below here is displaying status.
            if opt.quiet:
                return
            print("Abandoned branches:")
            for br in success.keys():
                if len(all_projects) > 1 and len(all_projects) == len(
                    success[br]
                ):
                    result = "all project"
                else:
                    result = "%s" % (
                        ("\n" + " " * width + "| ").join(
                            _RelPath(p) for p in success[br]
                        )
                    )
                print(f"{br}{' ' * (width - len(br))}| {result}\n")
