# Copyright (C) 2024 The Android Open Source Project
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
from typing import Set

from command import Command
import platform_utils
from progress import Progress
from project import Project


class Gc(Command):
    COMMON = True
    helpSummary = "Cleaning up internal repo state."
    helpUsage = """
%prog
"""

    def _Options(self, p):
        p.add_option(
            "-n",
            "--dry-run",
            dest="dryrun",
            default=False,
            action="store_true",
            help="do everything except actually delete",
        )
        p.add_option(
            "-y",
            "--yes",
            default=False,
            action="store_true",
            help="answer yes to all safe prompts",
        )

    def _find_git_to_delete(
        self, to_keep: Set[str], start_dir: str
    ) -> Set[str]:
        """Searches no longer needed ".git" directories.

        Scans the file system starting from `start_dir` and removes all
        directories that end with ".git" that are not in the `to_keep` set.
        """
        to_delete = set()
        for root, dirs, _ in platform_utils.walk(start_dir):
            for directory in dirs:
                if not directory.endswith(".git"):
                    continue

                path = os.path.join(root, directory)
                if path not in to_keep:
                    to_delete.add(path)

        return to_delete

    def delete_unused_projects(self, projects: list[Project], opt):
        print(f"Scanning filesystem under {self.repodir}...")

        project_paths = set()
        project_object_paths = set()

        for project in projects:
            project_paths.add(project.gitdir)
            project_object_paths.add(project.objdir)

        to_delete = self._find_git_to_delete(
            project_paths, os.path.join(self.repodir, "projects")
        )

        to_delete.update(
            self._find_git_to_delete(
                project_object_paths,
                os.path.join(self.repodir, "project-objects"),
            )
        )

        if not to_delete:
            print("Nothing to clean up.")
            return 0

        print("Identified the following projects are no longer used:")
        print("\n".join(to_delete))
        print("")
        if not opt.yes:
            print(
                "If you proceed, any local commits in those projects will be "
                "destroyed!"
            )
            ask = input("Proceed? [y/N] ")
            if ask.lower() != "y":
                return 1

        pm = Progress(
            "Deleting",
            len(to_delete),
            delay=False,
            quiet=opt.quiet,
            show_elapsed=True,
            elide=True,
        )

        for path in to_delete:
            if opt.dryrun:
                print(f"\nWould have deleted ${path}")
            else:
                tmp_path = os.path.join(
                    os.path.dirname(path),
                    f"to_be_deleted_{os.path.basename(path)}",
                )
                platform_utils.rename(path, tmp_path)
                platform_utils.rmtree(tmp_path)
            pm.update(msg=path)
        pm.end()

        return 0

    def Execute(self, opt, args):
        projects: list[Project] = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )

        return self.delete_unused_projects(projects, opt)
