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
from typing import NamedTuple

from command import Command
from command import DEFAULT_LOCAL_JOBS
from error import RepoExitError
from git_command import git
from git_config import IsImmutable
from progress import Progress
from project import Project
from repo_logging import RepoLogger


logger = RepoLogger(__file__)


class ExecuteOneResult(NamedTuple):
    project: Project
    error: Exception


class StartError(RepoExitError):
    """Exit error for failed start command."""


class Start(Command):
    COMMON = True
    helpSummary = "Start a new branch for development"
    helpUsage = """
%prog <newbranchname> [--all | <project>...]
"""
    helpDescription = """
'%prog' begins a new branch of development, starting from the
revision specified in the manifest.
"""
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

    def _Options(self, p):
        p.add_option(
            "--all",
            dest="all",
            action="store_true",
            help="begin branch in all projects",
        )
        p.add_option(
            "-r",
            "--rev",
            "--revision",
            dest="revision",
            help="point branch at this revision instead of upstream",
        )
        p.add_option(
            "--head",
            "--HEAD",
            dest="revision",
            action="store_const",
            const="HEAD",
            help="abbreviation for --rev HEAD",
        )

    def ValidateOptions(self, opt, args):
        if not args:
            self.Usage()

        nb = args[0]
        if not git.check_ref_format("heads/%s" % nb):
            self.OptionParser.error("'%s' is not a valid name" % nb)

    def _ExecuteOne(self, revision, nb, project):
        """Start one project."""
        # If the current revision is immutable, such as a SHA1, a tag or
        # a change, then we can't push back to it. Substitute with
        # dest_branch, if defined; or with manifest default revision instead.
        branch_merge = ""
        error = None
        if IsImmutable(project.revisionExpr):
            if project.dest_branch:
                branch_merge = project.dest_branch
            else:
                branch_merge = self.manifest.default.revisionExpr

        try:
            project.StartBranch(
                nb, branch_merge=branch_merge, revision=revision
            )
        except Exception as e:
            logger.error("error: unable to checkout %s: %s", project.name, e)
            error = e
        return ExecuteOneResult(project, error)

    def Execute(self, opt, args):
        nb = args[0]
        err_projects = []
        err = []
        projects = []
        if not opt.all:
            projects = args[1:]
            if len(projects) < 1:
                projects = ["."]  # start it in the local project by default

        all_projects = self.GetProjects(
            projects,
            all_manifests=not opt.this_manifest_only,
        )

        def _ProcessResults(_pool, pm, results):
            for result in results:
                if result.error:
                    err_projects.append(result.project)
                    err.append(result.error)
                pm.update(msg="")

        self.ExecuteInParallel(
            opt.jobs,
            functools.partial(self._ExecuteOne, opt.revision, nb),
            all_projects,
            callback=_ProcessResults,
            output=Progress(
                f"Starting {nb}", len(all_projects), quiet=opt.quiet
            ),
        )

        if err_projects:
            for p in err_projects:
                logger.error(
                    "error: %s/: cannot start %s",
                    p.RelPath(local=opt.this_manifest_only),
                    nb,
                )
            msg_fmt = "cannot start %d project(s)"
            self.git_event_log.ErrorEvent(
                msg_fmt % (len(err_projects)), msg_fmt
            )
            raise StartError(aggregate_errors=err)
