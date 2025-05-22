# Copyright (C) 2011 The Android Open Source Project
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

import os

from command import Command
from command import MirrorSafeCommand


class List(Command, MirrorSafeCommand):
    COMMON = True
    helpSummary = "List projects and their associated directories"
    helpUsage = """
%prog [-f] [<project>...]
%prog [-f] -r str1 [str2]...
"""
    helpDescription = """
List all projects; pass '.' to list the project for the cwd.

By default, only projects that currently exist in the checkout are shown.  If
you want to list all projects (using the specified filter settings), use the
--all option.  If you want to show all projects regardless of the manifest
groups, then also pass --groups all.

This is similar to running: repo forall -c 'echo "$REPO_PATH : $REPO_PROJECT"'.
"""

    def _Options(self, p):
        p.add_option(
            "-r",
            "--regex",
            action="store_true",
            help="filter the project list based on regex or wildcard matching "
            "of strings",
        )
        p.add_option(
            "-g",
            "--groups",
            help="filter the project list based on the groups the project is "
            "in",
        )
        p.add_option(
            "-a",
            "--all",
            action="store_true",
            help="show projects regardless of checkout state",
        )
        p.add_option(
            "-n",
            "--name-only",
            action="store_true",
            help="display only the name of the repository",
        )
        p.add_option(
            "-p",
            "--path-only",
            action="store_true",
            help="display only the path of the repository",
        )
        p.add_option(
            "-f",
            "--fullpath",
            action="store_true",
            help="display the full work tree path instead of the relative path",
        )
        p.add_option(
            "--relative-to",
            metavar="PATH",
            help="display paths relative to this one (default: top of repo "
            "client checkout)",
        )

    def ValidateOptions(self, opt, args):
        if opt.fullpath and opt.name_only:
            self.OptionParser.error("cannot combine -f and -n")

        # Resolve any symlinks so the output is stable.
        if opt.relative_to:
            opt.relative_to = os.path.realpath(opt.relative_to)

    def Execute(self, opt, args):
        """List all projects and the associated directories.

        This may be possible to do with 'repo forall', but repo newbies have
        trouble figuring that out.  The idea here is that it should be more
        discoverable.

        Args:
            opt: The options.
            args: Positional args.  Can be a list of projects to list, or empty.
        """
        if not opt.regex:
            projects = self.GetProjects(
                args,
                groups=opt.groups,
                missing_ok=opt.all,
                all_manifests=not opt.this_manifest_only,
            )
        else:
            projects = self.FindProjects(
                args, all_manifests=not opt.this_manifest_only
            )

        def _getpath(x):
            if opt.fullpath:
                return x.worktree
            if opt.relative_to:
                return os.path.relpath(x.worktree, opt.relative_to)
            return x.RelPath(local=opt.this_manifest_only)

        lines = []
        for project in projects:
            if opt.name_only and not opt.path_only:
                lines.append("%s" % (project.name))
            elif opt.path_only and not opt.name_only:
                lines.append("%s" % (_getpath(project)))
            else:
                lines.append(f"{_getpath(project)} : {project.name}")

        if lines:
            lines.sort()
            print("\n".join(lines))
