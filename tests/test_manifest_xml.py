# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the manifest_xml.py module."""

import os
from pathlib import Path
import platform
import re
import xml.dom.minidom

import pytest

import error
import manifest_xml


# Invalid paths that we don't want in the filesystem.
INVALID_FS_PATHS = (
    "",
    ".",
    "..",
    "../",
    "./",
    ".//",
    "foo/",
    "./foo",
    "../foo",
    "foo/./bar",
    "foo/../../bar",
    "/foo",
    "./../foo",
    ".git/foo",
    # Check case folding.
    ".GIT/foo",
    "blah/.git/foo",
    ".repo/foo",
    ".repoconfig",
    # Block ~ due to 8.3 filenames on Windows filesystems.
    "~",
    "foo~",
    "blah/foo~",
    # Block Unicode characters that get normalized out by filesystems.
    "foo\u200cbar",
    # Block newlines.
    "f\n/bar",
    "f\r/bar",
)

# Make sure platforms that use path separators (e.g. Windows) are also
# rejected properly.
if os.path.sep != "/":
    INVALID_FS_PATHS += tuple(
        x.replace("/", os.path.sep) for x in INVALID_FS_PATHS
    )


def sort_attributes(manifest: str) -> str:
    """Sort the attributes of all elements alphabetically.

    This is needed because different versions of the toxml() function from
    xml.dom.minidom outputs the attributes of elements in different orders.
    Before Python 3.8 they were output alphabetically, later versions preserve
    the order specified by the user.

    Args:
        manifest: String containing an XML manifest.

    Returns:
        The XML manifest with the attributes of all elements sorted
        alphabetically.
    """
    new_manifest = ""
    # This will find every element in the XML manifest, whether they have
    # attributes or not. This simplifies recreating the manifest below.
    matches = re.findall(
        r'(<[/?]?[a-z-]+\s*)((?:\S+?="[^"]+"\s*?)*)(\s*[/?]?>)', manifest
    )
    for head, attrs, tail in matches:
        m = re.findall(r'\S+?="[^"]+"', attrs)
        new_manifest += head + " ".join(sorted(m)) + tail
    return new_manifest


class RepoClient:
    """Basic empty repo checkout."""

    def __init__(self, topdir: Path):
        self.topdir = topdir
        self.repodir = self.topdir / ".repo"
        self.manifest_dir = self.repodir / "manifests"
        self.manifest_file = self.repodir / manifest_xml.MANIFEST_FILE_NAME
        self.local_manifest_dir = (
            self.repodir / manifest_xml.LOCAL_MANIFESTS_DIR_NAME
        )
        self.repodir.mkdir()
        self.manifest_dir.mkdir()
        # The manifest parsing really wants a git repo currently.
        gitdir = self.repodir / "manifests.git"
        gitdir.mkdir()
        (gitdir / "config").write_text(
            """[remote "origin"]
        url = https://localhost:0/manifest
"""
        )

    def get_xml_manifest(self, data: str) -> manifest_xml.XmlManifest:
        """Helper to initialize a manifest for testing."""
        self.manifest_file.write_text(data, encoding="utf-8")
        return manifest_xml.XmlManifest(
            str(self.repodir), str(self.manifest_file)
        )

    @staticmethod
    def encode_xml_attr(attr: str) -> str:
        """Encode |attr| using XML escape rules."""
        return attr.replace("\r", "&#x000d;").replace("\n", "&#x000a;")


@pytest.fixture
def repo_client(tmp_path: Path) -> RepoClient:
    """Generate a basic empty repo checkout.

    The manifest is not generated.
    """
    return RepoClient(tmp_path)


class TestManifestValidateFilePaths:
    """Check _ValidateFilePaths helper.

    This doesn't access a real filesystem.
    """

    def check_both(self, src: str, dest: str) -> None:
        """Check copyfile & linkfile."""
        manifest_xml.XmlManifest._ValidateFilePaths("copyfile", src, dest)
        manifest_xml.XmlManifest._ValidateFilePaths("linkfile", src, dest)

    def test_normal_path(self) -> None:
        """Make sure good paths are accepted."""
        self.check_both("foo", "bar")
        self.check_both("foo/bar", "bar")
        self.check_both("foo", "bar/bar")
        self.check_both("foo/bar", "bar/bar")

    def test_symlink_targets(self) -> None:
        """Some extra checks for symlinks."""

        def check(src: str, dest: str) -> None:
            manifest_xml.XmlManifest._ValidateFilePaths("linkfile", src, dest)

        # We allow symlinks to end in a slash since we allow them to point to
        # dirs in general.  Technically the slash isn't necessary.
        check("foo/", "bar")
        # We allow a single '.' to get a reference to the project itself.
        check(".", "bar")

    def test_bad_paths(self) -> None:
        """Make sure bad paths (src & dest) are rejected."""
        for path in INVALID_FS_PATHS:
            with pytest.raises(error.ManifestInvalidPathError):
                self.check_both(path, "a")
            with pytest.raises(error.ManifestInvalidPathError):
                self.check_both("a", path)


class TestValue:
    """Check utility parsing code."""

    def _get_node(self, text: str) -> xml.dom.minidom.Element:
        return xml.dom.minidom.parseString(text).firstChild

    def test_bool_default(self) -> None:
        """Check XmlBool default handling."""
        node = self._get_node("<node/>")
        assert manifest_xml.XmlBool(node, "a") is None
        assert manifest_xml.XmlBool(node, "a", None) is None
        assert manifest_xml.XmlBool(node, "a", 123) == 123

        node = self._get_node('<node a=""/>')
        assert manifest_xml.XmlBool(node, "a") is None

    def test_bool_invalid(self) -> None:
        """Check XmlBool invalid handling."""
        node = self._get_node('<node a="moo"/>')
        assert manifest_xml.XmlBool(node, "a", 123) == 123

    def test_bool_true(self) -> None:
        """Check XmlBool true values."""
        for value in ("yes", "true", "1"):
            node = self._get_node(f'<node a="{value}"/>')
            assert manifest_xml.XmlBool(node, "a") is True

    def test_bool_false(self) -> None:
        """Check XmlBool false values."""
        for value in ("no", "false", "0"):
            node = self._get_node(f'<node a="{value}"/>')
            assert manifest_xml.XmlBool(node, "a") is False

    def test_int_default(self) -> None:
        """Check XmlInt default handling."""
        node = self._get_node("<node/>")
        assert manifest_xml.XmlInt(node, "a") is None
        assert manifest_xml.XmlInt(node, "a", None) is None
        assert manifest_xml.XmlInt(node, "a", 123) == 123

        node = self._get_node('<node a=""/>')
        assert manifest_xml.XmlInt(node, "a") is None

    def test_int_good(self) -> None:
        """Check XmlInt numeric handling."""
        for value in (-1, 0, 1, 50000):
            node = self._get_node(f'<node a="{value}"/>')
            assert manifest_xml.XmlInt(node, "a") == value

    def test_int_invalid(self) -> None:
        """Check XmlInt invalid handling."""
        with pytest.raises(error.ManifestParseError):
            node = self._get_node('<node a="xx"/>')
            manifest_xml.XmlInt(node, "a")


class TestXmlManifest:
    """Check manifest processing."""

    def test_empty(self, repo_client: RepoClient) -> None:
        """Parse an 'empty' manifest file."""
        manifest = repo_client.get_xml_manifest(
            '<?xml version="1.0" encoding="UTF-8"?>' "<manifest></manifest>"
        )
        assert manifest.remotes == {}
        assert manifest.projects == []

    def test_link(self, repo_client: RepoClient) -> None:
        """Verify Link handling with new names."""
        manifest = repo_client.get_xml_manifest("<manifest></manifest>")
        (repo_client.manifest_dir / "foo.xml").write_text(
            "<manifest></manifest>"
        )
        manifest.Link("foo.xml")
        assert (
            '<include name="foo.xml" />'
            in repo_client.manifest_file.read_text()
        )

    def test_toxml_empty(self, repo_client: RepoClient) -> None:
        """Verify the ToXml() helper."""
        manifest = repo_client.get_xml_manifest(
            '<?xml version="1.0" encoding="UTF-8"?>' "<manifest></manifest>"
        )
        assert manifest.ToXml().toxml() == '<?xml version="1.0" ?><manifest/>'

    def test_todict_empty(self, repo_client: RepoClient) -> None:
        """Verify the ToDict() helper."""
        manifest = repo_client.get_xml_manifest(
            '<?xml version="1.0" encoding="UTF-8"?>' "<manifest></manifest>"
        )
        assert manifest.ToDict() == {}

    def test_toxml_omit_local(self, repo_client: RepoClient) -> None:
        """Does not include local_manifests projects when omit_local=True."""
        manifest = repo_client.get_xml_manifest(
            '<?xml version="1.0" encoding="UTF-8"?><manifest>'
            '<remote name="a" fetch=".."/><default remote="a" revision="r"/>'
            '<project name="p" groups="local::me"/>'
            '<project name="q"/>'
            '<project name="r" groups="keep"/>'
            "</manifest>"
        )
        assert (
            sort_attributes(manifest.ToXml(omit_local=True).toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch=".." name="a"/><default remote="a" revision="r"/>'
            '<project name="q"/><project groups="keep" name="r"/></manifest>'
        )

    def test_toxml_with_local(self, repo_client: RepoClient) -> None:
        """Does include local_manifests projects when omit_local=False."""
        manifest = repo_client.get_xml_manifest(
            '<?xml version="1.0" encoding="UTF-8"?><manifest>'
            '<remote name="a" fetch=".."/><default remote="a" revision="r"/>'
            '<project name="p" groups="local::me"/>'
            '<project name="q"/>'
            '<project name="r" groups="keep"/>'
            "</manifest>"
        )
        assert (
            sort_attributes(manifest.ToXml(omit_local=False).toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch=".." name="a"/><default remote="a" revision="r"/>'
            '<project groups="local::me" name="p"/>'
            '<project name="q"/><project groups="keep" name="r"/></manifest>'
        )

    def test_repo_hooks(self, repo_client: RepoClient) -> None:
        """Check repo-hooks settings."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="repohooks" path="src/repohooks"/>
  <repo-hooks in-project="repohooks" enabled-list="a, b"/>
</manifest>
"""
        )
        assert manifest.repo_hooks_project.name == "repohooks"
        assert manifest.repo_hooks_project.enabled_repo_hooks == ["a", "b"]

    def test_repo_hooks_unordered(self, repo_client: RepoClient) -> None:
        """Check repo-hooks settings work when the project comes after."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <repo-hooks in-project="repohooks" enabled-list="a, b"/>
  <project name="repohooks" path="src/repohooks"/>
</manifest>
"""
        )
        assert manifest.repo_hooks_project.name == "repohooks"
        assert manifest.repo_hooks_project.enabled_repo_hooks == ["a", "b"]

    def test_unknown_tags(self, repo_client: RepoClient) -> None:
        """Check superproject settings."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <iankaz value="unknown (possible) future tags are ignored"/>
  <x-custom-tag>X tags are always ignored</x-custom-tag>
</manifest>
"""
        )
        assert manifest.superproject.name == "superproject"
        assert manifest.superproject.remote.name == "test-remote"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="test-remote"/>'
            '<default remote="test-remote" revision="refs/heads/main"/>'
            '<superproject name="superproject"/>'
            "</manifest>"
        )

    def test_remote_annotations(self, repo_client: RepoClient) -> None:
        """Check remote settings."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost">
    <annotation name="foo" value="bar"/>
  </remote>
</manifest>
"""
        )
        assert manifest.remotes["test-remote"].annotations[0].name == "foo"
        assert manifest.remotes["test-remote"].annotations[0].value == "bar"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="test-remote">'
            '<annotation name="foo" value="bar"/>'
            "</remote>"
            "</manifest>"
        )

    def test_parse_with_xml_doctype(self, repo_client: RepoClient) -> None:
        """Check correct manifest parse with DOCTYPE node present."""
        manifest = repo_client.get_xml_manifest(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE manifest []>
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="test-project" path="src/test-project"/>
</manifest>
"""
        )
        assert len(manifest.projects) == 1
        assert manifest.projects[0].name == "test-project"

    def test_sync_j_max(self, repo_client: RepoClient) -> None:
        """Check sync-j-max handling."""
        # Check valid value.
        manifest = repo_client.get_xml_manifest(
            '<manifest><default sync-j-max="5" /></manifest>'
        )
        assert manifest.default.sync_j_max == 5
        assert (
            manifest.ToXml().toxml() == '<?xml version="1.0" ?>'
            '<manifest><default sync-j-max="5"/></manifest>'
        )

        # Check invalid values.
        with pytest.raises(error.ManifestParseError):
            manifest = repo_client.get_xml_manifest(
                '<manifest><default sync-j-max="0" /></manifest>'
            )
            manifest.ToXml()

        with pytest.raises(error.ManifestParseError):
            manifest = repo_client.get_xml_manifest(
                '<manifest><default sync-j-max="-1" /></manifest>'
            )
            manifest.ToXml()


class TestIncludeElement:
    """Tests for <include>."""

    def test_revision_default(self, repo_client: RepoClient) -> None:
        """Check handling of revision attribute."""
        root_m = repo_client.manifest_dir / "root.xml"
        root_m.write_text(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <include name="stable.xml" revision="stable-branch" />
  <project name="root-name1" path="root-path1" />
  <project name="root-name2" path="root-path2" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "stable.xml").write_text(
            """
<manifest>
  <include name="man1.xml" />
  <include name="man2.xml" revision="stable-branch2" />
  <project name="stable-name1" path="stable-path1" />
  <project name="stable-name2" path="stable-path2" revision="stable-branch2" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man1.xml").write_text(
            """
<manifest>
  <project name="man1-name1" />
  <project name="man1-name2" revision="stable-branch3" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man2.xml").write_text(
            """
<manifest>
  <project name="man2-name1" />
  <project name="man2-name2" revision="stable-branch3" />
</manifest>
"""
        )
        include_m = manifest_xml.XmlManifest(
            str(repo_client.repodir), str(root_m)
        )
        for proj in include_m.projects:
            if proj.name == "root-name1":
                # Check include revision not set on root level proj.
                assert proj.revisionExpr != "stable-branch"
            if proj.name == "root-name2":
                # Check root proj revision not removed.
                assert proj.revisionExpr == "refs/heads/main"
            if proj.name == "stable-name1":
                # Check stable proj has inherited revision include node.
                assert proj.revisionExpr == "stable-branch"
            if proj.name == "stable-name2":
                # Check stable proj revision can override include node.
                assert proj.revisionExpr == "stable-branch2"
            if proj.name == "man1-name1":
                assert proj.revisionExpr == "stable-branch"
            if proj.name == "man1-name2":
                assert proj.revisionExpr == "stable-branch3"
            if proj.name == "man2-name1":
                assert proj.revisionExpr == "stable-branch2"
            if proj.name == "man2-name2":
                assert proj.revisionExpr == "stable-branch3"

    def test_group_levels(self, repo_client: RepoClient) -> None:
        """Check handling of nested include groups."""
        root_m = repo_client.manifest_dir / "root.xml"
        root_m.write_text(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <include name="level1.xml" groups="level1-group" />
  <project name="root-name1" path="root-path1" />
  <project name="root-name2" path="root-path2" groups="r2g1,r2g2" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "level1.xml").write_text(
            """
<manifest>
  <include name="level2.xml" groups="level2-group" />
  <project name="level1-name1" path="level1-path1" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "level2.xml").write_text(
            """
<manifest>
  <project name="level2-name1" path="level2-path1" groups="l2g1,l2g2" />
</manifest>
"""
        )
        include_m = manifest_xml.XmlManifest(
            str(repo_client.repodir), str(root_m)
        )
        for proj in include_m.projects:
            if proj.name == "root-name1":
                # Check include group not set on root level proj.
                assert "level1-group" not in proj.groups
            if proj.name == "root-name2":
                # Check root proj group not removed.
                assert "r2g1" in proj.groups
            if proj.name == "level1-name1":
                # Check level1 proj has inherited group level 1.
                assert "level1-group" in proj.groups
            if proj.name == "level2-name1":
                # Check level2 proj has inherited group levels 1 and 2.
                assert "level1-group" in proj.groups
                assert "level2-group" in proj.groups
                # Check level2 proj group not removed.
                assert "l2g1" in proj.groups

    def test_group_levels_with_extend_project(
        self, repo_client: RepoClient
    ) -> None:
        """Check inheritance of groups via extend-project."""
        root_m = repo_client.manifest_dir / "root.xml"
        root_m.write_text(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <include name="man1.xml" groups="top-group1" />
  <include name="man2.xml" groups="top-group2" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man1.xml").write_text(
            """
<manifest>
  <project name="project1" path="project1" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man2.xml").write_text(
            """
<manifest>
  <extend-project name="project1" groups="eg1" />
</manifest>
"""
        )
        include_m = manifest_xml.XmlManifest(
            str(repo_client.repodir), str(root_m)
        )
        proj = include_m.projects[0]
        # Check project has inherited group via project element.
        assert "top-group1" in proj.groups
        # Check project has inherited group via extend-project element.
        assert "top-group2" in proj.groups
        # Check project has set group via extend-project element.
        assert "eg1" in proj.groups

    def test_extend_project_does_not_inherit_local_groups(
        self, repo_client: RepoClient
    ) -> None:
        """Check that extend-project does not inherit local groups."""
        root_m = repo_client.manifest_dir / "root.xml"
        root_m.write_text(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="project1" path="project1" />
  <include name="man1.xml" groups="g1,local:g2" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man1.xml").write_text(
            """
<manifest>
  <extend-project name="project1" groups="g3" />
</manifest>
"""
        )
        include_m = manifest_xml.XmlManifest(
            str(repo_client.repodir), str(root_m)
        )
        proj = include_m.projects[0]

        assert "g1" in proj.groups
        assert "local:g2" not in proj.groups
        assert "g3" in proj.groups

    def test_allow_bad_name_from_user(self, repo_client: RepoClient) -> None:
        """Check handling of bad name attribute from the user's input."""

        def parse(name: str) -> None:
            name = repo_client.encode_xml_attr(name)
            manifest = repo_client.get_xml_manifest(
                f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <include name="{name}" />
</manifest>
"""
            )
            # Force the manifest to be parsed.
            manifest.ToXml()

        # Setup target of the include.
        target = repo_client.topdir / "target.xml"
        target.write_text("<manifest></manifest>")

        # Include with absolute path.
        parse(str(target.absolute()))

        # Include with relative path.
        parse(os.path.relpath(str(target), str(repo_client.manifest_dir)))

    def test_bad_name_checks(self, repo_client: RepoClient) -> None:
        """Check handling of bad name attribute."""

        def parse(name: str) -> None:
            name = repo_client.encode_xml_attr(name)
            # Setup target of the include.
            (repo_client.manifest_dir / "target.xml").write_text(
                f'<manifest><include name="{name}"/></manifest>'
            )

            manifest = repo_client.get_xml_manifest(
                """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <include name="target.xml" />
</manifest>
"""
            )
            # Force the manifest to be parsed.
            manifest.ToXml()

        # Handle empty name explicitly because a different codepath rejects it.
        with pytest.raises(error.ManifestParseError):
            parse("")

        for path in INVALID_FS_PATHS:
            if not path:
                continue

            with pytest.raises(error.ManifestInvalidPathError):
                parse(path)


class TestProjectElement:
    """Tests for <project>."""

    def test_group(self, repo_client: RepoClient) -> None:
        """Check project group settings."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="test-name" path="test-path"/>
  <project name="extras" path="path" groups="g1,g2,g1"/>
</manifest>
"""
        )
        assert len(manifest.projects) == 2
        # Ordering isn't guaranteed.
        result = {
            manifest.projects[0].name: manifest.projects[0].groups,
            manifest.projects[1].name: manifest.projects[1].groups,
        }
        assert result["test-name"] == {
            "name:test-name",
            "all",
            "path:test-path",
        }
        assert result["extras"] == {
            "g1",
            "g2",
            "name:extras",
            "all",
            "path:path",
        }
        groupstr = "default,platform-" + platform.system().lower()
        assert manifest.GetManifestGroupsStr() == groupstr
        groupstr = "g1,g2,g1"
        manifest.manifestProject.config.SetString("manifest.groups", groupstr)
        assert manifest.GetManifestGroupsStr() == groupstr

    def test_set_revision_id(self, repo_client: RepoClient) -> None:
        """Check setting of project's revisionId."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="test-name"/>
</manifest>
"""
        )
        assert len(manifest.projects) == 1
        project = manifest.projects[0]
        project.SetRevisionId("ABCDEF")
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="test-name" revision="ABCDEF" upstream="refs/heads/main"/>'  # noqa: E501
            "</manifest>"
        )

    def test_sync_strategy(self, repo_client: RepoClient) -> None:
        """Check setting of project's sync_strategy."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="test-name" sync-strategy="stateless"/>
</manifest>
"""
        )
        assert len(manifest.projects) == 1
        project = manifest.projects[0]
        assert project.sync_strategy == "stateless"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="test-name" sync-strategy="stateless"/>'
            "</manifest>"
        )

    def test_trailing_slash(self, repo_client: RepoClient) -> None:
        """Check handling of trailing slashes in attributes."""

        def parse(name: str, path: str) -> manifest_xml.XmlManifest:
            name = repo_client.encode_xml_attr(name)
            path = repo_client.encode_xml_attr(path)
            return repo_client.get_xml_manifest(
                f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="{name}" path="{path}" />
</manifest>
"""
            )

        manifest = parse("a/path/", "foo")
        assert os.path.normpath(manifest.projects[0].gitdir) == os.path.join(
            str(repo_client.topdir), ".repo", "projects", "foo.git"
        )
        assert os.path.normpath(manifest.projects[0].objdir) == os.path.join(
            str(repo_client.topdir), ".repo", "project-objects", "a", "path.git"
        )

        manifest = parse("a/path", "foo/")
        assert os.path.normpath(manifest.projects[0].gitdir) == os.path.join(
            str(repo_client.topdir), ".repo", "projects", "foo.git"
        )
        assert os.path.normpath(manifest.projects[0].objdir) == os.path.join(
            str(repo_client.topdir), ".repo", "project-objects", "a", "path.git"
        )

        manifest = parse("a/path", "foo//////")
        assert os.path.normpath(manifest.projects[0].gitdir) == os.path.join(
            str(repo_client.topdir), ".repo", "projects", "foo.git"
        )
        assert os.path.normpath(manifest.projects[0].objdir) == os.path.join(
            str(repo_client.topdir), ".repo", "project-objects", "a", "path.git"
        )

    def test_toplevel_path(self, repo_client: RepoClient) -> None:
        """Check handling of path=. specially."""

        def parse(name: str, path: str) -> manifest_xml.XmlManifest:
            name = repo_client.encode_xml_attr(name)
            path = repo_client.encode_xml_attr(path)
            return repo_client.get_xml_manifest(
                f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="{name}" path="{path}" />
</manifest>
"""
            )

        for path in (".", "./", ".//", ".///"):
            manifest = parse("server/path", path)
            assert os.path.normpath(
                manifest.projects[0].gitdir
            ) == os.path.join(
                str(repo_client.topdir), ".repo", "projects", "..git"
            )

    def test_get_project_paths_local_gitdirs(
        self, repo_client: RepoClient
    ) -> None:
        """Check GetProjectPaths with UseLocalGitDirs."""
        manifest = repo_client.get_xml_manifest(
            '<?xml version="1.0" encoding="UTF-8"?><manifest></manifest>'
        )
        manifest.manifestProject.config.SetBoolean("repo.uselocalgitdirs", True)

        relpath, worktree, gitdir, objdir, use_git_worktrees = (
            manifest.GetProjectPaths("foo", "bar", "origin")
        )

        assert os.path.normpath(gitdir) == os.path.normpath(
            os.path.join(str(repo_client.topdir), "bar", ".git")
        )
        assert os.path.normpath(objdir) == os.path.normpath(
            os.path.join(str(repo_client.topdir), "bar", ".git")
        )

    def test_bad_path_name_checks(self, repo_client: RepoClient) -> None:
        """Check handling of bad path & name attributes."""

        def parse(name: str, path: str) -> None:
            name = repo_client.encode_xml_attr(name)
            path = repo_client.encode_xml_attr(path)
            manifest = repo_client.get_xml_manifest(
                f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="{name}" path="{path}" />
</manifest>
"""
            )
            # Force the manifest to be parsed.
            manifest.ToXml()

        # Verify the parser is valid by default to avoid buggy tests below.
        parse("ok", "ok")

        # Handle empty name explicitly because a different codepath rejects it.
        # Empty path is OK because it defaults to the name field.
        with pytest.raises(error.ManifestParseError):
            parse("", "ok")

        for path in INVALID_FS_PATHS:
            if not path or path.endswith("/") or path.endswith(os.path.sep):
                continue

            with pytest.raises(error.ManifestInvalidPathError):
                parse(path, "ok")

            # We have a dedicated test for path=".".
            if path not in {"."}:
                with pytest.raises(error.ManifestInvalidPathError):
                    parse("ok", path)


class TestSuperProjectElement:
    """Tests for <superproject>."""

    def test_superproject(self, repo_client: RepoClient) -> None:
        """Check superproject settings."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
</manifest>
"""
        )
        assert manifest.superproject.name == "superproject"
        assert manifest.superproject.remote.name == "test-remote"
        assert (
            manifest.superproject.remote.url == "http://localhost/superproject"
        )
        assert manifest.superproject.revision == "refs/heads/main"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="test-remote"/>'
            '<default remote="test-remote" revision="refs/heads/main"/>'
            '<superproject name="superproject"/>'
            "</manifest>"
        )

    def test_superproject_revision(self, repo_client: RepoClient) -> None:
        """Check superproject settings with a different revision attribute"""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject" revision="refs/heads/stable" />
</manifest>
"""
        )
        assert manifest.superproject.name == "superproject"
        assert manifest.superproject.remote.name == "test-remote"
        assert (
            manifest.superproject.remote.url == "http://localhost/superproject"
        )
        assert manifest.superproject.revision == "refs/heads/stable"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="test-remote"/>'
            '<default remote="test-remote" revision="refs/heads/main"/>'
            '<superproject name="superproject" revision="refs/heads/stable"/>'
            "</manifest>"
        )

    def test_superproject_revision_default_negative(
        self, repo_client: RepoClient
    ) -> None:
        """Check superproject settings with a same revision attribute"""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/stable" />
  <superproject name="superproject" revision="refs/heads/stable" />
</manifest>
"""
        )
        assert manifest.superproject.name == "superproject"
        assert manifest.superproject.remote.name == "test-remote"
        assert (
            manifest.superproject.remote.url == "http://localhost/superproject"
        )
        assert manifest.superproject.revision == "refs/heads/stable"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="test-remote"/>'
            '<default remote="test-remote" revision="refs/heads/stable"/>'
            '<superproject name="superproject"/>'
            "</manifest>"
        )

    def test_superproject_revision_remote(
        self, repo_client: RepoClient
    ) -> None:
        """Check superproject settings with a same revision attribute"""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost"
          revision="refs/heads/main" />
  <default remote="test-remote" />
  <superproject name="superproject" revision="refs/heads/stable" />
</manifest>
"""
        )
        assert manifest.superproject.name == "superproject"
        assert manifest.superproject.remote.name == "test-remote"
        assert (
            manifest.superproject.remote.url == "http://localhost/superproject"
        )
        assert manifest.superproject.revision == "refs/heads/stable"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="test-remote" revision="refs/heads/main"/>'  # noqa: E501
            '<default remote="test-remote"/>'
            '<superproject name="superproject" revision="refs/heads/stable"/>'
            "</manifest>"
        )

    def test_remote(self, repo_client: RepoClient) -> None:
        """Check superproject settings with a remote."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <remote name="superproject-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="platform/superproject" remote="superproject-remote"/>
</manifest>
"""
        )
        assert manifest.superproject.name == "platform/superproject"
        assert manifest.superproject.remote.name == "superproject-remote"
        assert (
            manifest.superproject.remote.url
            == "http://localhost/platform/superproject"
        )
        assert manifest.superproject.revision == "refs/heads/main"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<remote fetch="http://localhost" name="superproject-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<superproject name="platform/superproject" remote="superproject-remote"/>'  # noqa: E501
            "</manifest>"
        )

    def test_default_remote(self, repo_client: RepoClient) -> None:
        """Check superproject settings with a default remote."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject" remote="default-remote"/>
</manifest>
"""
        )
        assert manifest.superproject.name == "superproject"
        assert manifest.superproject.remote.name == "default-remote"
        assert manifest.superproject.revision == "refs/heads/main"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<superproject name="superproject"/>'
            "</manifest>"
        )


class TestContactinfoElement:
    """Tests for <contactinfo>."""

    def test_contactinfo(self, repo_client: RepoClient) -> None:
        """Check contactinfo settings."""
        bugurl = "http://localhost/contactinfo"
        manifest = repo_client.get_xml_manifest(
            f"""
<manifest>
  <contactinfo bugurl="{bugurl}"/>
</manifest>
"""
        )
        assert manifest.contactinfo.bugurl == bugurl
        assert (
            manifest.ToXml().toxml() == '<?xml version="1.0" ?><manifest>'
            f'<contactinfo bugurl="{bugurl}"/>'
            "</manifest>"
        )


class TestDefaultElement:
    """Tests for <default>."""

    def test_default(self) -> None:
        """Check default settings."""
        a = manifest_xml._Default()
        a.revisionExpr = "foo"
        a.remote = manifest_xml._XmlRemote(name="remote")
        b = manifest_xml._Default()
        b.revisionExpr = "bar"
        assert a == a
        assert a != b
        assert b != a.remote
        assert a != 123
        assert a is not None


class TestRemoteElement:
    """Tests for <remote>."""

    def test_remote(self) -> None:
        """Check remote settings."""
        a = manifest_xml._XmlRemote(name="foo")
        a.AddAnnotation("key1", "value1", "true")
        b = manifest_xml._XmlRemote(name="foo")
        b.AddAnnotation("key2", "value1", "true")
        c = manifest_xml._XmlRemote(name="foo")
        c.AddAnnotation("key1", "value2", "true")
        d = manifest_xml._XmlRemote(name="foo")
        d.AddAnnotation("key1", "value1", "false")
        assert a == a
        assert a != b
        assert a != c
        assert a != d
        assert a != manifest_xml._Default()
        assert a != 123
        assert a is not None


class TestRemoveProjectElement:
    """Tests for <remove-project>."""

    def test_remove_one_project(self, repo_client: RepoClient) -> None:
        """Check removal of a single project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <remove-project name="myproject" />
</manifest>
"""
        )
        assert manifest.projects == []

    def test_remove_one_project_one_remains(
        self, repo_client: RepoClient
    ) -> None:
        """Check removal of one project while another remains."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <project name="yourproject" />
  <remove-project name="myproject" />
</manifest>
"""
        )

        assert len(manifest.projects) == 1
        assert manifest.projects[0].name == "yourproject"

    def test_remove_one_project_doesnt_exist(
        self, repo_client: RepoClient
    ) -> None:
        """Check removal of non-existent project fails."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <remove-project name="myproject" />
</manifest>
"""
        )
        with pytest.raises(error.ManifestParseError):
            manifest.projects

    def test_remove_one_optional_project_doesnt_exist(
        self, repo_client: RepoClient
    ) -> None:
        """Check optional removal of non-existent project passes."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <remove-project name="myproject" optional="true" />
</manifest>
"""
        )
        assert manifest.projects == []

    def test_remove_using_path_attrib(self, repo_client: RepoClient) -> None:
        """Check removal using name and path attributes."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="project1" path="tests/path1" />
  <project name="project1" path="tests/path2" />
  <project name="project2" />
  <project name="project3" />
  <project name="project4" path="tests/path3" />
  <project name="project4" path="tests/path4" />
  <project name="project5" />
  <project name="project6" path="tests/path6" />

  <remove-project name="project1" path="tests/path2" />
  <remove-project name="project3" />
  <remove-project name="project4" />
  <remove-project path="project5" />
  <remove-project path="tests/path6" />
</manifest>
"""
        )
        found_proj1_path1 = False
        found_proj2 = False
        for proj in manifest.projects:
            if proj.name == "project1":
                found_proj1_path1 = True
                assert proj.relpath == "tests/path1"
            if proj.name == "project2":
                found_proj2 = True
            assert proj.name != "project3"
            assert proj.name != "project4"
            assert proj.name != "project5"
            assert proj.name != "project6"
        assert found_proj1_path1
        assert found_proj2

    def test_base_revision_checks_on_patching(
        self, repo_client: RepoClient
    ) -> None:
        """Check base-rev validation during patching."""
        manifest_fail_wrong_tag = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="tag.002" />
  <project name="project1" path="tests/path1" />
  <extend-project name="project1" revision="new_hash" base-rev="tag.001" />
</manifest>
"""
        )
        with pytest.raises(error.ManifestParseError):
            manifest_fail_wrong_tag.ToXml()

        manifest_fail_remove = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="project1" path="tests/path1" revision="hash1" />
  <remove-project name="project1" base-rev="wrong_hash" />
</manifest>
"""
        )
        with pytest.raises(error.ManifestParseError):
            manifest_fail_remove.ToXml()

        manifest_fail_extend = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="project1" path="tests/path1" revision="hash1" />
  <extend-project name="project1" revision="new_hash" base-rev="wrong_hash" />
</manifest>
"""
        )
        with pytest.raises(error.ManifestParseError):
            manifest_fail_extend.ToXml()

        manifest_fail_unknown = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="project1" path="tests/path1" />
  <extend-project name="project1" revision="new_hash" base-rev="any_hash" />
</manifest>
"""
        )
        with pytest.raises(error.ManifestParseError):
            manifest_fail_unknown.ToXml()

        manifest_ok = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="project1" path="tests/path1" revision="hash1" />
  <project name="project2" path="tests/path2" revision="hash2" />
  <project name="project3" path="tests/path3" revision="hash3" />
  <project name="project4" path="tests/path4" revision="hash4" />

  <remove-project name="project1" />
  <remove-project name="project2" base-rev="hash2" />
  <project name="project2" path="tests/path2" revision="new_hash2" />
  <extend-project name="project3" base-rev="hash3" revision="new_hash3" />
  <extend-project name="project3" base-rev="new_hash3" revision="newer_hash3" />
  <remove-project path="tests/path4" base-rev="hash4" />
</manifest>
"""
        )
        found_proj2 = False
        found_proj3 = False
        for proj in manifest_ok.projects:
            if proj.name == "project2":
                found_proj2 = True
            if proj.name == "project3":
                found_proj3 = True
            assert proj.name != "project1"
            assert proj.name != "project4"
        assert found_proj2
        assert found_proj3
        assert len(manifest_ok.projects) == 2


class TestExtendProjectElement:
    """Tests for <extend-project>."""

    def test_extend_project_dest_path_single_match(
        self, repo_client: RepoClient
    ) -> None:
        """Check dest-path when single match exists."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <extend-project name="myproject" dest-path="bar" />
</manifest>
"""
        )
        assert len(manifest.projects) == 1
        assert manifest.projects[0].relpath == "bar"

    def test_extend_project_dest_path_multi_match(
        self, repo_client: RepoClient
    ) -> None:
        """Check dest-path when multiple matches exist fails."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" path="x" />
  <project name="myproject" path="y" />
  <extend-project name="myproject" dest-path="bar" />
</manifest>
"""
        )
        with pytest.raises(error.ManifestParseError):
            manifest.projects

    def test_extend_project_dest_path_multi_match_path_specified(
        self, repo_client: RepoClient
    ) -> None:
        """Check dest-path when path is specified for multi-match."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" path="x" />
  <project name="myproject" path="y" />
  <extend-project name="myproject" path="x" dest-path="bar" />
</manifest>
"""
        )
        assert len(manifest.projects) == 2
        if manifest.projects[0].relpath == "y":
            assert manifest.projects[1].relpath == "bar"
        else:
            assert manifest.projects[0].relpath == "bar"
            assert manifest.projects[1].relpath == "y"

    def test_extend_project_dest_branch(self, repo_client: RepoClient) -> None:
        """Check dest-branch update via extend-project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main"
           dest-branch="foo" />
  <project name="myproject" />
  <extend-project name="myproject" dest-branch="bar" />
</manifest>
"""
        )
        assert len(manifest.projects) == 1
        assert manifest.projects[0].dest_branch == "bar"

    def test_extend_project_upstream(self, repo_client: RepoClient) -> None:
        """Check upstream update via extend-project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <extend-project name="myproject" upstream="bar" />
</manifest>
"""
        )
        assert len(manifest.projects) == 1
        assert manifest.projects[0].upstream == "bar"

    def test_extend_project_copyfiles(self, repo_client: RepoClient) -> None:
        """Check copyfile addition via extend-project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <extend-project name="myproject">
    <copyfile src="foo" dest="bar" />
  </extend-project>
</manifest>
"""
        )
        assert list(manifest.projects[0].copyfiles)[0].src == "foo"
        assert list(manifest.projects[0].copyfiles)[0].dest == "bar"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="myproject">'
            '<copyfile dest="bar" src="foo"/>'
            "</project>"
            "</manifest>"
        )

    def test_extend_project_duplicate_copyfiles(
        self, repo_client: RepoClient
    ) -> None:
        """Check duplicate copyfile handling in includes."""
        root_m = repo_client.manifest_dir / "root.xml"
        root_m.write_text(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <include name="man1.xml" />
  <include name="man2.xml" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man1.xml").write_text(
            """
<manifest>
  <include name="common.xml" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man2.xml").write_text(
            """
<manifest>
  <include name="common.xml" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "common.xml").write_text(
            """
<manifest>
  <extend-project name="myproject">
    <copyfile dest="bar" src="foo"/>
  </extend-project>
</manifest>
"""
        )
        manifest = manifest_xml.XmlManifest(
            str(repo_client.repodir), str(root_m)
        )
        assert len(manifest.projects[0].copyfiles) == 1
        assert list(manifest.projects[0].copyfiles)[0].src == "foo"
        assert list(manifest.projects[0].copyfiles)[0].dest == "bar"

    def test_extend_project_linkfiles(self, repo_client: RepoClient) -> None:
        """Check linkfile addition via extend-project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <extend-project name="myproject">
    <linkfile src="foo" dest="bar" />
  </extend-project>
</manifest>
"""
        )
        assert list(manifest.projects[0].linkfiles)[0].src == "foo"
        assert list(manifest.projects[0].linkfiles)[0].dest == "bar"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="myproject">'
            '<linkfile dest="bar" src="foo"/>'
            "</project>"
            "</manifest>"
        )

    def test_extend_project_duplicate_linkfiles(
        self, repo_client: RepoClient
    ) -> None:
        """Check duplicate linkfile handling in includes."""
        root_m = repo_client.manifest_dir / "root.xml"
        root_m.write_text(
            """
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <include name="man1.xml" />
  <include name="man2.xml" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man1.xml").write_text(
            """
<manifest>
  <include name="common.xml" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "man2.xml").write_text(
            """
<manifest>
  <include name="common.xml" />
</manifest>
"""
        )
        (repo_client.manifest_dir / "common.xml").write_text(
            """
<manifest>
  <extend-project name="myproject">
    <linkfile dest="bar" src="foo"/>
  </extend-project>
</manifest>
"""
        )
        manifest = manifest_xml.XmlManifest(
            str(repo_client.repodir), str(root_m)
        )
        assert len(manifest.projects[0].linkfiles) == 1
        assert list(manifest.projects[0].linkfiles)[0].src == "foo"
        assert list(manifest.projects[0].linkfiles)[0].dest == "bar"

    def test_extend_project_annotations(self, repo_client: RepoClient) -> None:
        """Check annotation addition via extend-project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <extend-project name="myproject">
    <annotation name="foo" value="bar" />
  </extend-project>
</manifest>
"""
        )
        assert manifest.projects[0].annotations[0].name == "foo"
        assert manifest.projects[0].annotations[0].value == "bar"
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="myproject">'
            '<annotation name="foo" value="bar"/>'
            "</project>"
            "</manifest>"
        )

    def test_extend_project_annotations_multiples(
        self, repo_client: RepoClient
    ) -> None:
        """Check multiple annotation additions via extend-project."""
        manifest = repo_client.get_xml_manifest(
            """
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject">
    <annotation name="foo" value="bar" />
    <annotation name="few" value="bar" />
  </project>
  <extend-project name="myproject">
    <annotation name="foo" value="new_bar" />
    <annotation name="new" value="anno" />
  </extend-project>
</manifest>
"""
        )
        assert [
            (a.name, a.value) for a in manifest.projects[0].annotations
        ] == [
            ("foo", "bar"),
            ("few", "bar"),
            ("foo", "new_bar"),
            ("new", "anno"),
        ]
        assert (
            sort_attributes(manifest.ToXml().toxml())
            == '<?xml version="1.0" ?><manifest>'
            '<remote fetch="http://localhost" name="default-remote"/>'
            '<default remote="default-remote" revision="refs/heads/main"/>'
            '<project name="myproject">'
            '<annotation name="foo" value="bar"/>'
            '<annotation name="few" value="bar"/>'
            '<annotation name="foo" value="new_bar"/>'
            '<annotation name="new" value="anno"/>'
            "</project>"
            "</manifest>"
        )


class TestNormalizeUrl:
    """Tests for normalize_url() in manifest_xml.py"""

    def test_has_trailing_slash(self) -> None:
        """Trailing slashes should be removed."""
        url = "http://foo.com/bar/baz/"
        assert manifest_xml.normalize_url(url) == "http://foo.com/bar/baz"

        url = "http://foo.com/bar/"
        assert manifest_xml.normalize_url(url) == "http://foo.com/bar"

    def test_has_leading_slash(self) -> None:
        """SCP-like syntax except a / comes before the : which git disallows."""
        url = "/git@foo.com:bar/baf"
        assert manifest_xml.normalize_url(url) == url

        url = "gi/t@foo.com:bar/baf"
        assert manifest_xml.normalize_url(url) == url

        url = "git@fo/o.com:bar/baf"
        assert manifest_xml.normalize_url(url) == url

    def test_has_no_scheme(self) -> None:
        """Deal with cases where we have no scheme, but we also
        aren't dealing with the git SCP-like syntax
        """
        url = "foo.com/baf/bat"
        assert manifest_xml.normalize_url(url) == url

        url = "foo.com/baf"
        assert manifest_xml.normalize_url(url) == url

        url = "git@foo.com/baf/bat"
        assert manifest_xml.normalize_url(url) == url

        url = "git@foo.com/baf"
        assert manifest_xml.normalize_url(url) == url

        url = "/file/path/here"
        assert manifest_xml.normalize_url(url) == url

    def test_has_no_scheme_matches_scp_like_syntax(self) -> None:
        """SCP-like syntax should be converted to ssh://."""
        url = "git@foo.com:bar/baf"
        assert manifest_xml.normalize_url(url) == "ssh://git@foo.com/bar/baf"

        url = "git@foo.com:bar/"
        assert manifest_xml.normalize_url(url) == "ssh://git@foo.com/bar"

    def test_remote_url_resolution(self) -> None:
        """Check resolvedFetchUrl calculation."""
        remote = manifest_xml._XmlRemote(
            name="foo",
            fetch="git@github.com:org2/",
            manifestUrl="git@github.com:org2/custom_manifest.git",
        )
        assert remote.resolvedFetchUrl == "ssh://git@github.com/org2"

        remote = manifest_xml._XmlRemote(
            name="foo",
            fetch="ssh://git@github.com/org2/",
            manifestUrl="git@github.com:org2/custom_manifest.git",
        )
        assert remote.resolvedFetchUrl == "ssh://git@github.com/org2"

        remote = manifest_xml._XmlRemote(
            name="foo",
            fetch="git@github.com:org2/",
            manifestUrl="ssh://git@github.com/org2/custom_manifest.git",
        )
        assert remote.resolvedFetchUrl == "ssh://git@github.com/org2"
