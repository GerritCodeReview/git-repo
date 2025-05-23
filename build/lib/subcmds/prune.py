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

import itertools

from color import Coloring
from command import DEFAULT_LOCAL_JOBS
from command import PagedCommand


class Prune(PagedCommand):
    COMMON = True
    helpSummary = "Prune (delete) already merged topics"
    helpUsage = """
%prog [<project>...]
"""
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

    @classmethod
    def _ExecuteOne(cls, project_idx):
        """Process one project."""
        project = cls.get_parallel_context()["projects"][project_idx]
        return project.PruneHeads()

    def Execute(self, opt, args):
        projects = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )

        # NB: Should be able to refactor this module to display summary as
        # results come back from children.
        def _ProcessResults(_pool, _output, results):
            return list(itertools.chain.from_iterable(results))

        with self.ParallelContext():
            self.get_parallel_context()["projects"] = projects
            all_branches = self.ExecuteInParallel(
                opt.jobs,
                self._ExecuteOne,
                range(len(projects)),
                callback=_ProcessResults,
                ordered=True,
            )

        if not all_branches:
            return

        class Report(Coloring):
            def __init__(self, config):
                Coloring.__init__(self, config, "status")
                self.project = self.printer("header", attr="bold")

        out = Report(all_branches[0].project.config)
        out.project("Pending Branches")
        out.nl()

        project = None

        for branch in all_branches:
            if project != branch.project:
                project = branch.project
                out.nl()
                out.project(
                    "project %s/"
                    % project.RelPath(local=opt.this_manifest_only)
                )
                out.nl()

            print(
                "%s %-33s "
                % (
                    branch.name == project.CurrentBranch and "*" or " ",
                    branch.name,
                ),
                end="",
            )

            if not branch.base_exists:
                print(f"(ignoring: tracking branch is gone: {branch.base})")
            else:
                commits = branch.commits
                date = branch.date
                print(
                    "(%2d commit%s, %s)"
                    % (len(commits), len(commits) != 1 and "s" or " ", date)
                )
