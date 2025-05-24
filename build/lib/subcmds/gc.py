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
from typing import List, Set

from command import Command
from git_command import GitCommand
import platform_utils
from progress import Progress
from project import Project


class Gc(Command):
    COMMON = True
    helpSummary = "Cleaning up internal repo and Git state."
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
        p.add_option(
            "--repack",
            default=False,
            action="store_true",
            help="repack all projects that use partial clone with "
            "filter=blob:none",
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

    def delete_unused_projects(self, projects: List[Project], opt):
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

    def _generate_promisor_files(self, pack_dir: str):
        """Generates promisor files for all pack files in the given directory.

        Promisor files are empty files with the same name as the corresponding
        pack file but with the ".promisor" extension. They are used by Git.
        """
        for root, _, files in platform_utils.walk(pack_dir):
            for file in files:
                if not file.endswith(".pack"):
                    continue
                with open(os.path.join(root, f"{file[:-4]}promisor"), "w"):
                    pass

    def repack_projects(self, projects: List[Project], opt):
        repack_projects = []
        # Find all projects eligible for repacking:
        # - can't be shared
        # - have a specific fetch filter
        for project in projects:
            if project.config.GetBoolean("extensions.preciousObjects"):
                continue
            if not project.clone_depth:
                continue
            if project.manifest.CloneFilterForDepth != "blob:none":
                continue

            repack_projects.append(project)

        if opt.dryrun:
            print(f"Would have repacked {len(repack_projects)} projects.")
            return 0

        pm = Progress(
            "Repacking (this will take a while)",
            len(repack_projects),
            delay=False,
            quiet=opt.quiet,
            show_elapsed=True,
            elide=True,
        )

        for project in repack_projects:
            pm.update(msg=f"{project.name}")

            pack_dir = os.path.join(project.gitdir, "tmp_repo_repack")
            if os.path.isdir(pack_dir):
                platform_utils.rmtree(pack_dir)
            os.mkdir(pack_dir)

            # Prepare workspace for repacking - remove all unreachable refs and
            # their objects.
            GitCommand(
                project,
                ["reflog", "expire", "--expire-unreachable=all"],
                verify_command=True,
            ).Wait()
            pm.update(msg=f"{project.name} | gc", inc=0)
            GitCommand(
                project,
                ["gc"],
                verify_command=True,
            ).Wait()

            # Get all objects that are reachable from the remote, and pack them.
            pm.update(msg=f"{project.name} | generating list of objects", inc=0)
            remote_objects_cmd = GitCommand(
                project,
                [
                    "rev-list",
                    "--objects",
                    f"--remotes={project.remote.name}",
                    "--filter=blob:none",
                    "--tags",
                ],
                capture_stdout=True,
                verify_command=True,
            )

            # Get all local objects and pack them.
            local_head_objects_cmd = GitCommand(
                project,
                ["rev-list", "--objects", "HEAD^{tree}"],
                capture_stdout=True,
                verify_command=True,
            )
            local_objects_cmd = GitCommand(
                project,
                [
                    "rev-list",
                    "--objects",
                    "--all",
                    "--reflog",
                    "--indexed-objects",
                    "--not",
                    f"--remotes={project.remote.name}",
                    "--tags",
                ],
                capture_stdout=True,
                verify_command=True,
            )

            remote_objects_cmd.Wait()

            pm.update(msg=f"{project.name} | remote repack", inc=0)
            GitCommand(
                project,
                ["pack-objects", os.path.join(pack_dir, "pack")],
                input=remote_objects_cmd.stdout,
                capture_stderr=True,
                capture_stdout=True,
                verify_command=True,
            ).Wait()

            # create promisor file for each pack file
            self._generate_promisor_files(pack_dir)

            local_head_objects_cmd.Wait()
            local_objects_cmd.Wait()

            pm.update(msg=f"{project.name} | local repack", inc=0)
            GitCommand(
                project,
                ["pack-objects", os.path.join(pack_dir, "pack")],
                input=local_head_objects_cmd.stdout + local_objects_cmd.stdout,
                capture_stderr=True,
                capture_stdout=True,
                verify_command=True,
            ).Wait()

            # Swap the old pack directory with the new one.
            platform_utils.rename(
                os.path.join(project.objdir, "objects", "pack"),
                os.path.join(project.objdir, "objects", "pack_old"),
            )
            platform_utils.rename(
                pack_dir,
                os.path.join(project.objdir, "objects", "pack"),
            )
            platform_utils.rmtree(
                os.path.join(project.objdir, "objects", "pack_old")
            )

        pm.end()
        return 0

    def Execute(self, opt, args):
        projects: List[Project] = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )

        ret = self.delete_unused_projects(projects, opt)
        if ret != 0:
            return ret

        if not opt.repack:
            return

        return self.repack_projects(projects, opt)
