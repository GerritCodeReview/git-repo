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

    def Execute(self, opt, args):
        if not args:
            raise UsageError("no projects specified")

        # We need all projects to correctly handle shared object directories.
        all_projects = self.GetAllProjects(all_manifests=True)
        projects_to_wipe = self.GetProjects(args, all_manifests=True)
        names_to_wipe = {p.name for p in projects_to_wipe}

        # Build a map from objdir to the names of projects that use it.
        objdir_map = {}
        for p in all_projects:
            objdir_map.setdefault(p.objdir, set()).add(p.name)

        objdirs_to_delete = set()
        for project in projects_to_wipe:
            users = objdir_map.get(project.objdir, {project.name})
            is_shared_with_other_projects = not users.issubset(names_to_wipe)

            if is_shared_with_other_projects and not opt.force:
                # Find an example project it's shared with for a helpful error.
                other_user = list(users - names_to_wipe)[0]
                raise UsageError(
                    f"project '{project.name}' shares object directory with "
                    f"'{other_user}' (and possibly others). Use --force to wipe."
                )

            self._WipeProject(project)

            if not is_shared_with_other_projects:
                objdirs_to_delete.add(project.objdir)

        for objdir in objdirs_to_delete:
            if os.path.exists(objdir):
                print(f"Deleting objects directory: {objdir}")
                shutil.rmtree(objdir)

    def _WipeProject(self, project):
        """Wipes a single project's worktree and git directory."""
        if not project:
            return

        # Delete the worktree.
        if project.worktree and os.path.exists(project.worktree):
            print(f"Deleting worktree: {project.worktree}")
            shutil.rmtree(project.worktree)

        # Delete the git directory.
        if os.path.exists(project.gitdir):
            print(f"Deleting git directory: {project.gitdir}")
            shutil.rmtree(project.gitdir)
