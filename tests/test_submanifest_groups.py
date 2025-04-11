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

"""Unittests for the manifest_xml.py module.

Tests for submanifest parsing, filtering and default-groups string
in XmlManifest.
"""

import os
import shutil
import tempfile
import unittest

from manifest_xml import XmlManifest
from error import ManifestParseError


# Utility function to generate the main manifest XML.
def get_main_manifest(submanifest_line):
    return f"""
    <manifest>
      <remote name="origin" fetch="." />
      <default remote="origin" revision="main" />
      <project name="dummy/project" path="unused" />
      {submanifest_line}
    </manifest>
    """.strip()


# Utility function to generate submanifest XML.
def get_submanifest_manifest(projects_xml):
    return f"""
    <manifest>
      <remote name="origin" fetch="." />
      <default remote="origin" revision="main" />
      {projects_xml}
    </manifest>
    """.strip()


# Utility function to parse a project's groups into a set.
def parse_groups(proj):
    if isinstance(proj.groups, str):
        return set(g.strip() for g in proj.groups.split(","))
    return set(proj.groups)


def submanifest_repo_structure():
    """
    Sets up a valid .repo structure for testing XmlManifest with submanifests.

    This function creates a temporary repo root with a .repo directory,
    a 'manifests.git' directory (with a dummy config for remote "origin"),
    and a submanifest directory.

    Returns a dict with:
      - repo_root: root directory of the repository
      - repodir:   path to the .repo directory
      - manifest_path: path to the main manifest file (.repo/manifest.xml)
      - submanifest_dir: path to the submanifest directory
        (.repo/submanifests/submanifest_dir)
      - tempdirobj: TemporaryDirectory object for cleanup.
    """
    tempdirobj = tempfile.TemporaryDirectory(prefix="repo_tests")
    repo_root = tempdirobj.name
    dot_repo = os.path.join(repo_root, ".repo")
    manifests_git = os.path.join(dot_repo, "manifests.git")
    submanifest_dir = os.path.join(dot_repo, "submanifests", "submanifest_dir")

    os.makedirs(manifests_git, exist_ok=True)
    os.makedirs(submanifest_dir, exist_ok=True)

    # Create dummy git config for remote "origin"
    with open(os.path.join(manifests_git, "config"), "w") as f:
        f.write(
            """[remote "origin"]
    url = https://localhost:0/manifest
"""
        )

    # Write a basic main manifest (to be overridden by tests if needed)
    manifest_content = """
    <manifest>
      <remote name="origin" fetch="." />
      <default remote="origin" revision="main" />
      <project name="dummy/project" path="unused" />
    </manifest>
    """
    manifest_path = os.path.join(dot_repo, "manifest.xml")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_content.strip())

    return {
        "repo_root": repo_root,
        "repodir": dot_repo,
        "manifest_path": manifest_path,
        "submanifest_dir": submanifest_dir,
        "tempdirobj": tempdirobj,
    }


class SubmanifestGroupsTest(unittest.TestCase):
    def setUp(self):
        self.repo_struct = submanifest_repo_structure()

    def test_submanifest_positive_and_filtering(self):
        """
        Positive test with filtering:
          - The main manifest includes a <submanifest> element with groups="g1"
            and default-groups="dg1,dg2".
          - The submanifest XML defines three projects:
                sub1: groups="dg1"         -> matches default-groups
                sub2: groups="dg2"         -> matches default-groups
                sub3: groups="other"       -> does not match default-groups;
                                              should be marked 'notdefault'
          - Expectations:
                * sub1 and sub2 load normally.
                * sub3 is loaded, but its groups include 'notdefault'.
        """
        rs = self.repo_struct
        manifest_path = rs["manifest_path"]
        subm_dir = rs["submanifest_dir"]

        # Update main manifest: include a <submanifest> element.
        submanifest_line = """
      <submanifest name="my-submanifest" project="dummy/project"
                path="submanifest_dir" groups="g1" default-groups="dg1,dg2" />
        """
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(get_main_manifest(submanifest_line))

        # Prepare submanifest's .git config (for remote "origin")
        submanifest_git = os.path.join(subm_dir, "manifests.git")
        os.makedirs(submanifest_git, exist_ok=True)
        with open(
            os.path.join(subm_dir, "manifests.git", "config"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                """[remote "origin"]
    url = https://localhost:0/my-submanifest
"""
            )
        # Prepare submanifest manifests directory and default.xml with projects.
        submanifest_manifests_dir = os.path.join(subm_dir, "manifests")
        os.makedirs(submanifest_manifests_dir, exist_ok=True)
        projects_xml = """
      <project name="sub1" path="p1" groups="dg1" />
      <project name="sub2" path="p2" groups="dg2" />
      <project name="sub3" path="p3" groups="other" />
        """
        submanifest_xml = get_submanifest_manifest(projects_xml)
        submanifest_file = os.path.join(
            submanifest_manifests_dir, "default.xml"
        )
        with open(submanifest_file, "w", encoding="utf-8") as f:
            f.write(submanifest_xml)

        # Create the link file manifest.xml in subm_dir.
        link_file = os.path.join(subm_dir, "manifest.xml")
        shutil.copyfile(submanifest_file, link_file)

        # Initialize XmlManifest.
        manifest = XmlManifest(rs["repodir"], manifest_path)
        all_projects = manifest.all_projects
        project_names = [p.name for p in all_projects]

        # Check that all expected projects are loaded.
        self.assertIn(
            "dummy/project", project_names, "Main manifest project missing"
        )
        self.assertIn("sub1", project_names, "Expected 'sub1' in submanifest")
        self.assertIn("sub2", project_names, "Expected 'sub2' in submanifest")
        self.assertIn("sub3", project_names, "Expected 'sub3' in submanifest")

        sub1 = next(p for p in all_projects if p.name == "sub1")
        sub2 = next(p for p in all_projects if p.name == "sub2")
        sub3 = next(p for p in all_projects if p.name == "sub3")
        g_sub1 = parse_groups(sub1)
        g_sub2 = parse_groups(sub2)
        g_sub3 = parse_groups(sub3)

        # Check that sub1 and sub2 have their declared groups
        # and inherit parent's "g1".
        self.assertIn("dg1", g_sub1, "sub1 must have 'dg1'")
        self.assertIn("dg2", g_sub2, "sub2 must have 'dg2'")
        self.assertIn("g1", g_sub1, "sub1 must inherit 'g1'")
        self.assertIn("g1", g_sub2, "sub2 must inherit 'g1'")
        # For sub3, declared group "other" does not match default-groups
        # "dg1,dg2", so it should be marked as 'notdefault'.
        self.assertIn(
            "notdefault",
            g_sub3,
            "sub3 should be marked as 'notdefault' due to filtering",
        )

    def test_get_default_groups_str(self):
        """
        Test that GetDefaultGroupsStr() returns the expected string and
        that the serialized XML contains the correct default-groups attribute.
        """
        rs = self.repo_struct
        repodir = rs["repodir"]
        manifest_path = rs["manifest_path"]
        subm_dir = rs["submanifest_dir"]

        # Update main manifest with a submanifest element.
        submanifest_line = """
      <submanifest name="my-submanifest" project="dummy/project"
                path="submanifest_dir" groups="g1" default-groups="dg1,dg2" />
        """
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(get_main_manifest(submanifest_line))

        # Prepare minimal submanifest configuration.
        submanifest_git = os.path.join(subm_dir, "manifests.git")
        os.makedirs(submanifest_git, exist_ok=True)
        with open(
            os.path.join(subm_dir, "manifests.git", "config"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                """[remote "origin"]
    url = https://localhost:0/my-submanifest
"""
            )
        submanifest_manifests_dir = os.path.join(subm_dir, "manifests")
        os.makedirs(submanifest_manifests_dir, exist_ok=True)
        submanifest_xml = """
    <manifest>
      <remote name="origin" fetch="." />
      <default remote="origin" revision="main" />
    </manifest>
        """
        submanifest_file = os.path.join(subm_dir, "manifests", "default.xml")
        with open(
            subm_dir + "/manifests/default.xml", "w", encoding="utf-8"
        ) as f:
            f.write(submanifest_xml.strip())
        link_file = os.path.join(subm_dir, "manifest.xml")
        shutil.copyfile(submanifest_file, link_file)

        # Initialize XmlManifest.
        manifest = XmlManifest(repodir, manifest_path)
        submanifests = manifest.submanifests
        self.assertIn(
            "my-submanifest",
            submanifests,
            "Submanifest 'my-submanifest' not found.",
        )

        subman_obj = submanifests["my-submanifest"]
        dg_str = subman_obj.GetDefaultGroupsStr()
        self.assertEqual(
            dg_str,
            "dg1,dg2",
            f"Expected 'dg1,dg2' from GetDefaultGroupsStr(), got: {dg_str}",
        )

        xml_str = manifest.ToXml().toxml()
        self.assertIn(
            'default-groups="dg1,dg2"',
            xml_str,
            "Serialized XML missing default-groups attribute",
        )

    def test_submanifest_negative_missing_remote(self):
        """
        Negative test: verify that if the submanifest's <default> element
        specifies a remote that is not declared, then manifest loading fails
        with a ManifestParseError.
        """
        rs = self.repo_struct
        manifest_path = rs["manifest_path"]
        subm_dir = rs["submanifest_dir"]

        # Update main manifest with a submanifest element.
        broken_manifest = """
    <manifest>
      <remote name="origin" fetch="." />
      <default remote="origin" revision="main" />
      <submanifest name="broken-submanifest" project="dummy/project"
       path="submanifest_dir" />
    </manifest>
        """
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(broken_manifest.strip())

        # Prepare submanifest .git config.
        submanifest_git = os.path.join(subm_dir, "manifests.git")
        os.makedirs(submanifest_git, exist_ok=True)
        with open(
            os.path.join(subm_dir, "manifests.git", "config"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(
                """[remote "origin"]
    url = https://localhost:0/broken-submanifest
"""
            )
        # Prepare submanifest XML with an undefined remote ("bad-remote")
        # in the <default> element.
        submanifest_manifests_dir = os.path.join(subm_dir, "manifests")
        os.makedirs(submanifest_manifests_dir, exist_ok=True)
        broken_submanifest_xml = """
    <manifest>
      <remote name="origin" fetch="." />
      <default remote="bad-remote" revision="main" />
      <project name="subX" path="px" />
    </manifest>
        """
        submanifest_file = os.path.join(subm_dir, "manifests", "default.xml")
        with open(submanifest_file, "w", encoding="utf-8") as f:
            f.write(broken_submanifest_xml.strip())
        link_file = os.path.join(subm_dir, "manifest.xml")
        shutil.copyfile(submanifest_file, link_file)

        with self.assertRaises(ManifestParseError):
            _ = list(XmlManifest(rs["repodir"], manifest_path).projects)


if __name__ == "__main__":
    unittest.main()
