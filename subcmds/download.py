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

import re
import sys

from command import Command
from error import GitError
from error import NoSuchProjectError
from error import RepoExitError
from repo_logging import RepoLogger


CHANGE_RE = re.compile(r"^([1-9][0-9]*)(?:[/\.-]([1-9][0-9]*))?$")
logger = RepoLogger(__file__)


class DownloadCommandError(RepoExitError):
    """Error raised when download command fails."""


class Download(Command):
    COMMON = True
    helpSummary = "Download and checkout a change"
    helpUsage = """
%prog {[project] change[/patchset]}...
"""
    helpDescription = """
The '%prog' command downloads a change from the review system and
makes it available in your project's local working directory.
If no project is specified try to use current directory as a project.
"""

    def _Options(self, p):
        p.add_option("-b", "--branch", help="create a new branch first")
        p.add_option(
            "-c",
            "--cherry-pick",
            dest="cherrypick",
            action="store_true",
            help="cherry-pick instead of checkout",
        )
        p.add_option(
            "-x",
            "--record-origin",
            action="store_true",
            help="pass -x when cherry-picking",
        )
        p.add_option(
            "-r",
            "--revert",
            dest="revert",
            action="store_true",
            help="revert instead of checkout",
        )
        p.add_option(
            "-f",
            "--ff-only",
            dest="ffonly",
            action="store_true",
            help="force fast-forward merge",
        )

    def _ParseChangeIds(self, opt, args):
        if not args:
            self.Usage()

        to_get = []
        project = None

        for a in args:
            m = CHANGE_RE.match(a)
            if m:
                if not project:
                    project = self.GetProjects(".")[0]
                    print("Defaulting to cwd project", project.name)
                chg_id = int(m.group(1))
                if m.group(2):
                    ps_id = int(m.group(2))
                else:
                    ps_id = 1
                    refs = "refs/changes/%2.2d/%d/" % (chg_id % 100, chg_id)
                    output = project._LsRemote(refs + "*")
                    if output:
                        regex = refs + r"(\d+)"
                        rcomp = re.compile(regex, re.I)
                        for line in output.splitlines():
                            match = rcomp.search(line)
                            if match:
                                ps_id = max(int(match.group(1)), ps_id)
                to_get.append((project, chg_id, ps_id))
            else:
                projects = self.GetProjects(
                    [a], all_manifests=not opt.this_manifest_only
                )
                if len(projects) > 1:
                    # If the cwd is one of the projects, assume they want that.
                    try:
                        project = self.GetProjects(".")[0]
                    except NoSuchProjectError:
                        project = None
                    if project not in projects:
                        logger.error(
                            "error: %s matches too many projects; please "
                            "re-run inside the project checkout.",
                            a,
                        )
                        for project in projects:
                            logger.error(
                                "  %s/ @ %s",
                                project.RelPath(local=opt.this_manifest_only),
                                project.revisionExpr,
                            )
                        raise NoSuchProjectError()
                else:
                    project = projects[0]
                    print("Defaulting to cwd project", project.name)
        return to_get

    def ValidateOptions(self, opt, args):
        if opt.record_origin:
            if not opt.cherrypick:
                self.OptionParser.error(
                    "-x only makes sense with --cherry-pick"
                )

            if opt.ffonly:
                self.OptionParser.error(
                    "-x and --ff are mutually exclusive options"
                )

    def Execute(self, opt, args):
        try:
            self._ExecuteHelper(opt, args)
        except Exception as e:
            if isinstance(e, RepoExitError):
                raise e
            raise DownloadCommandError(aggregate_errors=[e])

    def _ExecuteHelper(self, opt, args):
        for project, change_id, ps_id in self._ParseChangeIds(opt, args):
            dl = project.DownloadPatchSet(change_id, ps_id)

            if not opt.revert and not dl.commits:
                logger.error(
                    "[%s] change %d/%d has already been merged",
                    project.name,
                    change_id,
                    ps_id,
                )
                continue

            if len(dl.commits) > 1:
                logger.error(
                    "[%s] %d/%d depends on %d unmerged changes:",
                    project.name,
                    change_id,
                    ps_id,
                    len(dl.commits),
                )
                for c in dl.commits:
                    print("  %s" % (c), file=sys.stderr)

            if opt.cherrypick:
                mode = "cherry-pick"
            elif opt.revert:
                mode = "revert"
            elif opt.ffonly:
                mode = "fast-forward merge"
            else:
                mode = "checkout"

            # We'll combine the branch+checkout operation, but all the rest need
            # a dedicated branch start.
            if opt.branch and mode != "checkout":
                project.StartBranch(opt.branch)

            try:
                if opt.cherrypick:
                    project._CherryPick(
                        dl.commit,
                        ffonly=opt.ffonly,
                        record_origin=opt.record_origin,
                    )
                elif opt.revert:
                    project._Revert(dl.commit)
                elif opt.ffonly:
                    project._FastForward(dl.commit, ffonly=True)
                else:
                    if opt.branch:
                        project.StartBranch(opt.branch, revision=dl.commit)
                    else:
                        project._Checkout(dl.commit)

            except GitError:
                logger.error(
                    "[%s] Could not complete the %s of %s",
                    project.name,
                    mode,
                    dl.commit,
                )
                raise
