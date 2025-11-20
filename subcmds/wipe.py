# Copyright (C) 2025 The Android Open Source Project
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
import sys
from typing import List

from command import Command
from error import GitError
from error import RepoExitError
import platform_utils
from project import DeleteWorktreeError


class Error(RepoExitError):
    """Exit error when wipe command fails."""


class Wipe(Command):
    """Delete projects from the worktree and .repo"""

    COMMON = True
    helpSummary = "Wipe projects from the worktree"
    helpUsage = """
%prog <project>...
"""
    helpDescription = """
The `repo wipe` command removes the specified projects from the worktree
(the checked out source code) and deletes the project's git data from `.repo`.

This is a destructive operation and cannot be undone.

Projects can be specified either by name, or by a relative or absolute path
to the project's local directory.

Examples:
  # Wipe the project "platform/build" by name:
  $ repo wipe platform/build

  # Wipe the project at the path "build/make":
  $ repo wipe build/make
"""

    def _Options(self, p):
        # TODO(crbug.com/gerrit/393383056): Add --broken option to scan and
        # wipe broken projects.
        p.add_option(
            "-f",
            "--force",
            action="store_true",
            help="force wipe shared projects and uncommitted changes",
        )
        p.add_option(
            "--force-uncommitted",
            action="store_true",
            help="force wipe even if there are uncommitted changes",
        )
        p.add_option(
            "--force-shared",
            action="store_true",
            help="force wipe even if the project shares an object directory",
        )

    def ValidateOptions(self, opt, args: List[str]):
        if not args:
            self.Usage()

    def Execute(self, opt, args: List[str]):
        # Get all projects to handle shared object directories.
        all_projects = self.GetProjects(None, all_manifests=True, groups="all")
        projects_to_wipe = self.GetProjects(args, all_manifests=True)
        relpaths_to_wipe = {p.relpath for p in projects_to_wipe}

        # Build a map from objdir to the relpaths of projects that use it.
        objdir_map = {}
        for p in all_projects:
            objdir_map.setdefault(p.objdir, set()).add(p.relpath)

        uncommitted_projects = []
        shared_objdirs = {}
        objdirs_to_delete = set()

        for project in projects_to_wipe:
            if project == self.manifest.manifestProject:
                raise Error(
                    f"error: cannot wipe the manifest project: {project.name}"
                )

            try:
                if project.HasChanges():
                    uncommitted_projects.append(project.name)
            except GitError:
                uncommitted_projects.append(f"{project.name} (corrupted)")

            users = objdir_map.get(project.objdir, {project.relpath})
            is_shared = not users.issubset(relpaths_to_wipe)
            if is_shared:
                shared_objdirs.setdefault(project.objdir, set()).update(users)
            else:
                objdirs_to_delete.add(project.objdir)

        block_uncommitted = uncommitted_projects and not (
            opt.force or opt.force_uncommitted
        )
        block_shared = shared_objdirs and not (opt.force or opt.force_shared)

        if block_uncommitted or block_shared:
            error_messages = []
            if block_uncommitted:
                error_messages.append(
                    "The following projects have uncommitted changes or are "
                    "corrupted:\n"
                    + "\n".join(f" - {p}" for p in sorted(uncommitted_projects))
                )
            if block_shared:
                shared_dir_messages = []
                for objdir, users in sorted(shared_objdirs.items()):
                    other_users = users - relpaths_to_wipe
                    projects_to_wipe_in_dir = users & relpaths_to_wipe
                    message = f"""Object directory {objdir} is shared by:
  Projects to be wiped: {', '.join(sorted(projects_to_wipe_in_dir))}
  Projects not to be wiped: {', '.join(sorted(other_users))}"""
                    shared_dir_messages.append(message)
                error_messages.append(
                    "The following projects have shared object directories:\n"
                    + "\n".join(sorted(shared_dir_messages))
                )

            if block_uncommitted and block_shared:
                error_messages.append(
                    "Use --force to wipe anyway, or --force-uncommitted and "
                    "--force-shared to specify."
                )
            elif block_uncommitted:
                error_messages.append("Use --force-uncommitted to wipe anyway.")
            else:
                error_messages.append("Use --force-shared to wipe anyway.")

            raise Error("\n\n".join(error_messages))

        # If we are here, either there were no issues, or --force was used.
        # Proceed with wiping.
        successful_wipes = set()

        for project in projects_to_wipe:
            try:
                # Force the delete here since we've already performed our
                # own safety checks above.
                project.DeleteWorktree(force=True, verbose=opt.verbose)
                successful_wipes.add(project.relpath)
            except DeleteWorktreeError as e:
                print(
                    f"error: failed to wipe {project.name}: {e}",
                    file=sys.stderr,
                )

        # Clean up object directories only if all projects using them were
        # successfully wiped.
        for objdir in objdirs_to_delete:
            users = objdir_map.get(objdir, set())
            # Check if every project that uses this objdir has been
            # successfully processed. If a project failed to be wiped, don't
            # delete the object directory, or we'll corrupt the remaining
            # project.
            if users.issubset(successful_wipes):
                if os.path.exists(objdir):
                    if opt.verbose:
                        print(
                            f"Deleting objects directory: {objdir}",
                            file=sys.stderr,
                        )
                    platform_utils.rmtree(objdir)
