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

"""Pytests for the status subcmd."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
from typing import List
from unittest import mock

import pytest
import utils_for_test

import manifest_xml
import subcmds


@pytest.fixture
def init_temp_git_tree():
    """Create a new git checkout with an initial commit for testing."""

    def _init_temp_git_tree(git_dir: Path) -> None:
        utils_for_test.init_git_tree(git_dir)
        (git_dir / "README").write_text("init")
        subprocess.check_call(["git", "add", "README"], cwd=git_dir)
        subprocess.check_call(
            ["git", "commit", "-q", "-m", "init"], cwd=git_dir
        )

    return _init_temp_git_tree


@pytest.fixture
def create_manifest_with_project(tmp_path, init_temp_git_tree):
    """Create a test manifest workspace and return (topdir, manifest)."""

    def _create(project_inner_xml: str = ""):
        topdir = tmp_path
        repodir = topdir / ".repo"
        manifest_dir = repodir / "manifests"
        manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME

        repodir.mkdir()
        manifest_dir.mkdir()

        gitdir = repodir / "manifests.git"
        gitdir.mkdir()
        (gitdir / "config").write_text(
            """[remote "origin"]
                url = https://localhost:0/manifest
                verbose = false
            """
        )

        init_temp_git_tree(manifest_dir)

        manifest_file.write_text(
            f"""
                <manifest>
                    <remote name="origin" fetch="http://localhost" />
                    <default remote="origin" revision="refs/heads/main" />
                    <project name="proj" path="src/proj">
                        {project_inner_xml}
                    </project>
                </manifest>
            """,
            encoding="utf-8",
        )

        (repodir / "projects" / "src" / "proj.git").mkdir(parents=True)
        (repodir / "project-objects" / "proj.git").mkdir(parents=True)

        worktree = topdir / "src" / "proj"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        init_temp_git_tree(worktree)

        manifest = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
        return topdir, manifest

    return _create


@pytest.fixture
def status_workspace(create_manifest_with_project):
    return create_manifest_with_project()


def _run_status(manifest: manifest_xml.XmlManifest, argv: List[str]) -> None:
    cmd = subcmds.status.Status()
    cmd.manifest = manifest
    cmd.client = mock.MagicMock(globalConfig=manifest.globalConfig)

    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.CommonValidateOptions(opts, args)
    opts.jobs = 1

    cmd.Execute(opts, args)


def test_orphans_basic(status_workspace) -> None:
    topdir, manifest = status_workspace

    (topdir / "src" / "orphan_dir").mkdir(parents=True)
    (topdir / "orphan.txt").write_text("data")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        _run_status(manifest, ["-o"])

    output = stdout.getvalue().replace(os.sep, "/")
    assert "Objects not within a project (orphans)" in output
    assert " --\torphan.txt" in output
    assert "src/orphan_dir/" in output


def test_orphans_with_copyfile_and_linkfile(
    create_manifest_with_project,
) -> None:
    topdir, manifest = create_manifest_with_project(
        """
        <copyfile src="README" dest="generated/copied.txt" />
        <linkfile src="README" dest="links/README.link" />
        """
    )

    (topdir / "src" / "proj" / "README").write_text("source")

    copy_dest = topdir / "generated" / "copied.txt"
    copy_dest.parent.mkdir(parents=True, exist_ok=True)
    copy_dest.write_text("copied")

    link_dest = topdir / "links" / "README.link"
    link_dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        link_dest.symlink_to(topdir / "src" / "proj" / "README")
    except OSError:
        link_dest.write_text("linked")

    (topdir / "orphan.txt").write_text("data")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        _run_status(manifest, ["-o"])

    output = stdout.getvalue().replace(os.sep, "/")
    assert "Objects not within a project (orphans)" in output
    assert " --\torphan.txt" in output
    assert "Objects created by copyfile" in output
    assert " --\tgenerated/copied.txt" in output
    assert "Objects created by linkfile" in output
    assert " --\tlinks/README.link" in output
    assert (
        "Objects not within a project (orphans)\n --\tgenerated/copied.txt"
        not in output
    )
    assert (
        "Objects not within a project (orphans)\n --\tlinks/README.link"
        not in output
    )


def test_empty_status_without_orphans(status_workspace) -> None:
    _, manifest = status_workspace

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        _run_status(manifest, [])

    output = stdout.getvalue().replace(os.sep, "/")
    assert "Objects not within a project (orphans)" not in output
    assert "project src/proj/" in output
    assert "branch main" in output


def test_status_without_orphans(status_workspace) -> None:
    topdir, manifest = status_workspace

    (topdir / "src" / "proj" / "README").write_text("updated")

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        _run_status(manifest, [])

    output = stdout.getvalue().replace(os.sep, "/")
    assert "Objects not within a project (orphans)" not in output
    assert "project src/proj/" in output
    assert " -m\tREADME" in output
