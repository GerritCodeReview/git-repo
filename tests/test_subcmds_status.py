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


def _init_temp_git_tree(git_dir: Path) -> None:
    """Create a new git checkout with an initial commit for testing."""
    utils_for_test.init_git_tree(git_dir)
    (git_dir / "README").write_text("init")
    subprocess.check_call(["git", "add", "README"], cwd=git_dir)
    subprocess.check_call(["git", "commit", "-q", "-m", "init"], cwd=git_dir)


def _create_checkout(
    tmp_path: Path,
    project_xml_fragment: str = "",
) -> Tuple[Path, manifest_xml.XmlManifest]:
    """Create a checkout and return (topdir, manifest).

    The optional |project_xml_fragment| is inserted inside the
    `<project>...</project>` element in the generated manifest so callers can
    add entries like `<copyfile>` and `<linkfile>`.
    """
    # Create in a subdir to avoid noise (like the repo_trace file).
    repo_client_checkout = utils_for_test.RepoClientCheckout(
        tmp_path / "client_checkout"
    )
    repo_client_checkout.init_manifest_git()

    _init_temp_git_tree(repo_client_checkout.manifest_dir)

    repo_client_checkout.write_manifest(
        f"""
            <manifest>
                <remote name="origin" fetch="http://localhost" />
                <default remote="origin" revision="refs/heads/main" />
                <project name="proj" path="src/proj">
                    {project_xml_fragment}
                </project>
            </manifest>
        """,
    )

    worktree = repo_client_checkout.create_project(
        name="proj",
        path="src/proj",
        init_worktree=False,
    )
    _init_temp_git_tree(worktree)

    return (
        repo_client_checkout.topdir,
        repo_client_checkout.xml_manifest(),
    )


@pytest.fixture
def repo_client_checkout(
    tmp_path: Path,
) -> Tuple[Path, manifest_xml.XmlManifest]:
    """Create a basic repo client checkout for status tests."""
    return _create_checkout(tmp_path)


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


def _assert_block(lines: List[str], header: str, expected: List[str]) -> None:
    """Assert a section header and entries, with order-independent entries."""
    assert lines
    assert lines[0] == header
    entries = lines[1:]
    assert len(entries) == len(expected)
    assert sorted(entries) == sorted(expected)


def _assert_orphan_block(lines: List[str], expected: List[str]) -> None:
    """Assert orphan block header and entries, independent of entry ordering."""
    _assert_block(lines, "Objects not within a project (orphans)", expected)


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


def test_orphans_with_copyfile_and_linkfile(tmp_path: Path) -> None:
    """Verify copyfile/linkfile outputs are reported outside orphan entries."""
    topdir, manifest = _create_checkout(
        tmp_path,
        """
        <copyfile src="README" dest="generated/copied.txt" />
        <linkfile src="README" dest="links/README.link" />
        """,
    )
    project_path = next(iter(manifest.paths.keys()))

    copy_dest = topdir / "generated" / "copied.txt"
    copy_dest.parent.mkdir(parents=True, exist_ok=True)
    copy_dest.write_text("copied")

    link_dest = topdir / "links" / "README.link"
    link_dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        link_dest.symlink_to(topdir / project_path / "README")
    except OSError:
        link_dest.write_text("linked")

    (topdir / "orphan.txt").write_text("data")

    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        _run_status(manifest, ["-o"])

    lines = _status_lines(stdout.getvalue())
    _assert_project_header(lines[0], project_path, "main")

    copy_idx = lines.index("Objects created by copyfile")
    link_idx = lines.index("Objects created by linkfile")

    _assert_orphan_block(
        lines[1:copy_idx],
        [
            " --\torphan.txt",
        ],
    )
    _assert_block(
        lines[copy_idx:link_idx],
        "Objects created by copyfile",
        [" --\tgenerated/copied.txt"],
    )
    _assert_block(
        lines[link_idx:],
        "Objects created by linkfile",
        [" --\tlinks/README.link"],
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
