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

"""Unittests for the command.py module."""

import pytest

from command import Command


class FakeProject:
    """Minimal project double for Command.GetProjects tests."""

    def __init__(
        self,
        name,
        relpath,
        *,
        gitdir=None,
        derived_subprojects=None,
        sync_s=False,
    ):
        self.name = name
        self.relpath = relpath
        self.worktree = f"/work/{relpath}"
        self.manifest = None
        self.gitdir = gitdir or f"/git/{relpath}"
        self.sync_s = sync_s
        self.Exists = True
        self._derived_subprojects = derived_subprojects or []

    def GetDerivedSubprojects(self):
        return list(self._derived_subprojects)

    def MatchesGroups(self, _groups):
        return True

    def RelPath(self, local=True):
        return self.relpath


class FakeManifest:
    """Minimal manifest double for Command.GetProjects tests."""

    def __init__(
        self,
        projects,
        *,
        all_projects=None,
        effective_groups="default",
    ):
        self.projects = list(projects)
        self.all_projects = (
            list(self.projects) if all_projects is None else list(all_projects)
        )
        self._effective_groups = effective_groups

        # all_projects may include projects owned by child manifests,
        # so only set this manifest on its direct projects.
        for project in self.projects:
            self._set_project_manifest(project)

    def _set_project_manifest(self, project):
        project.manifest = self
        for subproject in project.GetDerivedSubprojects():
            self._set_project_manifest(subproject)

    def GetManifestGroupsStr(self):
        return self._effective_groups

    def GetProjectsWithName(self, name, all_manifests=False):
        projects = self.all_projects if all_manifests else self.projects
        return [project for project in projects if project.name == name]


class GroupMatchingFakeProject(FakeProject):
    """Fake project with predictable group matches for GetProjects tests.

    This lets the tests check which groups GetProjects uses without
    reimplementing Project.MatchesGroups.
    """

    def __init__(self, name, relpath, *, matching_groups):
        super().__init__(name, relpath)
        self._matching_groups = set(matching_groups)

    def MatchesGroups(self, groups):
        return bool(self._matching_groups.intersection(groups))


def test_get_projects_keeps_derived_subprojects_for_repeated_repo():
    """Derived subprojects are keyed by checkout path, not repo identity."""
    submodule_a = FakeProject(
        "submodule",
        "src/one/submodule",
        gitdir="/shared/modules/submodule.git",
    )
    submodule_b = FakeProject(
        "submodule",
        "src/two/submodule",
        gitdir="/shared/modules/submodule.git",
    )
    project_a = FakeProject(
        "project",
        "src/one",
        derived_subprojects=[submodule_a],
        sync_s=True,
    )
    project_b = FakeProject(
        "project",
        "src/two",
        derived_subprojects=[submodule_b],
        sync_s=True,
    )
    manifest = FakeManifest([project_a, project_b])
    cmd = Command(manifest=manifest)

    projects = cmd.GetProjects([])

    assert set(projects) == {project_a, project_b, submodule_a, submodule_b}


@pytest.mark.parametrize(
    "submodules_ok, sync_s, includes_submodule",
    [
        (None, False, False),
        (None, True, True),
        (True, False, True),
        (True, True, True),
        (False, False, False),
        (False, True, False),
    ],
)
def test_get_projects_submodule_override(
    submodules_ok, sync_s, includes_submodule
):
    """The CLI override takes precedence over a project's sync-s setting."""
    submodule = FakeProject("submodule", "project/submodule")
    project = FakeProject(
        "project",
        "project",
        derived_subprojects=[submodule],
        sync_s=sync_s,
    )
    cmd = Command(manifest=FakeManifest([project]))

    projects = cmd.GetProjects([], submodules_ok=submodules_ok)

    assert (submodule in projects) is includes_submodule


@pytest.mark.parametrize(
    ("groups", "expected_relpaths"),
    [
        ("", ["outer", "sub/child"]),
        ("override-group", ["sub/override"]),
    ],
    ids=("implicit-per-manifest", "explicit-override"),
)
def test_get_projects_uses_groups_from_each_manifest_unless_overridden(
    groups, expected_relpaths
):
    """Use each manifest's effective groups unless the caller overrides them."""
    outer_project = GroupMatchingFakeProject(
        "outer",
        "outer",
        matching_groups={"outer-group"},
    )

    # Both child projects also match "outer". Reusing the outer manifest's
    # groups would therefore select both child projects.
    child_project = GroupMatchingFakeProject(
        "child",
        "sub/child",
        matching_groups={"outer-group", "child-group"},
    )
    override_project = GroupMatchingFakeProject(
        "override",
        "sub/override",
        matching_groups={"outer-group", "override-group"},
    )

    child_manifest = FakeManifest(
        [child_project, override_project],
        effective_groups="child-group",
    )
    outer_manifest = FakeManifest(
        [outer_project],
        all_projects=[outer_project, *child_manifest.projects],
        effective_groups="outer-group",
    )
    cmd = Command(manifest=outer_manifest)

    projects = cmd.GetProjects(
        [],
        manifest=outer_manifest,
        groups=groups,
        all_manifests=True,
    )

    assert [project.relpath for project in projects] == expected_relpaths


def test_get_projects_by_name_uses_groups_from_each_manifest():
    """Name matches use the groups from each project's owning manifest."""
    outer_project = GroupMatchingFakeProject(
        "shared",
        "outer/shared",
        matching_groups={"outer-group"},
    )
    child_project = GroupMatchingFakeProject(
        "shared",
        "sub/shared",
        matching_groups={"child-group"},
    )

    child_manifest = FakeManifest(
        [child_project],
        effective_groups="child-group",
    )
    outer_manifest = FakeManifest(
        [outer_project],
        all_projects=[outer_project, *child_manifest.projects],
        effective_groups="outer-group",
    )
    cmd = Command(manifest=outer_manifest)

    projects = cmd.GetProjects(
        ["shared"],
        manifest=outer_manifest,
        all_manifests=True,
    )

    assert [project.relpath for project in projects] == [
        "outer/shared",
        "sub/shared",
    ]
