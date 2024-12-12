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

"""Unittests for the forall subcmd."""

import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import git_command
import manifest_xml
import project
import subcmds


class AllCommands(unittest.TestCase):
    """Check registered all_commands."""

    def setUp(self):
        """Common setup."""
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="forall_tests")
        self.tempdir = Path(self.tempdirobj.name)
        self.repodir = self.tempdir / ".repo"
        self.manifest_dir = self.repodir / "manifests"
        self.manifest_file = str(self.repodir / manifest_xml.MANIFEST_FILE_NAME)
        self.local_manifest_dir = self.repodir / (
            manifest_xml.LOCAL_MANIFESTS_DIR_NAME
        )

        os.mkdir(self.repodir)
        os.mkdir(self.manifest_dir)

    def tearDown(self):
        """Common teardown."""
        self.tempdirobj.cleanup()

    def initTempGitTree(self, git_dir):
        """Create a new empty git checkout for testing."""

        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git", "init", "-q"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init.
            templatedir = self.tempdirobj.name / ".test-template"
            os.makedirs(templatedir)
            with open(templatedir / "HEAD", "w") as fp:
                fp.write("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        cmd += [git_dir]
        subprocess.check_call(cmd)

    def getXmlManifestWith8Projects(self):
        """Create and return a setup of 8 projects.

        The setup includes enough stub files and setup to execute forall.
        """

        # Set up a manifest git dir for parsing to work.
        gitdir = self.repodir / "manifests.git"
        os.mkdir(gitdir)
        with open(gitdir / "config", "w") as fp:
            fp.write(
                """[remote "origin"]
                    url = https://localhost:0/manifest
                    verbose = false
                """
            )

        # Add the manifest data.
        manifest_data = """
                <manifest>
                    <remote name="origin" fetch="http://localhost" />
                    <default remote="origin" revision="refs/heads/main" />
                    <project name="project1" path="tests/path1" />
                    <project name="project2" path="tests/path2" />
                    <project name="project3" path="tests/path3" />
                    <project name="project4" path="tests/path4" />
                    <project name="project5" path="tests/path5" />
                    <project name="project6" path="tests/path6" />
                    <project name="project7" path="tests/path7" />
                    <project name="project8" path="tests/path8" />
                </manifest>
            """
        with open(self.manifest_file, "w", encoding="utf-8") as fp:
            fp.write(manifest_data)

        # Set up 8 empty projects to match the manifest.
        for x in range(1, 9):
            os.makedirs(self.repodir / f"projects/tests/path{x}.git")
            os.makedirs(self.repodir / f"project-objects/project{x}.git")
            git_path = self.tempdir / f"tests/path{x}"
            self.initTempGitTree(git_path)

        return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

    # Use mock to capture stdout from the forall run.
    @unittest.mock.patch("sys.stdout", new_callable=io.StringIO)
    def test_forall_all_projects_called_once(self, mock_stdout):
        """Test that all projects get a command run once each."""

        manifest_with_8_projects = self.getXmlManifestWith8Projects()

        cmd = subcmds.forall.Forall()
        cmd.manifest = manifest_with_8_projects

        # Use echo project names as the test of forall.
        opts, args = cmd.OptionParser.parse_args(["-c", "echo $REPO_PROJECT"])
        opts.verbose = False

        # Mock to not have the Execute fail on remote check.
        with mock.patch.object(
            project.Project, "GetRevisionId", return_value="refs/heads/main"
        ):
            # Run the forall command.
            cmd.Execute(opts, args)

            # Verify that we got every project name in the prints.
            for x in range(1, 9):
                self.assertIn(f"project{x}", mock_stdout.getvalue())

            # Split the captured output into lines to count them.
            line_count = sum(
                1 if x else 0 for x in mock_stdout.getvalue().splitlines()
            )

            # Verify that we didn't get more lines than expected.
            assert line_count == 8
