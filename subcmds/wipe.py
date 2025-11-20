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
from command import UsageError
from error import GitError
from error import RepoExitError
import platform_utils
from project import DeleteWorktreeError


class WipeError(RepoExitError):
    """Exit error when wipe command fails."""


class Wipe(Command):
    """Delete projects from the worktree and .repo"""

    COMMON = True
    helpSummary = "Wipe projects from the worktree"
    helpUsage = """
%prog <project>...
"""
    helpDescription = """
The `repo wipe` command removes the specified projects from the worktree,
and deletes the project's git data from `.repo`.

This is a destructive operation and cannot be undone.
"""

    def _Options(self, p):
        p.add_option(
            "-f",
            "--force",
            action="store_true",
            help="force wipe shared projects and uncommitted changes",
        )

    def Execute(self, opt, args: List[str]):
        if not args:
            raise UsageError("no projects specified")

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
                raise WipeError(
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

        if (uncommitted_projects or shared_objdirs) and not opt.force:
            error_messages = []
            if uncommitted_projects:
                error_messages.append(
                    "The following projects have uncommitted changes or are "
                    + "corrupted:\n"
                    + "\n".join(
                        [f" - {p}" for p in sorted(uncommitted_projects)]
                    )
                )
            if shared_objdirs:
                shared_dir_messages = []
                for objdir, users in sorted(shared_objdirs.items()):
                    other_users = users - relpaths_to_wipe
                    projects_to_wipe_in_dir = users & relpaths_to_wipe
                    message = f"""Object directory {objdir} is shared by:
  Projects to be wiped: {', '.join(sorted(list(projects_to_wipe_in_dir)))}
  Projects not to be wiped: {', '.join(sorted(list(other_users)))}"""
                    shared_dir_messages.append(message)
                error_messages.append(
                    "The following projects have shared object directories:\n"
                    + "\n".join(sorted(shared_dir_messages))
                )
            error_messages.append("Use --force to wipe anyway.")
            raise WipeError("\n\n".join(error_messages))

        # If we are here, either there were no issues, or --force was used.
        # Proceed with wiping.
        successful_wipes = set()

        for project in projects_to_wipe:
            try:
                # Force the delete here since we've already performed our
                # own safety checks above.
                project.DeleteWorktree(force=True)
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
                    print(
                        f"Deleting objects directory: {objdir}", file=sys.stderr
                    )
                    platform_utils.rmtree(objdir)
