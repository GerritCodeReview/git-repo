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

import json
import optparse

from color import Coloring
from command import PagedCommand
from git_refs import R_HEADS
from git_refs import R_M


class _Coloring(Coloring):
    def __init__(self, config):
        Coloring.__init__(self, config, "status")


class Info(PagedCommand):
    COMMON = True
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
        p.add_option(
            "--format",
            default="text",
            choices=("text", "json"),
            help="output format: text, json (default: %default)",
        )

    def Execute(self, opt, args):
        if not opt.this_manifest_only:
            self.manifest = self.manifest.outer_client

        if opt.format == "json":
            self._ExecuteJson(opt, args)
            return

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

    def _getSummaryData(self):
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

    def _getProjectData(self, project):
        """Gather project data as a dict."""
        data = {
            "name": project.name,
            "mount_path": project.worktree,
            "current_revision": project.GetRevisionId(),
            "manifest_revision": project.revisionExpr,
            "local_branches": list(project.GetBranches().keys()),
        }
        currentBranch = project.CurrentBranch
        if currentBranch:
            data["current_branch"] = currentBranch
        return data

    def _ExecuteJson(self, opt, args):
        """Output info as JSON."""
        result = {}
        if opt.include_summary:
            result["summary"] = self._getSummaryData()
        if opt.include_projects:
            projs = self.GetProjects(
                args, all_manifests=not opt.this_manifest_only
            )
            result["projects"] = [self._getProjectData(p) for p in projs]
        print(json.dumps(result, sort_keys=True, indent=2))

    def _printSummary(self):
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

    def _printDiffInfo(self, opt, args):
        # We let exceptions bubble up to main as they'll be well structured.
        projs = self.GetProjects(args, all_manifests=not opt.this_manifest_only)

        for p in projs:
            self.heading("Project: ")
            self.headtext(p.name)
            self.out.nl()

            self.heading("Mount path: ")
            self.headtext(p.worktree)
            self.out.nl()

            self.heading("Current revision: ")
            self.headtext(p.GetRevisionId())
            self.out.nl()

            currentBranch = p.CurrentBranch
            if currentBranch:
                self.heading("Current branch: ")
                self.headtext(currentBranch)
                self.out.nl()

            self.heading("Manifest revision: ")
            self.headtext(p.revisionExpr)
            self.out.nl()

            localBranches = list(p.GetBranches().keys())
            self.heading("Local Branches: ")
            self.redtext(str(len(localBranches)))
            if localBranches:
                self.text(" [")
                self.text(", ".join(localBranches))
                self.text("]")
            self.out.nl()

            if self.opt.all:
                self.findRemoteLocalDiff(p)

            self.printSeparator()

    def findRemoteLocalDiff(self, project):
        # Fetch all the latest commits.
        if not self.opt.local:
            project.Sync_NetworkHalf(quiet=True, current_branch_only=True)

        branch = self.manifest.manifestProject.config.GetBranch("default").merge
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

        self.heading("Local Commits: ")
        self.redtext(str(len(localCommits)))
        self.dimtext(" (on current branch)")
        self.out.nl()

        for c in localCommits:
            split = c.split()
            self.sha(split[0] + " ")
            self.text(" ".join(split[1:]))
            self.out.nl()

        self.printSeparator()

        self.heading("Remote Commits: ")
        self.redtext(str(len(originCommits)))
        self.out.nl()

        for c in originCommits:
            split = c.split()
            self.sha(split[0] + " ")
            self.text(" ".join(split[1:]))
            self.out.nl()

    def _printCommitOverview(self, opt, args):
        all_branches = []
        for project in self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        ):
            br = [project.GetUploadableBranch(x) for x in project.GetBranches()]
            br = [x for x in br if x]
            if self.opt.current_branch:
                br = [x for x in br if x.name == project.CurrentBranch]
            all_branches.extend(br)

        if not all_branches:
            return

        self.out.nl()
        self.heading("Projects Overview")
        project = None

        for branch in all_branches:
            if project != branch.project:
                project = branch.project
                self.out.nl()
                self.headtext(project.RelPath(local=opt.this_manifest_only))
                self.out.nl()

            commits = branch.commits
            date = branch.date
            self.text(
                "%s %-33s (%2d commit%s, %s)"
                % (
                    branch.name == project.CurrentBranch and "*" or " ",
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
