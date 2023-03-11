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
import sys

from color import Coloring
from command import DEFAULT_LOCAL_JOBS, PagedCommand
from error import GitError
from git_command import GitCommand


class GrepColoring(Coloring):
    def __init__(self, config):
        Coloring.__init__(self, config, "grep")
        self.project = self.printer("project", attr="bold")
        self.fail = self.printer("fail", fg="red")


class Grep(PagedCommand):
    COMMON = True
    helpSummary = "Print lines matching a pattern"
    helpUsage = """
%prog {pattern | -e pattern} [<project>...]
"""
    helpDescription = """
Search for the specified patterns in all project files.

# Boolean Options

The following options can appear as often as necessary to express
the pattern to locate:

 -e PATTERN
 --and, --or, --not, -(, -)

Further, the -r/--revision option may be specified multiple times
in order to scan multiple trees.  If the same file matches in more
than one tree, only the first result is reported, prefixed by the
revision name it was found under.

# Examples

Look for a line that has '#define' and either 'MAX_PATH or 'PATH_MAX':

  repo grep -e '#define' --and -\\( -e MAX_PATH -e PATH_MAX \\)

Look for a line that has 'NODE' or 'Unexpected' in files that
contain a line that matches both expressions:

  repo grep --all-match -e NODE -e Unexpected

"""
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

    @staticmethod
    def _carry_option(_option, opt_str, value, parser):
        pt = getattr(parser.values, "cmd_argv", None)
        if pt is None:
            pt = []
            setattr(parser.values, "cmd_argv", pt)

        if opt_str == "-(":
            pt.append("(")
        elif opt_str == "-)":
            pt.append(")")
        else:
            pt.append(opt_str)

        if value is not None:
            pt.append(value)

    def _CommonOptions(self, p):
        """Override common options slightly."""
        super()._CommonOptions(p, opt_v=False)

    def _Options(self, p):
        g = p.add_option_group("Sources")
        g.add_option(
            "--cached",
            action="callback",
            callback=self._carry_option,
            help="Search the index, instead of the work tree",
        )
        g.add_option(
            "-r",
            "--revision",
            dest="revision",
            action="append",
            metavar="TREEish",
            help="Search TREEish, instead of the work tree",
        )

        g = p.add_option_group("Pattern")
        g.add_option(
            "-e",
            action="callback",
            callback=self._carry_option,
            metavar="PATTERN",
            type="str",
            help="Pattern to search for",
        )
        g.add_option(
            "-i",
            "--ignore-case",
            action="callback",
            callback=self._carry_option,
            help="Ignore case differences",
        )
        g.add_option(
            "-a",
            "--text",
            action="callback",
            callback=self._carry_option,
            help="Process binary files as if they were text",
        )
        g.add_option(
            "-I",
            action="callback",
            callback=self._carry_option,
            help="Don't match the pattern in binary files",
        )
        g.add_option(
            "-w",
            "--word-regexp",
            action="callback",
            callback=self._carry_option,
            help="Match the pattern only at word boundaries",
        )
        g.add_option(
            "-v",
            "--invert-match",
            action="callback",
            callback=self._carry_option,
            help="Select non-matching lines",
        )
        g.add_option(
            "-G",
            "--basic-regexp",
            action="callback",
            callback=self._carry_option,
            help="Use POSIX basic regexp for patterns (default)",
        )
        g.add_option(
            "-E",
            "--extended-regexp",
            action="callback",
            callback=self._carry_option,
            help="Use POSIX extended regexp for patterns",
        )
        g.add_option(
            "-F",
            "--fixed-strings",
            action="callback",
            callback=self._carry_option,
            help="Use fixed strings (not regexp) for pattern",
        )

        g = p.add_option_group("Pattern Grouping")
        g.add_option(
            "--all-match",
            action="callback",
            callback=self._carry_option,
            help="Limit match to lines that have all patterns",
        )
        g.add_option(
            "--and",
            "--or",
            "--not",
            action="callback",
            callback=self._carry_option,
            help="Boolean operators to combine patterns",
        )
        g.add_option(
            "-(",
            "-)",
            action="callback",
            callback=self._carry_option,
            help="Boolean operator grouping",
        )

        g = p.add_option_group("Output")
        g.add_option(
            "-n",
            action="callback",
            callback=self._carry_option,
            help="Prefix the line number to matching lines",
        )
        g.add_option(
            "-C",
            action="callback",
            callback=self._carry_option,
            metavar="CONTEXT",
            type="str",
            help="Show CONTEXT lines around match",
        )
        g.add_option(
            "-B",
            action="callback",
            callback=self._carry_option,
            metavar="CONTEXT",
            type="str",
            help="Show CONTEXT lines before match",
        )
        g.add_option(
            "-A",
            action="callback",
            callback=self._carry_option,
            metavar="CONTEXT",
            type="str",
            help="Show CONTEXT lines after match",
        )
        g.add_option(
            "-l",
            "--name-only",
            "--files-with-matches",
            action="callback",
            callback=self._carry_option,
            help="Show only file names containing matching lines",
        )
        g.add_option(
            "-L",
            "--files-without-match",
            action="callback",
            callback=self._carry_option,
            help="Show only file names not containing matching lines",
        )

    def _ExecuteOne(self, cmd_argv, project):
        """Process one project."""
        try:
            p = GitCommand(
                project,
                cmd_argv,
                bare=False,
                capture_stdout=True,
                capture_stderr=True,
            )
        except GitError as e:
            return (project, -1, None, str(e))

        return (project, p.Wait(), p.stdout, p.stderr)

    @staticmethod
    def _ProcessResults(full_name, have_rev, opt, _pool, out, results):
        git_failed = False
        bad_rev = False
        have_match = False
        _RelPath = lambda p: p.RelPath(local=opt.this_manifest_only)

        for project, rc, stdout, stderr in results:
            if rc < 0:
                git_failed = True
                out.project("--- project %s ---" % _RelPath(project))
                out.nl()
                out.fail("%s", stderr)
                out.nl()
                continue

            if rc:
                # no results
                if stderr:
                    if have_rev and "fatal: ambiguous argument" in stderr:
                        bad_rev = True
                    else:
                        out.project("--- project %s ---" % _RelPath(project))
                        out.nl()
                        out.fail("%s", stderr.strip())
                        out.nl()
                continue
            have_match = True

            # We cut the last element, to avoid a blank line.
            r = stdout.split("\n")
            r = r[0:-1]

            if have_rev and full_name:
                for line in r:
                    rev, line = line.split(":", 1)
                    out.write("%s", rev)
                    out.write(":")
                    out.project(_RelPath(project))
                    out.write("/")
                    out.write("%s", line)
                    out.nl()
            elif full_name:
                for line in r:
                    out.project(_RelPath(project))
                    out.write("/")
                    out.write("%s", line)
                    out.nl()
            else:
                for line in r:
                    print(line)

        return (git_failed, bad_rev, have_match)

    def Execute(self, opt, args):
        out = GrepColoring(self.manifest.manifestProject.config)

        cmd_argv = ["grep"]
        if out.is_on:
            cmd_argv.append("--color")
        cmd_argv.extend(getattr(opt, "cmd_argv", []))

        if "-e" not in cmd_argv:
            if not args:
                self.Usage()
            cmd_argv.append("-e")
            cmd_argv.append(args[0])
            args = args[1:]

        projects = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )

        full_name = False
        if len(projects) > 1:
            cmd_argv.append("--full-name")
            full_name = True

        have_rev = False
        if opt.revision:
            if "--cached" in cmd_argv:
                print(
                    "fatal: cannot combine --cached and --revision",
                    file=sys.stderr,
                )
                sys.exit(1)
            have_rev = True
            cmd_argv.extend(opt.revision)
        cmd_argv.append("--")

        git_failed, bad_rev, have_match = self.ExecuteInParallel(
            opt.jobs,
            functools.partial(self._ExecuteOne, cmd_argv),
            projects,
            callback=functools.partial(
                self._ProcessResults, full_name, have_rev, opt
            ),
            output=out,
            ordered=True,
        )

        if git_failed:
            sys.exit(1)
        elif have_match:
            sys.exit(0)
        elif have_rev and bad_rev:
            for r in opt.revision:
                print("error: can't search revision %s" % r, file=sys.stderr)
            sys.exit(1)
        else:
            sys.exit(1)
