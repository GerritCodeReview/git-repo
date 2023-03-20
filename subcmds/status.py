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
import glob
import io
import os

from command import DEFAULT_LOCAL_JOBS, PagedCommand

from color import Coloring
import platform_utils


class Status(PagedCommand):
    COMMON = True
    helpSummary = "Show the working tree status"
    helpUsage = """
%prog [<project>...]
"""
    helpDescription = """
'%prog' compares the working tree to the staging area (aka index),
and the most recent commit on this branch (HEAD), in each project
specified.  A summary is displayed, one line per file where there
is a difference between these three states.

The -j/--jobs option can be used to run multiple status queries
in parallel.

The -o/--orphans option can be used to show objects that are in
the working directory, but not associated with a repo project.
This includes unmanaged top-level files and directories, but also
includes deeper items.  For example, if dir/subdir/proj1 and
dir/subdir/proj2 are repo projects, dir/subdir/proj3 will be shown
if it is not known to repo.

# Status Display

The status display is organized into three columns of information,
for example if the file 'subcmds/status.py' is modified in the
project 'repo' on branch 'devwork':

  project repo/                                   branch devwork
   -m     subcmds/status.py

The first column explains how the staging area (index) differs from
the last commit (HEAD).  Its values are always displayed in upper
case and have the following meanings:

 -:  no difference
 A:  added         (not in HEAD,     in index                     )
 M:  modified      (    in HEAD,     in index, different content  )
 D:  deleted       (    in HEAD, not in index                     )
 R:  renamed       (not in HEAD,     in index, path changed       )
 C:  copied        (not in HEAD,     in index, copied from another)
 T:  mode changed  (    in HEAD,     in index, same content       )
 U:  unmerged; conflict resolution required

The second column explains how the working directory differs from
the index.  Its values are always displayed in lower case and have
the following meanings:

 -:  new / unknown (not in index,     in work tree                )
 m:  modified      (    in index,     in work tree, modified      )
 d:  deleted       (    in index, not in work tree                )

"""
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

    def _Options(self, p):
        p.add_option(
            "-o",
            "--orphans",
            dest="orphans",
            action="store_true",
            help="include objects in working directory outside of repo "
            "projects",
        )

    def _StatusHelper(self, quiet, local, project):
        """Obtains the status for a specific project.

        Obtains the status for a project, redirecting the output to
        the specified object.

        Args:
            quiet: Where to output the status.
            local: a boolean, if True, the path is relative to the local
                (sub)manifest.  If false, the path is relative to the outermost
                manifest.
            project: Project to get status of.

        Returns:
            The status of the project.
        """
        buf = io.StringIO()
        ret = project.PrintWorkTreeStatus(
            quiet=quiet, output_redir=buf, local=local
        )
        return (ret, buf.getvalue())

    def _FindOrphans(self, dirs, proj_dirs, proj_dirs_parents, outstring):
        """find 'dirs' that are present in 'proj_dirs_parents' but not in 'proj_dirs'"""  # noqa: E501
        status_header = " --\t"
        for item in dirs:
            if not platform_utils.isdir(item):
                outstring.append("".join([status_header, item]))
                continue
            if item in proj_dirs:
                continue
            if item in proj_dirs_parents:
                self._FindOrphans(
                    glob.glob("%s/.*" % item) + glob.glob("%s/*" % item),
                    proj_dirs,
                    proj_dirs_parents,
                    outstring,
                )
                continue
            outstring.append("".join([status_header, item, "/"]))

    def Execute(self, opt, args):
        all_projects = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )

        def _ProcessResults(_pool, _output, results):
            ret = 0
            for state, output in results:
                if output:
                    print(output, end="")
                if state == "CLEAN":
                    ret += 1
            return ret

        counter = self.ExecuteInParallel(
            opt.jobs,
            functools.partial(
                self._StatusHelper, opt.quiet, opt.this_manifest_only
            ),
            all_projects,
            callback=_ProcessResults,
            ordered=True,
        )

        if not opt.quiet and len(all_projects) == counter:
            print("nothing to commit (working directory clean)")

        if opt.orphans:
            proj_dirs = set()
            proj_dirs_parents = set()
            for project in self.GetProjects(
                None, missing_ok=True, all_manifests=not opt.this_manifest_only
            ):
                relpath = project.RelPath(local=opt.this_manifest_only)
                proj_dirs.add(relpath)
                (head, _tail) = os.path.split(relpath)
                while head != "":
                    proj_dirs_parents.add(head)
                    (head, _tail) = os.path.split(head)
            proj_dirs.add(".repo")

            class StatusColoring(Coloring):
                def __init__(self, config):
                    Coloring.__init__(self, config, "status")
                    self.project = self.printer("header", attr="bold")
                    self.untracked = self.printer("untracked", fg="red")

            orig_path = os.getcwd()
            try:
                os.chdir(self.manifest.topdir)

                outstring = []
                self._FindOrphans(
                    glob.glob(".*") + glob.glob("*"),
                    proj_dirs,
                    proj_dirs_parents,
                    outstring,
                )

                if outstring:
                    output = StatusColoring(self.client.globalConfig)
                    output.project("Objects not within a project (orphans)")
                    output.nl()
                    for entry in outstring:
                        output.untracked(entry)
                        output.nl()
                else:
                    print("No orphan files or directories")

            finally:
                # Restore CWD.
                os.chdir(orig_path)
