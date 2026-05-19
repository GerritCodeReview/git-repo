# Copyright (C) 2012 The Android Open Source Project
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

import enum
import functools
import io
import json
import optparse
import sys
from typing import Any, Dict, List, NamedTuple

from color import Coloring
from command import DEFAULT_LOCAL_JOBS
from command import PagedCommand
from git_refs import R_HEADS
from git_refs import R_M


class BranchInfo(NamedTuple):
    """Holds information about a branch in a project."""

    relpath: str
    name: str
    commits: Any
    date: str
    is_current: bool


class OutputFormat(enum.Enum):
    """Type for the requested output format."""

    # Human-readable text output.
    TEXT = enum.auto()

    # Machine-readable JSON output.
    JSON = enum.auto()


class _Coloring(Coloring):
    def __init__(self, config):
        Coloring.__init__(self, config, "status")


class Info(PagedCommand):
    COMMON = True
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS
    helpSummary = (
        "Get info on the manifest branch, current branch or unmerged branches"
    )
    helpUsage = "%prog [-dl] [-o [-c]] [--format=<format>] [<project>...]"

    def _Options(self, p):
        p.add_option(
            "-d",
            "--diff",
            dest="all",
            action="store_true",
            help="show full info and commit diff including remote branches",
        )
        p.add_option(
            "-o",
            "--overview",
            action="store_true",
            help="show overview of all local commits",
        )
        p.add_option(
            "--include-summary",
            action="store_true",
            default=True,
            help="include manifest summary (default: true)",
        )
        p.add_option(
            "--no-include-summary",
            dest="include_summary",
            action="store_false",
            help="exclude manifest summary",
        )
        p.add_option(
            "--include-projects",
            action="store_true",
            default=True,
            help="include project details (default: true)",
        )
        p.add_option(
            "--no-include-projects",
            dest="include_projects",
            action="store_false",
            help="exclude project details",
        )
        p.add_option(
            "-c",
            "--current-branch",
            action="store_true",
            help="consider only checked out branches",
        )
        p.add_option(
            "--no-current-branch",
            dest="current_branch",
            action="store_false",
            help="consider all local branches",
        )
        # Turn this into a warning & remove this someday.
        p.add_option(
            "-b",
            dest="current_branch",
            action="store_true",
            help=optparse.SUPPRESS_HELP,
        )
        p.add_option(
            "-l",
            "--local-only",
            dest="local",
            action="store_true",
            help="disable all remote operations",
        )
        formats = tuple(x.lower() for x in OutputFormat.__members__.keys())
        p.add_option(
            "--format",
            default=OutputFormat.TEXT.name.lower(),
            choices=formats,
            help=f"output format: {', '.join(formats)} (default: %default)",
        )

    def WantPager(self, opt):
        return OutputFormat[opt.format.upper()] == OutputFormat.TEXT

    def ValidateOptions(self, opt, args):
        output_format = OutputFormat[opt.format.upper()]
        if output_format == OutputFormat.JSON:
            if opt.all:
                self.OptionParser.error("--diff is not supported with JSON")
            if opt.overview:
                self.OptionParser.error("--overview is not supported with JSON")

    def Execute(self, opt, args):
        if not opt.this_manifest_only:
            self.manifest = self.manifest.outer_client

        output_format = OutputFormat[opt.format.upper()]
        if output_format == OutputFormat.JSON:
            self._ExecuteJson(opt, args)
        else:
            self._ExecuteText(opt, args)

    def _ExecuteText(self, opt, args) -> None:
        """Output info as human-readable text."""
        self.out = _Coloring(self.client.globalConfig)
        self.heading = self.out.printer("heading", attr="bold")
        self.headtext = self.out.nofmt_printer("headtext", fg="yellow")
        self.redtext = self.out.printer("redtext", fg="red")
        self.sha = self.out.printer("sha", fg="yellow")
        self.text = self.out.nofmt_printer("text")
        self.dimtext = self.out.printer("dimtext", attr="dim")

        self.opt = opt

        if opt.include_summary:
            self._printSummary()

        if not opt.include_projects:
            return
        elif not opt.overview:
            self._printDiffInfo(opt, args)
        else:
            self._printCommitOverview(opt, args)

    def _getSummaryData(self) -> Dict[str, Any]:
        """Gather manifest summary data as a dict."""
        manifestConfig = self.manifest.manifestProject.config
        mergeBranch = manifestConfig.GetBranch("default").merge
        manifestGroups = self.manifest.GetManifestGroupsStr()
        sp = self.manifest.superproject
        srev = sp.commit_id if sp and sp.commit_id else None
        return {
            "manifest_branch": self.manifest.default.revisionExpr or "",
            "manifest_merge_branch": mergeBranch or "",
            "manifest_groups": manifestGroups,
            "superproject_revision": srev,
        }

    def _getProjectData(self, project) -> Dict[str, Any]:
        """Gather project data as a dict."""
        data = {
            "name": project.name,
            "mount_path": project.worktree,
            "current_revision": project.GetHeadRevisionId()
            or project.GetRevisionId(),
            "manifest_revision": project.revisionExpr,
            "local_branches": list(project.GetBranches()),
        }
        currentBranch = project.CurrentBranch
        if currentBranch:
            data["current_branch"] = currentBranch
        return data

    def _ExecuteJson(self, opt, args) -> None:
        """Output info as JSON."""
        result = {}
        if opt.include_summary:
            result["summary"] = self._getSummaryData()
        if opt.include_projects:
            projs = self.GetProjects(
                args, all_manifests=not opt.this_manifest_only
            )
            result["projects"] = [self._getProjectData(p) for p in projs]

        json_settings = {
            # JSON style guide says Unicode characters are fully allowed.
            "ensure_ascii": False,
            # We use 2 space indent to match JSON style guide.
            "indent": 2,
            "separators": (",", ": "),
            "sort_keys": True,
        }
        sys.stdout.write(json.dumps(result, **json_settings) + "\n")

    def _printSummary(self) -> None:
        """Print manifest summary in text format."""
        data = self._getSummaryData()
        self.heading("Manifest branch: ")
        self.headtext(data["manifest_branch"])
        self.out.nl()
        self.heading("Manifest merge branch: ")
        self.headtext(data["manifest_merge_branch"])
        self.out.nl()
        self.heading("Manifest groups: ")
        self.headtext(data["manifest_groups"])
        self.out.nl()
        self.heading("Superproject revision: ")
        self.headtext(data["superproject_revision"] or "None")
        self.out.nl()
        self.printSeparator()

    def printSeparator(self):
        self.text("----------------------------")
        self.out.nl()

    @classmethod
    def _DiffHelper(cls, project_idx: int, opt: Any) -> str:
        """Helper for ParallelContext to get diff info for a project."""
        buf = io.StringIO()
        project = cls.get_parallel_context()["projects"][project_idx]
        config = cls.get_parallel_context()["config"]

        out = _Coloring(config)
        out.redirect(buf)

        heading = out.printer("heading", attr="bold")
        headtext = out.nofmt_printer("headtext", fg="yellow")
        redtext = out.printer("redtext", fg="red")
        sha = out.printer("sha", fg="yellow")
        text = out.nofmt_printer("text")
        dimtext = out.printer("dimtext", attr="dim")

        heading("Project: ")
        headtext(project.name)
        out.nl()

        heading("Mount path: ")
        headtext(project.worktree)
        out.nl()

        heading("Current revision: ")
        headtext(project.GetHeadRevisionId() or project.GetRevisionId())
        out.nl()

        currentBranch = project.CurrentBranch
        if currentBranch:
            heading("Current branch: ")
            headtext(currentBranch)
            out.nl()

        heading("Manifest revision: ")
        headtext(project.revisionExpr)
        out.nl()

        localBranches = list(project.GetBranches().keys())
        heading("Local Branches: ")
        redtext(str(len(localBranches)))
        if localBranches:
            text(" [")
            text(", ".join(localBranches))
            text("]")
        out.nl()

        if opt.all:
            if not opt.local:
                project.Sync_NetworkHalf(quiet=True, current_branch_only=True)

            branch = project.manifest.manifestProject.config.GetBranch(
                "default"
            ).merge
            if branch.startswith(R_HEADS):
                branch = branch[len(R_HEADS) :]
            logTarget = R_M + branch

            bareTmp = project.bare_git._bare
            project.bare_git._bare = False
            localCommits = project.bare_git.rev_list(
                "--abbrev=8",
                "--abbrev-commit",
                "--pretty=oneline",
                logTarget + "..",
                "--",
            )

            originCommits = project.bare_git.rev_list(
                "--abbrev=8",
                "--abbrev-commit",
                "--pretty=oneline",
                ".." + logTarget,
                "--",
            )
            project.bare_git._bare = bareTmp

            heading("Local Commits: ")
            redtext(str(len(localCommits)))
            dimtext(" (on current branch)")
            out.nl()

            for c in localCommits:
                split = c.split()
                sha(split[0] + " ")
                text(" ".join(split[1:]))
                out.nl()

            text("----------------------------")
            out.nl()

            heading("Remote Commits: ")
            redtext(str(len(originCommits)))
            out.nl()

            for c in originCommits:
                split = c.split()
                sha(split[0] + " ")
                text(" ".join(split[1:]))
                out.nl()

        text("----------------------------")
        out.nl()

        return buf.getvalue()

    def _printDiffInfo(self, opt, args):
        projs = self.GetProjects(args, all_manifests=not opt.this_manifest_only)

        def _ProcessResults(_pool, _output, results):
            for output in results:
                if output:
                    print(output, end="")

        with self.ParallelContext():
            self.get_parallel_context()["projects"] = projs
            self.get_parallel_context()[
                "config"
            ] = self.manifest.manifestProject.config

            self.ExecuteInParallel(
                opt.jobs,
                functools.partial(self._DiffHelper, opt=opt),
                range(len(projs)),
                callback=_ProcessResults,
                ordered=True,
                chunksize=1,
            )

    @classmethod
    def _OverviewHelper(cls, project_idx: int, opt: Any) -> List[BranchInfo]:
        """Helper to get overview of uploadable branches."""
        project = cls.get_parallel_context()["projects"][project_idx]

        branches = []
        br = [project.GetUploadableBranch(x) for x in project.GetBranches()]
        br = [x for x in br if x]
        if opt.current_branch:
            br = [x for x in br if x.name == project.CurrentBranch]

        for b in br:
            branches.append(
                BranchInfo(
                    relpath=project.RelPath(local=opt.this_manifest_only),
                    name=b.name,
                    commits=b.commits,
                    date=b.date,
                    is_current=b.name == project.CurrentBranch,
                )
            )
        return branches

    def _printCommitOverview(self, opt, args):
        projs = self.GetProjects(args, all_manifests=not opt.this_manifest_only)

        all_branches = []

        def _ProcessResults(_pool, _output, results):
            for branches in results:
                all_branches.extend(branches)

        with self.ParallelContext():
            self.get_parallel_context()["projects"] = projs

            self.ExecuteInParallel(
                opt.jobs,
                functools.partial(self._OverviewHelper, opt=opt),
                range(len(projs)),
                callback=_ProcessResults,
                ordered=True,
                chunksize=1,
            )

        if not all_branches:
            return

        self.out.nl()
        self.heading("Projects Overview")
        current_relpath = None

        for branch in all_branches:
            if current_relpath != branch.relpath:
                current_relpath = branch.relpath
                self.out.nl()
                self.headtext(current_relpath)
                self.out.nl()

            commits = branch.commits
            date = branch.date
            self.text(
                "%s %-33s (%2d commit%s, %s)"
                % (
                    branch.is_current and "*" or " ",
                    branch.name,
                    len(commits),
                    len(commits) != 1 and "s" or "",
                    date,
                )
            )
            self.out.nl()

            for commit in commits:
                split = commit.split()
                self.text(f"{'':38}{'-'} ")
                self.sha(split[0] + " ")
                self.text(" ".join(split[1:]))
                self.out.nl()
