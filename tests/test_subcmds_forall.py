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

import contextlib
import io
from pathlib import Path
from unittest import mock

import utils_for_test

import manifest_xml
import project
import subcmds


def _create_manifest_with_8_projects(
    topdir: Path,
) -> manifest_xml.XmlManifest:
    """Create a setup of 8 projects to execute forall."""
    repodir = topdir / ".repo"
    manifest_dir = repodir / "manifests"
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME

    repodir.mkdir()
    manifest_dir.mkdir()

    # Set up a manifest git dir for parsing to work.
    gitdir = repodir / "manifests.git"
    gitdir.mkdir()
    (gitdir / "config").write_text(
        """[remote "origin"]
            url = https://localhost:0/manifest
            verbose = false
        """
    )

    # Add the manifest data.
    manifest_file.write_text(
        """
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
        """,
        encoding="utf-8",
    )

    # Set up 8 empty projects to match the manifest.
    for x in range(1, 9):
        (repodir / "projects" / "tests" / f"path{x}.git").mkdir(parents=True)
        (repodir / "project-objects" / f"project{x}.git").mkdir(parents=True)
        git_path = topdir / "tests" / f"path{x}"
        utils_for_test.init_git_tree(git_path)

    return manifest_xml.XmlManifest(str(repodir), str(manifest_file))


def test_forall_all_projects_called_once(tmp_path: Path) -> None:
    """Test that all projects get a command run once each."""
    manifest = _create_manifest_with_8_projects(tmp_path)

    cmd = subcmds.forall.Forall()
    cmd.manifest = manifest

    # Use echo project names as the test of forall.
    opts, args = cmd.OptionParser.parse_args(["-c", "echo $REPO_PROJECT"])
    opts.verbose = False
    # Force single job to make mock of "GetRevisionId" work correctly on
    # macOS and Windows where multiprocessing is not forked and thus the
    # mock doesn't apply to the subprocesses
    opts.jobs = 1

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        # Mock to not have the Execute fail on remote check.
        with mock.patch.object(
            project.Project, "GetRevisionId", return_value="refs/heads/main"
        ):
            # Run the forall command.
            cmd.Execute(opts, args)

    output = stdout.getvalue()
    # Verify that we got every project name in the output.
    for x in range(1, 9):
        assert f"project{x}" in output

    # Split the captured output into lines to count them.
    line_count = sum(1 for x in output.splitlines() if x)
    # Verify that we didn't get more lines than expected.
    assert line_count == 8
