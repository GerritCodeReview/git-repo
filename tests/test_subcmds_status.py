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

import contextlib
import io
import os
from pathlib import Path
import subprocess
from typing import List, Tuple
from unittest import mock

import pytest
import utils_for_test

import manifest_xml
import subcmds


@pytest.fixture
def repo_client_checkout(
    tmp_path: Path,
) -> Tuple[Path, manifest_xml.XmlManifest]:
    """Create a basic repo client checkout for status tests."""
    # Create in a subdir to avoid noise (like the repo_trace file).
    topdir = tmp_path / "client_checkout"
    repodir = topdir / ".repo"
    manifest_dir = repodir / "manifests"
    manifest_file = repodir / manifest_xml.MANIFEST_FILE_NAME

    repodir.mkdir(parents=True)
    manifest_dir.mkdir()

    gitdir = repodir / "manifests.git"
    gitdir.mkdir()
    (gitdir / "config").write_text(
        """[remote "origin"]
                url = https://localhost:0/manifest
                verbose = false
            """
    )

    _init_temp_git_tree(manifest_dir)

    manifest_file.write_text(
        """
            <manifest>
                <remote name="origin" fetch="http://localhost" />
                <default remote="origin" revision="refs/heads/main" />
                <project name="proj" path="src/proj" />
            </manifest>
        """,
        encoding="utf-8",
    )

    (repodir / "projects" / "src" / "proj.git").mkdir(parents=True)
    (repodir / "project-objects" / "proj.git").mkdir(parents=True)

    worktree = topdir / "src" / "proj"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _init_temp_git_tree(worktree)

    manifest = manifest_xml.XmlManifest(str(repodir), str(manifest_file))
    return topdir, manifest


def _init_temp_git_tree(git_dir: Path) -> None:
    """Create a new git checkout with an initial commit for testing."""
    utils_for_test.init_git_tree(git_dir)
    (git_dir / "README").write_text("init")
    subprocess.check_call(["git", "add", "README"], cwd=git_dir)
    subprocess.check_call(["git", "commit", "-q", "-m", "init"], cwd=git_dir)


def _run_status(manifest: manifest_xml.XmlManifest, argv: List[str]) -> None:
    """Run the status subcommand with parsed options against a test manifest."""
    cmd = subcmds.status.Status()
    cmd.manifest = manifest
    cmd.client = mock.MagicMock(globalConfig=manifest.globalConfig)

    opts, args = cmd.OptionParser.parse_args(argv + ["--jobs=1"])
    cmd.CommonValidateOptions(opts, args)

    cmd.Execute(opts, args)


def _status_lines(output: str) -> List[str]:
    """Normalize path separators and split command output into lines."""
    return output.replace(os.sep, "/").splitlines()


def _assert_project_header(line: str, project_path: str, branch: str) -> None:
    """Assert a status project header line for a project and branch."""
    expected = f"project {(project_path + '/ '):<40}branch {branch}"
    assert line == expected


def _assert_orphan_block(lines: List[str], expected: List[str]) -> None:
    """Assert orphan block header and entries, independent of entry ordering."""
    assert lines
    assert lines[0] == ("Objects not within a project (orphans)")
    orphan_lines = lines[1:]
    assert len(orphan_lines) == len(expected)
    assert sorted(orphan_lines) == sorted(expected)


def test_orphans_basic(
    repo_client_checkout: Tuple[Path, manifest_xml.XmlManifest],
) -> None:
    """Verify -o output includes project header and orphan block."""
    topdir, manifest = repo_client_checkout
    project_path = next(iter(manifest.paths.keys()))

    (topdir / "src" / "orphan_dir").mkdir(parents=True)
    (topdir / "orphan.txt").write_text("data")

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        _run_status(manifest, ["-o"])

    lines = _status_lines(stdout.getvalue())
    _assert_project_header(lines[0], project_path, "main")
    _assert_orphan_block(
        lines[1:],
        [
            " --\torphan.txt",
            " --\tsrc/orphan_dir/",
        ],
    )


def test_empty_status_without_orphans(
    repo_client_checkout: Tuple[Path, manifest_xml.XmlManifest],
) -> None:
    """Verify clean status without -o prints only the project header line."""
    _, manifest = repo_client_checkout
    project_path = next(iter(manifest.paths.keys()))

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        _run_status(manifest, [])

    lines = _status_lines(stdout.getvalue())
    assert len(lines) == 1
    _assert_project_header(lines[0], project_path, "main")


def test_status_without_orphans(
    repo_client_checkout: Tuple[Path, manifest_xml.XmlManifest],
) -> None:
    """Verify modified tracked file appears in status output without -o."""
    topdir, manifest = repo_client_checkout
    project_path = next(iter(manifest.paths.keys()))

    (topdir / project_path / "README").write_text("updated")

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        _run_status(manifest, [])

    lines = _status_lines(stdout.getvalue())
    assert len(lines) == 2
    _assert_project_header(lines[0], project_path, "main")
    assert lines[1] == " -m\tREADME"


def test_status_with_orphans_and_modified_file(
    repo_client_checkout: Tuple[Path, manifest_xml.XmlManifest],
) -> None:
    """Verify modified-file status plus orphan block."""
    topdir, manifest = repo_client_checkout
    project_path = next(iter(manifest.paths.keys()))

    (topdir / project_path / "README").write_text("updated")
    (topdir / "src" / "orphan_dir").mkdir(parents=True)
    (topdir / "orphan.txt").write_text("data")

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        _run_status(manifest, ["-o"])

    lines = _status_lines(stdout.getvalue())
    _assert_project_header(lines[0], project_path, "main")
    assert lines[1] == " -m\tREADME"
    _assert_orphan_block(
        lines[2:],
        [
            " --\torphan.txt",
            " --\tsrc/orphan_dir/",
        ],
    )


def test_empty_status_after_start_shows_started_branch(
    repo_client_checkout: Tuple[Path, manifest_xml.XmlManifest],
) -> None:
    """Verify status shows the started branch name when the tree is clean."""
    topdir, manifest = repo_client_checkout

    project_path = next(iter(manifest.paths.keys()))
    project_worktree = topdir / project_path
    started_branch = "topic/test-status-branch"
    subprocess.check_call(
        ["git", "checkout", "-q", "-b", started_branch], cwd=project_worktree
    )

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        _run_status(manifest, [])

    lines = _status_lines(stdout.getvalue())
    assert len(lines) == 1
    _assert_project_header(lines[0], project_path, started_branch)
