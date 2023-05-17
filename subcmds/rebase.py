# Copyright (C) 2010 The Android Open Source Project
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

import sys

from color import Coloring
from command import Command
from git_command import GitCommand


class RebaseColoring(Coloring):
    def __init__(self, config):
        Coloring.__init__(self, config, "rebase")
        self.project = self.printer("project", attr="bold")
        self.fail = self.printer("fail", fg="red")


class Rebase(Command):
    COMMON = True
    helpSummary = "Rebase local branches on upstream branch"
    helpUsage = """
%prog {[<project>...] | -i <project>...}
"""
    helpDescription = """
'%prog' uses git rebase to move local changes in the current topic branch to
the HEAD of the upstream history, useful when you have made commits in a topic
branch but need to incorporate new upstream changes "underneath" them.
"""

    def _Options(self, p):
        g = p.get_option_group("--quiet")
        g.add_option(
            "-i",
            "--interactive",
            dest="interactive",
            action="store_true",
            help="interactive rebase (single project only)",
        )

        p.add_option(
            "--fail-fast",
            dest="fail_fast",
            action="store_true",
            help="stop rebasing after first error is hit",
        )
        p.add_option(
            "-f",
            "--force-rebase",
            dest="force_rebase",
            action="store_true",
            help="pass --force-rebase to git rebase",
        )
        p.add_option(
            "--no-ff",
            dest="ff",
            default=True,
            action="store_false",
            help="pass --no-ff to git rebase",
        )
        p.add_option(
            "--autosquash",
            dest="autosquash",
            action="store_true",
            help="pass --autosquash to git rebase",
        )
        p.add_option(
            "--whitespace",
            dest="whitespace",
            action="store",
            metavar="WS",
            help="pass --whitespace to git rebase",
        )
        p.add_option(
            "--auto-stash",
            dest="auto_stash",
            action="store_true",
            help="stash local modifications before starting",
        )
        p.add_option(
            "-m",
            "--onto-manifest",
            dest="onto_manifest",
            action="store_true",
            help="rebase onto the manifest version instead of upstream "
            "HEAD (this helps to make sure the local tree stays "
            "consistent if you previously synced to a manifest)",
        )

    def Execute(self, opt, args):
        all_projects = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )
        one_project = len(all_projects) == 1

        if opt.interactive and not one_project:
            print(
                "error: interactive rebase not supported with multiple "
                "projects",
                file=sys.stderr,
            )
            if len(args) == 1:
                print(
                    "note: project %s is mapped to more than one path"
                    % (args[0],),
                    file=sys.stderr,
                )
            return 1

        # Setup the common git rebase args that we use for all projects.
        common_args = ["rebase"]
        if opt.whitespace:
            common_args.append("--whitespace=%s" % opt.whitespace)
        if opt.quiet:
            common_args.append("--quiet")
        if opt.force_rebase:
            common_args.append("--force-rebase")
        if not opt.ff:
            common_args.append("--no-ff")
        if opt.autosquash:
            common_args.append("--autosquash")
        if opt.interactive:
            common_args.append("-i")

        config = self.manifest.manifestProject.config
        out = RebaseColoring(config)
        out.redirect(sys.stdout)
        _RelPath = lambda p: p.RelPath(local=opt.this_manifest_only)

        ret = 0
        for project in all_projects:
            if ret and opt.fail_fast:
                break

            cb = project.CurrentBranch
            if not cb:
                if one_project:
                    print(
                        "error: project %s has a detached HEAD"
                        % _RelPath(project),
                        file=sys.stderr,
                    )
                    return 1
                # Ignore branches with detached HEADs.
                continue

            upbranch = project.GetBranch(cb)
            if not upbranch.LocalMerge:
                if one_project:
                    print(
                        "error: project %s does not track any remote branches"
                        % _RelPath(project),
                        file=sys.stderr,
                    )
                    return 1
                # Ignore branches without remotes.
                continue

            args = common_args[:]
            if opt.onto_manifest:
                args.append("--onto")
                args.append(project.revisionExpr)

            args.append(upbranch.LocalMerge)

            out.project(
                "project %s: rebasing %s -> %s",
                _RelPath(project),
                cb,
                upbranch.LocalMerge,
            )
            out.nl()
            out.flush()

            needs_stash = False
            if opt.auto_stash:
                stash_args = ["update-index", "--refresh", "-q"]

                if GitCommand(project, stash_args).Wait() != 0:
                    needs_stash = True
                    # Dirty index, requires stash...
                    stash_args = ["stash"]

                    if GitCommand(project, stash_args).Wait() != 0:
                        ret += 1
                        continue

            if GitCommand(project, args).Wait() != 0:
                ret += 1
                continue

            if needs_stash:
                stash_args.append("pop")
                stash_args.append("--quiet")
                if GitCommand(project, stash_args).Wait() != 0:
                    ret += 1

        if ret:
            msg_fmt = "%d projects had errors"
            self.git_event_log.ErrorEvent(msg_fmt % (ret), msg_fmt)
            out.fail(msg_fmt, ret)
            out.nl()

        return ret
