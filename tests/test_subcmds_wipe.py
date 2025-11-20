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
from unittest import mock

import pytest

import project
from subcmds import wipe


def _create_mock_project(tempdir, name, objdir_path=None, has_changes=False):
    """Creates a mock project with necessary attributes and directories."""
    worktree = os.path.join(tempdir, name)
    gitdir = os.path.join(tempdir, ".repo/projects", f"{name}.git")
    if objdir_path:
        objdir = objdir_path
    else:
        objdir = os.path.join(tempdir, ".repo/project-objects", f"{name}.git")

    os.makedirs(worktree, exist_ok=True)
    os.makedirs(gitdir, exist_ok=True)
    os.makedirs(objdir, exist_ok=True)

    proj = project.Project(
        manifest=mock.MagicMock(),
        name=name,
        remote=mock.MagicMock(),
        gitdir=gitdir,
        objdir=objdir,
        worktree=worktree,
        relpath=name,
        revisionExpr="main",
        revisionId="abcd",
    )

    proj.HasChanges = mock.MagicMock(return_value=has_changes)

    def side_effect_delete_worktree(force=False, verbose=False):
        if os.path.exists(proj.worktree):
            shutil.rmtree(proj.worktree)
        if os.path.exists(proj.gitdir):
            shutil.rmtree(proj.gitdir)
        return True

    proj.DeleteWorktree = mock.MagicMock(
        side_effect=side_effect_delete_worktree
    )

    return proj


def _run_wipe(all_projects, projects_to_wipe_names, options=None):
    """Helper to run the Wipe command with mocked projects."""
    cmd = wipe.Wipe()
    cmd.manifest = mock.MagicMock()

    def get_projects_mock(projects, all_manifests=False, **kwargs):
        if projects is None:
            return all_projects
        names_to_find = set(projects)
        return [p for p in all_projects if p.name in names_to_find]

    cmd.GetProjects = mock.MagicMock(side_effect=get_projects_mock)

    if options is None:
        options = []

    opts = cmd.OptionParser.parse_args(options + projects_to_wipe_names)[0]
    cmd.CommonValidateOptions(opts, projects_to_wipe_names)
    cmd.ValidateOptions(opts, projects_to_wipe_names)
    cmd.Execute(opts, projects_to_wipe_names)


def test_wipe_single_unshared_project(tmp_path):
    """Test wiping a single project that is not shared."""
    p1 = _create_mock_project(str(tmp_path), "project/one")
    _run_wipe([p1], ["project/one"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert not os.path.exists(p1.objdir)


def test_wipe_multiple_unshared_projects(tmp_path):
    """Test wiping multiple projects that are not shared."""
    p1 = _create_mock_project(str(tmp_path), "project/one")
    p2 = _create_mock_project(str(tmp_path), "project/two")
    _run_wipe([p1, p2], ["project/one", "project/two"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert not os.path.exists(p1.objdir)
    assert not os.path.exists(p2.worktree)
    assert not os.path.exists(p2.gitdir)
    assert not os.path.exists(p2.objdir)


def test_wipe_shared_project_no_force_raises_error(tmp_path):
    """Test that wiping a shared project without --force raises an error."""
    shared_objdir = os.path.join(
        str(tmp_path), ".repo/project-objects", "shared.git"
    )
    p1 = _create_mock_project(
        str(tmp_path), "project/one", objdir_path=shared_objdir
    )
    p2 = _create_mock_project(
        str(tmp_path), "project/two", objdir_path=shared_objdir
    )

    with pytest.raises(wipe.Error) as e:
        _run_wipe([p1, p2], ["project/one"])

    assert "shared object directories" in str(e.value)
    assert "project/one" in str(e.value)
    assert "project/two" in str(e.value)

    assert os.path.exists(p1.worktree)
    assert os.path.exists(p1.gitdir)
    assert os.path.exists(p2.worktree)
    assert os.path.exists(p2.gitdir)
    assert os.path.exists(shared_objdir)


def test_wipe_shared_project_with_force(tmp_path):
    """Test wiping a shared project with --force."""
    shared_objdir = os.path.join(
        str(tmp_path), ".repo/project-objects", "shared.git"
    )
    p1 = _create_mock_project(
        str(tmp_path), "project/one", objdir_path=shared_objdir
    )
    p2 = _create_mock_project(
        str(tmp_path), "project/two", objdir_path=shared_objdir
    )

    _run_wipe([p1, p2], ["project/one"], options=["--force"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert os.path.exists(shared_objdir)
    assert os.path.exists(p2.worktree)
    assert os.path.exists(p2.gitdir)


def test_wipe_all_sharing_projects(tmp_path):
    """Test wiping all projects that share an object directory."""
    shared_objdir = os.path.join(
        str(tmp_path), ".repo/project-objects", "shared.git"
    )
    p1 = _create_mock_project(
        str(tmp_path), "project/one", objdir_path=shared_objdir
    )
    p2 = _create_mock_project(
        str(tmp_path), "project/two", objdir_path=shared_objdir
    )

    _run_wipe([p1, p2], ["project/one", "project/two"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert not os.path.exists(p2.worktree)
    assert not os.path.exists(p2.gitdir)
    assert not os.path.exists(shared_objdir)


def test_wipe_with_uncommitted_changes_raises_error(tmp_path):
    """Test wiping a project with uncommitted changes raises an error."""
    p1 = _create_mock_project(str(tmp_path), "project/one", has_changes=True)

    with pytest.raises(wipe.Error) as e:
        _run_wipe([p1], ["project/one"])

    assert "uncommitted changes" in str(e.value)
    assert "project/one" in str(e.value)

    assert os.path.exists(p1.worktree)
    assert os.path.exists(p1.gitdir)
    assert os.path.exists(p1.objdir)


def test_wipe_with_uncommitted_changes_with_force(tmp_path):
    """Test wiping a project with uncommitted changes with --force."""
    p1 = _create_mock_project(str(tmp_path), "project/one", has_changes=True)
    _run_wipe([p1], ["project/one"], options=["--force"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert not os.path.exists(p1.objdir)


def test_wipe_uncommitted_and_shared_raises_combined_error(tmp_path):
    """Test that uncommitted and shared projects raise a combined error."""
    shared_objdir = os.path.join(
        str(tmp_path), ".repo/project-objects", "shared.git"
    )
    p1 = _create_mock_project(
        str(tmp_path),
        "project/one",
        objdir_path=shared_objdir,
        has_changes=True,
    )
    p2 = _create_mock_project(
        str(tmp_path), "project/two", objdir_path=shared_objdir
    )

    with pytest.raises(wipe.Error) as e:
        _run_wipe([p1, p2], ["project/one"])

    assert "uncommitted changes" in str(e.value)
    assert "shared object directories" in str(e.value)
    assert "project/one" in str(e.value)
    assert "project/two" in str(e.value)

    assert os.path.exists(p1.worktree)
    assert os.path.exists(p1.gitdir)
    assert os.path.exists(p2.worktree)
    assert os.path.exists(p2.gitdir)
    assert os.path.exists(shared_objdir)


def test_wipe_shared_project_with_force_shared(tmp_path):
    """Test wiping a shared project with --force-shared."""
    shared_objdir = os.path.join(
        str(tmp_path), ".repo/project-objects", "shared.git"
    )
    p1 = _create_mock_project(
        str(tmp_path), "project/one", objdir_path=shared_objdir
    )
    p2 = _create_mock_project(
        str(tmp_path), "project/two", objdir_path=shared_objdir
    )

    _run_wipe([p1, p2], ["project/one"], options=["--force-shared"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert os.path.exists(shared_objdir)
    assert os.path.exists(p2.worktree)
    assert os.path.exists(p2.gitdir)


def test_wipe_with_uncommitted_changes_with_force_uncommitted(tmp_path):
    """Test wiping uncommitted changes with --force-uncommitted."""
    p1 = _create_mock_project(str(tmp_path), "project/one", has_changes=True)
    _run_wipe([p1], ["project/one"], options=["--force-uncommitted"])

    assert not os.path.exists(p1.worktree)
    assert not os.path.exists(p1.gitdir)
    assert not os.path.exists(p1.objdir)
