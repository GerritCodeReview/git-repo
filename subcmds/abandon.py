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

from collections import defaultdict
import functools
import itertools
import sys

from command import Command, DEFAULT_LOCAL_JOBS
from git_command import git
from progress import Progress


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
            dest="all",
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

    def _ExecuteOne(self, all_branches, nb, project):
        """Abandon one project."""
        if all_branches:
            branches = project.GetBranches()
        else:
            branches = nb

        ret = {}
        for name in branches:
            status = project.AbandonBranch(name)
            if status is not None:
                ret[name] = status
        return (ret, project)

    def Execute(self, opt, args):
        nb = args[0].split()
        err = defaultdict(list)
        success = defaultdict(list)
        all_projects = self.GetProjects(
            args[1:], all_manifests=not opt.this_manifest_only
        )
        _RelPath = lambda p: p.RelPath(local=opt.this_manifest_only)

        def _ProcessResults(_pool, pm, states):
            for results, project in states:
                for branch, status in results.items():
                    if status:
                        success[branch].append(project)
                    else:
                        err[branch].append(project)
                pm.update(msg="")

        self.ExecuteInParallel(
            opt.jobs,
            functools.partial(self._ExecuteOne, opt.all, nb),
            all_projects,
            callback=_ProcessResults,
            output=Progress(
                "Abandon %s" % (nb,), len(all_projects), quiet=opt.quiet
            ),
        )

        width = max(
            itertools.chain(
                [25], (len(x) for x in itertools.chain(success, err))
            )
        )
        if err:
            for br in err.keys():
                err_msg = "error: cannot abandon %s" % br
                print(err_msg, file=sys.stderr)
                for proj in err[br]:
                    print(
                        " " * len(err_msg) + " | %s" % _RelPath(proj),
                        file=sys.stderr,
                    )
            sys.exit(1)
        elif not success:
            print(
                "error: no project has local branch(es) : %s" % nb,
                file=sys.stderr,
            )
            sys.exit(1)
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
                print("%s%s| %s\n" % (br, " " * (width - len(br)), result))
