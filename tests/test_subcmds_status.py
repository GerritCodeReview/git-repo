# Copyright (C) 2026 The Android Open Source Project
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

"""Unittests for the status subcmd."""

from io import StringIO
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import git_command
import manifest_xml
import subcmds


class StatusOrphans(unittest.TestCase):
    """Tests for status output."""

    def setUp(self):
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="status_tests")
        self.topdir = self.tempdirobj.name
        self.repodir = os.path.join(self.topdir, ".repo")
        self.manifest_dir = os.path.join(self.repodir, "manifests")
        self.manifest_file = os.path.join(
            self.repodir, manifest_xml.MANIFEST_FILE_NAME
        )

        os.mkdir(self.repodir)
        os.mkdir(self.manifest_dir)

        gitdir = os.path.join(self.repodir, "manifests.git")
        os.mkdir(gitdir)
        with open(os.path.join(gitdir, "config"), "w") as fp:
            fp.write(
                """[remote \"origin\"]
                    url = https://localhost:0/manifest
                    verbose = false
                """
            )

        self.initTempGitTree(self.manifest_dir)

    def tearDown(self):
        self.tempdirobj.cleanup()

    def initTempGitTree(self, git_dir):
        """Create a new git checkout with an initial commit for testing."""
        cmd = ["git", "init", "-q"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            templatedir = os.path.join(self.tempdirobj.name, ".test-template")
            if not os.path.exists(templatedir):
                os.makedirs(templatedir)
                with open(os.path.join(templatedir, "HEAD"), "w") as fp:
                    fp.write("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        cmd += [git_dir]
        subprocess.check_call(cmd)

        subprocess.check_call(
            ["git", "-C", git_dir, "config", "user.email", "status@test"]
        )
        subprocess.check_call(
            ["git", "-C", git_dir, "config", "user.name", "Status Test"]
        )
        with open(os.path.join(git_dir, "README"), "w") as fp:
            fp.write("init")
        subprocess.check_call(["git", "-C", git_dir, "add", "README"])
        subprocess.check_call(
            ["git", "-C", git_dir, "commit", "-q", "-m", "init"]
        )

    def _create_manifest_with_project(self, project_inner_xml=""):
        manifest_data = f"""
                <manifest>
                    <remote name="origin" fetch="http://localhost" />
                    <default remote="origin" revision="refs/heads/main" />
                    <project name="proj" path="src/proj">
                        {project_inner_xml}
                    </project>
                </manifest>
            """
        with open(self.manifest_file, "w", encoding="utf-8") as fp:
            fp.write(manifest_data)

        os.makedirs(os.path.join(self.repodir, "projects", "src", "proj.git"))
        os.makedirs(os.path.join(self.repodir, "project-objects", "proj.git"))

        worktree = os.path.join(self.topdir, "src", "proj")
        os.makedirs(os.path.dirname(worktree), exist_ok=True)
        self.initTempGitTree(worktree)

        return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

    def _run_status(self, manifest, argv):
        cmd = subcmds.status.Status()
        cmd.manifest = manifest
        cmd.client = mock.MagicMock(globalConfig=manifest.globalConfig)

        opts, args = cmd.OptionParser.parse_args(argv)
        cmd.CommonValidateOptions(opts, args)
        opts.jobs = 1

        cmd.Execute(opts, args)

    @mock.patch("sys.stdout", new_callable=StringIO)
    def test_orphans_basic(self, mock_stdout):
        manifest = self._create_manifest_with_project()

        os.makedirs(os.path.join(self.topdir, "src", "orphan_dir"))
        with open(os.path.join(self.topdir, "orphan.txt"), "w") as fp:
            fp.write("data")

        self._run_status(manifest, ["-o"])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertIn("Objects not within a project (orphans)", output)
        self.assertIn(" --\torphan.txt", output)
        self.assertIn("src/orphan_dir/", output)

    @mock.patch("sys.stdout", new_callable=StringIO)
    def test_orphans_with_copyfile_and_linkfile(self, mock_stdout):
        manifest = self._create_manifest_with_project(
            """
            <copyfile src="README" dest="generated/copied.txt" />
            <linkfile src="README" dest="links/README.link" />
            """
        )

        with open(
            os.path.join(self.topdir, "src", "proj", "README"), "w"
        ) as fp:
            fp.write("source")

        copy_dest = os.path.join(self.topdir, "generated", "copied.txt")
        os.makedirs(os.path.dirname(copy_dest), exist_ok=True)
        with open(copy_dest, "w") as fp:
            fp.write("copied")

        link_dest = os.path.join(self.topdir, "links", "README.link")
        os.makedirs(os.path.dirname(link_dest), exist_ok=True)
        try:
            os.symlink(
                os.path.join(self.topdir, "src", "proj", "README"), link_dest
            )
        except OSError:
            with open(link_dest, "w") as fp:
                fp.write("linked")

        with open(os.path.join(self.topdir, "orphan.txt"), "w") as fp:
            fp.write("data")

        self._run_status(manifest, ["-o"])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertIn("Objects not within a project (orphans)", output)
        self.assertIn(" --\torphan.txt", output)
        self.assertIn("Objects created by copyfile", output)
        self.assertIn(" --\tgenerated/copied.txt", output)
        self.assertIn("Objects created by linkfile", output)
        self.assertIn(" --\tlinks/README.link", output)
        self.assertNotIn(
            "Objects not within a project (orphans)\n --\tgenerated/copied.txt",
            output,
        )
        self.assertNotIn(
            "Objects not within a project (orphans)\n --\tlinks/README.link",
            output,
        )

    @mock.patch("sys.stdout", new_callable=StringIO)
    def test_empty_status_without_orphans(self, mock_stdout):
        manifest = self._create_manifest_with_project()

        self._run_status(manifest, [])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertNotIn("Objects not within a project (orphans)", output)
        self.assertIn("project src/proj/", output)
        self.assertIn("branch main", output)

    @mock.patch("sys.stdout", new_callable=StringIO)
    def test_status_without_orphans(self, mock_stdout):
        manifest = self._create_manifest_with_project()

        with open(
            os.path.join(self.topdir, "src", "proj", "README"), "w"
        ) as fp:
            fp.write("updated")

        self._run_status(manifest, [])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertNotIn("Objects not within a project (orphans)", output)
        self.assertIn("project src/proj/", output)
        self.assertIn(" -m\tREADME", output)
