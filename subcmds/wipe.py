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
import shutil
from typing import List

from command import Command
from command import UsageError
from git_command import GitCommand
from project import Project


class Wipe(Command, GitCommand):
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
            help="force wipe in the case of shared projects",
        )

    def Execute(self, opt, args: List[str]):
        if not args:
            raise UsageError("no projects specified")

        # We need all projects to correctly handle shared object directories.
        all_projects = self.GetProjects(None, all_manifests=True)
        projects_to_wipe = self.GetProjects(args, all_manifests=True)
        names_to_wipe = {p.name for p in projects_to_wipe}

        # Build a map from objdir to the names of projects that use it.
        objdir_map = {}
        for p in all_projects:
            objdir_map.setdefault(p.objdir, set()).add(p.name)

        uncommitted_projects = []
        shared_objdirs = {}
        objdirs_to_delete = set()

        for project in projects_to_wipe:
            if project.HasChanges():
                uncommitted_projects.append(project.name)

            users = objdir_map.get(project.objdir, {project.name})
            is_shared = not users.issubset(names_to_wipe)
            if is_shared:
                shared_objdirs.setdefault(project.objdir, set()).update(users)
            else:
                objdirs_to_delete.add(project.objdir)

        if (uncommitted_projects or shared_objdirs) and not opt.force:
            error_messages = []
            if uncommitted_projects:
                error_messages.append(
                    "The following projects have uncommitted changes:\n - "
                    + "\n - ".join(sorted(uncommitted_projects))
                )
            if shared_objdirs:
                shared_dir_messages = []
                for objdir, users in sorted(shared_objdirs.items()):
                    other_users = users - names_to_wipe
                    projects_to_wipe_in_dir = users & names_to_wipe
                    message = f"""Object directory {objdir} is shared by:
  Wiping: {', '.join(sorted(list(projects_to_wipe_in_dir)))}
  Other projects: {', '.join(sorted(list(other_users)))}"""
                    shared_dir_messages.append(message)
                error_messages.append(
                    "The following projects have shared object directories:\n"
                    + "\n\n".join(sorted(shared_dir_messages))
                )
            error_messages.append("\nUse --force to wipe anyway.")
            raise UsageError("\n\n".join(error_messages))

        # If we are here, either there were no issues, or --force was used.
        # Proceed with wiping.
        for project in projects_to_wipe:
            self._WipeProject(project)

        for objdir in objdirs_to_delete:
            if os.path.exists(objdir):
                print(f"Deleting objects directory: {objdir}")
                shutil.rmtree(objdir)

    def _WipeProject(self, project: Project):
        """Wipes a single project's worktree and git directory."""
        if not project:
            return

        if project.worktree and os.path.exists(project.worktree):
            print(f"Deleting worktree: {project.worktree}")
            shutil.rmtree(project.worktree)

        if os.path.exists(project.gitdir):
            print(f"Deleting git directory: {project.gitdir}")
            shutil.rmtree(project.gitdir)
