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

    def __init__(self, projects):
        self.projects = projects

    def GetManifestGroupsStr(self):
        return "default"


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
