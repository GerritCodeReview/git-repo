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

from io import StringIO
import os
from shutil import rmtree
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
        self.tempdir = self.tempdirobj.name
        self.repodir = os.path.join(self.tempdir, ".repo")
        self.manifest_dir = os.path.join(self.repodir, "manifests")
        self.manifest_file = os.path.join(
            self.repodir, manifest_xml.MANIFEST_FILE_NAME
        )
        self.local_manifest_dir = os.path.join(
            self.repodir, manifest_xml.LOCAL_MANIFESTS_DIR_NAME
        )
        os.mkdir(self.repodir)
        os.mkdir(self.manifest_dir)

    def tearDown(self):
        """Common teardown."""
        rmtree(self.tempdir, ignore_errors=True)

    def initTempGitTree(self, git_dir):
        """Create a new empty git checkout for testing."""

        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git", "init", "-q"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init
            templatedir = os.path.join(self.tempdirobj.name, ".test-template")
            os.makedirs(templatedir)
            with open(os.path.join(templatedir, "HEAD"), "w") as fp:
                fp.write("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        cmd += [git_dir]
        subprocess.check_call(cmd)

    def getXmlManifestWith8Projects(self):
        """Create and return a setup of 8 projects with enough dummy
        files and setup to execute forall."""

        # Set up a manifest git dir for parsing to work
        gitdir = os.path.join(self.repodir, "manifests.git")
        os.mkdir(gitdir)
        with open(os.path.join(gitdir, "config"), "w") as fp:
            fp.write(
                """[remote "origin"]
                    url = https://localhost:0/manifest
                    verbose = false
                """
            )

        # Add the manifest data
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

        # Set up 8 empty projects to match the manifest
        for x in range(1, 9):
            os.makedirs(
                os.path.join(
                    self.repodir, "projects/tests/path" + str(x) + ".git"
                )
            )
            os.makedirs(
                os.path.join(
                    self.repodir, "project-objects/project" + str(x) + ".git"
                )
            )
            git_path = os.path.join(self.tempdir, "tests/path" + str(x))
            self.initTempGitTree(git_path)

        return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

    # Use mock to capture stdout from the forall run
    @unittest.mock.patch("sys.stdout", new_callable=StringIO)
    def test_forall_all_projects_called_once(self, mock_stdout):
        """Test that all projects get a command run once each."""

        manifest_with_8_projects = self.getXmlManifestWith8Projects()

        cmd = subcmds.forall.Forall()
        cmd.manifest = manifest_with_8_projects

        # Use echo project names as the test of forall
        opts, args = cmd.OptionParser.parse_args(["-c", "echo $REPO_PROJECT"])
        opts.verbose = False

        # Mock to not have the Execute fail on remote check
        with mock.patch.object(
            project.Project, "GetRevisionId", return_value="refs/heads/main"
        ):
            # Run the forall command
            cmd.Execute(opts, args)

            # Verify that we got every project name in the prints
            for x in range(1, 9):
                self.assertIn("project" + str(x), mock_stdout.getvalue())

            # Split the captured output into lines to count them
            line_count = 0
            for line in mock_stdout.getvalue().split("\n"):
                # A commented out print to stderr as a reminder
                # that stdout is mocked, include sys and uncomment if needed
                # print(line, file=sys.stderr)
                if len(line) > 0:
                    line_count += 1

            # Verify that we didn't get more lines than expected
            assert line_count == 8
