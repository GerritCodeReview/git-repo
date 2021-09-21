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
import platform
import re
import shutil
import tempfile
import unittest
import xml.dom.minidom

import error
import manifest_xml


# Invalid paths that we don't want in the filesystem.
INVALID_FS_PATHS = (
    '',
    '.',
    '..',
    '../',
    './',
    './/',
    'foo/',
    './foo',
    '../foo',
    'foo/./bar',
    'foo/../../bar',
    '/foo',
    './../foo',
    '.git/foo',
    # Check case folding.
    '.GIT/foo',
    'blah/.git/foo',
    '.repo/foo',
    '.repoconfig',
    # Block ~ due to 8.3 filenames on Windows filesystems.
    '~',
    'foo~',
    'blah/foo~',
    # Block Unicode characters that get normalized out by filesystems.
    u'foo\u200Cbar',
    # Block newlines.
    'f\n/bar',
    'f\r/bar',
)

# Make sure platforms that use path separators (e.g. Windows) are also
# rejected properly.
if os.path.sep != '/':
  INVALID_FS_PATHS += tuple(x.replace('/', os.path.sep) for x in INVALID_FS_PATHS)


def sort_attributes(manifest):
  """Sort the attributes of all elements alphabetically.

  This is needed because different versions of the toxml() function from
  xml.dom.minidom outputs the attributes of elements in different orders.
  Before Python 3.8 they were output alphabetically, later versions preserve
  the order specified by the user.

  Args:
    manifest: String containing an XML manifest.

  Returns:
    The XML manifest with the attributes of all elements sorted alphabetically.
  """
  new_manifest = ''
  # This will find every element in the XML manifest, whether they have
  # attributes or not. This simplifies recreating the manifest below.
  matches = re.findall(r'(<[/?]?[a-z-]+\s*)((?:\S+?="[^"]+"\s*?)*)(\s*[/?]?>)', manifest)
  for head, attrs, tail in matches:
    m = re.findall(r'\S+?="[^"]+"', attrs)
    new_manifest += head + ' '.join(sorted(m)) + tail
  return new_manifest


class ManifestParseTestCase(unittest.TestCase):
  """TestCase for parsing manifests."""

  def setUp(self):
    self.tempdir = tempfile.mkdtemp(prefix='repo_tests')
    self.repodir = os.path.join(self.tempdir, '.repo')
    self.manifest_dir = os.path.join(self.repodir, 'manifests')
    self.manifest_file = os.path.join(
        self.repodir, manifest_xml.MANIFEST_FILE_NAME)
    self.local_manifest_dir = os.path.join(
        self.repodir, manifest_xml.LOCAL_MANIFESTS_DIR_NAME)
    os.mkdir(self.repodir)
    os.mkdir(self.manifest_dir)

    # The manifest parsing really wants a git repo currently.
    gitdir = os.path.join(self.repodir, 'manifests.git')
    os.mkdir(gitdir)
    with open(os.path.join(gitdir, 'config'), 'w') as fp:
      fp.write("""[remote "origin"]
        url = https://localhost:0/manifest
""")

  def tearDown(self):
    shutil.rmtree(self.tempdir, ignore_errors=True)

  def getXmlManifest(self, data):
    """Helper to initialize a manifest for testing."""
    with open(self.manifest_file, 'w') as fp:
      fp.write(data)
    return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

  @staticmethod
  def encodeXmlAttr(attr):
    """Encode |attr| using XML escape rules."""
    return attr.replace('\r', '&#x000d;').replace('\n', '&#x000a;')


class ManifestValidateFilePaths(unittest.TestCase):
  """Check _ValidateFilePaths helper.

  This doesn't access a real filesystem.
  """

  def check_both(self, *args):
    manifest_xml.XmlManifest._ValidateFilePaths('copyfile', *args)
    manifest_xml.XmlManifest._ValidateFilePaths('linkfile', *args)

  def test_normal_path(self):
    """Make sure good paths are accepted."""
    self.check_both('foo', 'bar')
    self.check_both('foo/bar', 'bar')
    self.check_both('foo', 'bar/bar')
    self.check_both('foo/bar', 'bar/bar')

  def test_symlink_targets(self):
    """Some extra checks for symlinks."""
    def check(*args):
      manifest_xml.XmlManifest._ValidateFilePaths('linkfile', *args)

    # We allow symlinks to end in a slash since we allow them to point to dirs
    # in general.  Technically the slash isn't necessary.
    check('foo/', 'bar')
    # We allow a single '.' to get a reference to the project itself.
    check('.', 'bar')

  def test_bad_paths(self):
    """Make sure bad paths (src & dest) are rejected."""
    for path in INVALID_FS_PATHS:
      self.assertRaises(
          error.ManifestInvalidPathError, self.check_both, path, 'a')
      self.assertRaises(
          error.ManifestInvalidPathError, self.check_both, 'a', path)


class ValueTests(unittest.TestCase):
  """Check utility parsing code."""

  def _get_node(self, text):
    return xml.dom.minidom.parseString(text).firstChild

  def test_bool_default(self):
    """Check XmlBool default handling."""
    node = self._get_node('<node/>')
    self.assertIsNone(manifest_xml.XmlBool(node, 'a'))
    self.assertIsNone(manifest_xml.XmlBool(node, 'a', None))
    self.assertEqual(123, manifest_xml.XmlBool(node, 'a', 123))

    node = self._get_node('<node a=""/>')
    self.assertIsNone(manifest_xml.XmlBool(node, 'a'))

  def test_bool_invalid(self):
    """Check XmlBool invalid handling."""
    node = self._get_node('<node a="moo"/>')
    self.assertEqual(123, manifest_xml.XmlBool(node, 'a', 123))

  def test_bool_true(self):
    """Check XmlBool true values."""
    for value in ('yes', 'true', '1'):
      node = self._get_node('<node a="%s"/>' % (value,))
      self.assertTrue(manifest_xml.XmlBool(node, 'a'))

  def test_bool_false(self):
    """Check XmlBool false values."""
    for value in ('no', 'false', '0'):
      node = self._get_node('<node a="%s"/>' % (value,))
      self.assertFalse(manifest_xml.XmlBool(node, 'a'))

  def test_int_default(self):
    """Check XmlInt default handling."""
    node = self._get_node('<node/>')
    self.assertIsNone(manifest_xml.XmlInt(node, 'a'))
    self.assertIsNone(manifest_xml.XmlInt(node, 'a', None))
    self.assertEqual(123, manifest_xml.XmlInt(node, 'a', 123))

    node = self._get_node('<node a=""/>')
    self.assertIsNone(manifest_xml.XmlInt(node, 'a'))

  def test_int_good(self):
    """Check XmlInt numeric handling."""
    for value in (-1, 0, 1, 50000):
      node = self._get_node('<node a="%s"/>' % (value,))
      self.assertEqual(value, manifest_xml.XmlInt(node, 'a'))

  def test_int_invalid(self):
    """Check XmlInt invalid handling."""
    with self.assertRaises(error.ManifestParseError):
      node = self._get_node('<node a="xx"/>')
      manifest_xml.XmlInt(node, 'a')


class XmlManifestTests(ManifestParseTestCase):
  """Check manifest processing."""

  def test_empty(self):
    """Parse an 'empty' manifest file."""
    manifest = self.getXmlManifest(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest></manifest>')
    self.assertEqual(manifest.remotes, {})
    self.assertEqual(manifest.projects, [])

  def test_link(self):
    """Verify Link handling with new names."""
    manifest = manifest_xml.XmlManifest(self.repodir, self.manifest_file)
    with open(os.path.join(self.manifest_dir, 'foo.xml'), 'w') as fp:
      fp.write('<manifest></manifest>')
    manifest.Link('foo.xml')
    with open(self.manifest_file) as fp:
      self.assertIn('<include name="foo.xml" />', fp.read())

  def test_toxml_empty(self):
    """Verify the ToXml() helper."""
    manifest = self.getXmlManifest(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest></manifest>')
    self.assertEqual(manifest.ToXml().toxml(), '<?xml version="1.0" ?><manifest/>')

  def test_todict_empty(self):
    """Verify the ToDict() helper."""
    manifest = self.getXmlManifest(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest></manifest>')
    self.assertEqual(manifest.ToDict(), {})

  def test_repo_hooks(self):
    """Check repo-hooks settings."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="repohooks" path="src/repohooks"/>
  <repo-hooks in-project="repohooks" enabled-list="a, b"/>
</manifest>
""")
    self.assertEqual(manifest.repo_hooks_project.name, 'repohooks')
    self.assertEqual(manifest.repo_hooks_project.enabled_repo_hooks, ['a', 'b'])

  def test_repo_hooks_unordered(self):
    """Check repo-hooks settings work even if the project def comes second."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <repo-hooks in-project="repohooks" enabled-list="a, b"/>
  <project name="repohooks" path="src/repohooks"/>
</manifest>
""")
    self.assertEqual(manifest.repo_hooks_project.name, 'repohooks')
    self.assertEqual(manifest.repo_hooks_project.enabled_repo_hooks, ['a', 'b'])

  def test_unknown_tags(self):
    """Check superproject settings."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <iankaz value="unknown (possible) future tags are ignored"/>
  <x-custom-tag>X tags are always ignored</x-custom-tag>
</manifest>
""")
    self.assertEqual(manifest.superproject['name'], 'superproject')
    self.assertEqual(manifest.superproject['remote'].name, 'test-remote')
    self.assertEqual(
        sort_attributes(manifest.ToXml().toxml()),
        '<?xml version="1.0" ?><manifest>'
        '<remote fetch="http://localhost" name="test-remote"/>'
        '<default remote="test-remote" revision="refs/heads/main"/>'
        '<superproject name="superproject"/>'
        '</manifest>')

  def test_remote_annotations(self):
    """Check remote settings."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="http://localhost">
    <annotation name="foo" value="bar"/>
  </remote>
</manifest>
""")
    self.assertEqual(manifest.remotes['test-remote'].annotations[0].name, 'foo')
    self.assertEqual(manifest.remotes['test-remote'].annotations[0].value, 'bar')
    self.assertEqual(
        sort_attributes(manifest.ToXml().toxml()),
        '<?xml version="1.0" ?><manifest>'
        '<remote fetch="http://localhost" name="test-remote">'
        '<annotation name="foo" value="bar"/>'
        '</remote>'
        '</manifest>')


class IncludeElementTests(ManifestParseTestCase):
  """Tests for <include>."""

  def test_group_levels(self):
    root_m = os.path.join(self.manifest_dir, 'root.xml')
    with open(root_m, 'w') as fp:
      fp.write("""
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <include name="level1.xml" groups="level1-group" />
  <project name="root-name1" path="root-path1" />
  <project name="root-name2" path="root-path2" groups="r2g1,r2g2" />
</manifest>
""")
    with open(os.path.join(self.manifest_dir, 'level1.xml'), 'w') as fp:
      fp.write("""
<manifest>
  <include name="level2.xml" groups="level2-group" />
  <project name="level1-name1" path="level1-path1" />
</manifest>
""")
    with open(os.path.join(self.manifest_dir, 'level2.xml'), 'w') as fp:
      fp.write("""
<manifest>
  <project name="level2-name1" path="level2-path1" groups="l2g1,l2g2" />
</manifest>
""")
    include_m = manifest_xml.XmlManifest(self.repodir, root_m)
    for proj in include_m.projects:
      if proj.name == 'root-name1':
        # Check include group not set on root level proj.
        self.assertNotIn('level1-group', proj.groups)
      if proj.name == 'root-name2':
        # Check root proj group not removed.
        self.assertIn('r2g1', proj.groups)
      if proj.name == 'level1-name1':
        # Check level1 proj has inherited group level 1.
        self.assertIn('level1-group', proj.groups)
      if proj.name == 'level2-name1':
        # Check level2 proj has inherited group levels 1 and 2.
        self.assertIn('level1-group', proj.groups)
        self.assertIn('level2-group', proj.groups)
        # Check level2 proj group not removed.
        self.assertIn('l2g1', proj.groups)

  def test_allow_bad_name_from_user(self):
    """Check handling of bad name attribute from the user's input."""
    def parse(name):
      name = self.encodeXmlAttr(name)
      manifest = self.getXmlManifest(f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <include name="{name}" />
</manifest>
""")
      # Force the manifest to be parsed.
      manifest.ToXml()

    # Setup target of the include.
    target = os.path.join(self.tempdir, 'target.xml')
    with open(target, 'w') as fp:
      fp.write('<manifest></manifest>')

    # Include with absolute path.
    parse(os.path.abspath(target))

    # Include with relative path.
    parse(os.path.relpath(target, self.manifest_dir))

  def test_bad_name_checks(self):
    """Check handling of bad name attribute."""
    def parse(name):
      name = self.encodeXmlAttr(name)
      # Setup target of the include.
      with open(os.path.join(self.manifest_dir, 'target.xml'), 'w') as fp:
        fp.write(f'<manifest><include name="{name}"/></manifest>')

      manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <include name="target.xml" />
</manifest>
""")
      # Force the manifest to be parsed.
      manifest.ToXml()

    # Handle empty name explicitly because a different codepath rejects it.
    with self.assertRaises(error.ManifestParseError):
      parse('')

    for path in INVALID_FS_PATHS:
      if not path:
        continue

      with self.assertRaises(error.ManifestInvalidPathError):
        parse(path)


class ProjectElementTests(ManifestParseTestCase):
  """Tests for <project>."""

  def test_group(self):
    """Check project group settings."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="test-name" path="test-path"/>
  <project name="extras" path="path" groups="g1,g2,g1"/>
</manifest>
""")
    self.assertEqual(len(manifest.projects), 2)
    # Ordering isn't guaranteed.
    result = {
        manifest.projects[0].name: manifest.projects[0].groups,
        manifest.projects[1].name: manifest.projects[1].groups,
    }
    project = manifest.projects[0]
    self.assertCountEqual(
        result['test-name'],
        ['name:test-name', 'all', 'path:test-path'])
    self.assertCountEqual(
        result['extras'],
        ['g1', 'g2', 'g1', 'name:extras', 'all', 'path:path'])
    groupstr = 'default,platform-' + platform.system().lower()
    self.assertEqual(groupstr, manifest.GetGroupsStr())
    groupstr = 'g1,g2,g1'
    manifest.manifestProject.config.SetString('manifest.groups', groupstr)
    self.assertEqual(groupstr, manifest.GetGroupsStr())

  def test_set_revision_id(self):
    """Check setting of project's revisionId."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="test-name"/>
</manifest>
""")
    self.assertEqual(len(manifest.projects), 1)
    project = manifest.projects[0]
    project.SetRevisionId('ABCDEF')
    self.assertEqual(
        sort_attributes(manifest.ToXml().toxml()),
        '<?xml version="1.0" ?><manifest>'
        '<remote fetch="http://localhost" name="default-remote"/>'
        '<default remote="default-remote" revision="refs/heads/main"/>'
        '<project name="test-name" revision="ABCDEF" upstream="refs/heads/main"/>'
        '</manifest>')

  def test_trailing_slash(self):
    """Check handling of trailing slashes in attributes."""
    def parse(name, path):
      name = self.encodeXmlAttr(name)
      path = self.encodeXmlAttr(path)
      return self.getXmlManifest(f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="{name}" path="{path}" />
</manifest>
""")

    manifest = parse('a/path/', 'foo')
    self.assertEqual(manifest.projects[0].gitdir,
                     os.path.join(self.tempdir, '.repo/projects/foo.git'))
    self.assertEqual(manifest.projects[0].objdir,
                     os.path.join(self.tempdir, '.repo/project-objects/a/path.git'))

    manifest = parse('a/path', 'foo/')
    self.assertEqual(manifest.projects[0].gitdir,
                     os.path.join(self.tempdir, '.repo/projects/foo.git'))
    self.assertEqual(manifest.projects[0].objdir,
                     os.path.join(self.tempdir, '.repo/project-objects/a/path.git'))

    manifest = parse('a/path', 'foo//////')
    self.assertEqual(manifest.projects[0].gitdir,
                     os.path.join(self.tempdir, '.repo/projects/foo.git'))
    self.assertEqual(manifest.projects[0].objdir,
                     os.path.join(self.tempdir, '.repo/project-objects/a/path.git'))

  def test_toplevel_path(self):
    """Check handling of path=. specially."""
    def parse(name, path):
      name = self.encodeXmlAttr(name)
      path = self.encodeXmlAttr(path)
      return self.getXmlManifest(f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="{name}" path="{path}" />
</manifest>
""")

    for path in ('.', './', './/', './//'):
      manifest = parse('server/path', path)
      self.assertEqual(manifest.projects[0].gitdir,
                       os.path.join(self.tempdir, '.repo/projects/..git'))

  def test_bad_path_name_checks(self):
    """Check handling of bad path & name attributes."""
    def parse(name, path):
      name = self.encodeXmlAttr(name)
      path = self.encodeXmlAttr(path)
      manifest = self.getXmlManifest(f"""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="{name}" path="{path}" />
</manifest>
""")
      # Force the manifest to be parsed.
      manifest.ToXml()

    # Verify the parser is valid by default to avoid buggy tests below.
    parse('ok', 'ok')

    # Handle empty name explicitly because a different codepath rejects it.
    # Empty path is OK because it defaults to the name field.
    with self.assertRaises(error.ManifestParseError):
      parse('', 'ok')

    for path in INVALID_FS_PATHS:
      if not path or path.endswith('/'):
        continue

      with self.assertRaises(error.ManifestInvalidPathError):
        parse(path, 'ok')

      # We have a dedicated test for path=".".
      if path not in {'.'}:
        with self.assertRaises(error.ManifestInvalidPathError):
          parse('ok', path)


class SuperProjectElementTests(ManifestParseTestCase):
  """Tests for <superproject>."""

  def test_superproject(self):
    """Check superproject settings."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
</manifest>
""")
    self.assertEqual(manifest.superproject['name'], 'superproject')
    self.assertEqual(manifest.superproject['remote'].name, 'test-remote')
    self.assertEqual(manifest.superproject['remote'].url, 'http://localhost/superproject')
    self.assertEqual(
        sort_attributes(manifest.ToXml().toxml()),
        '<?xml version="1.0" ?><manifest>'
        '<remote fetch="http://localhost" name="test-remote"/>'
        '<default remote="test-remote" revision="refs/heads/main"/>'
        '<superproject name="superproject"/>'
        '</manifest>')

  def test_remote(self):
    """Check superproject settings with a remote."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <remote name="superproject-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="platform/superproject" remote="superproject-remote"/>
</manifest>
""")
    self.assertEqual(manifest.superproject['name'], 'platform/superproject')
    self.assertEqual(manifest.superproject['remote'].name, 'superproject-remote')
    self.assertEqual(manifest.superproject['remote'].url, 'http://localhost/platform/superproject')
    self.assertEqual(
        sort_attributes(manifest.ToXml().toxml()),
        '<?xml version="1.0" ?><manifest>'
        '<remote fetch="http://localhost" name="default-remote"/>'
        '<remote fetch="http://localhost" name="superproject-remote"/>'
        '<default remote="default-remote" revision="refs/heads/main"/>'
        '<superproject name="platform/superproject" remote="superproject-remote"/>'
        '</manifest>')

  def test_defalut_remote(self):
    """Check superproject settings with a default remote."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject" remote="default-remote"/>
</manifest>
""")
    self.assertEqual(manifest.superproject['name'], 'superproject')
    self.assertEqual(manifest.superproject['remote'].name, 'default-remote')
    self.assertEqual(
        sort_attributes(manifest.ToXml().toxml()),
        '<?xml version="1.0" ?><manifest>'
        '<remote fetch="http://localhost" name="default-remote"/>'
        '<default remote="default-remote" revision="refs/heads/main"/>'
        '<superproject name="superproject"/>'
        '</manifest>')


class ContactinfoElementTests(ManifestParseTestCase):
  """Tests for <contactinfo>."""

  def test_contactinfo(self):
    """Check contactinfo settings."""
    bugurl = 'http://localhost/contactinfo'
    manifest = self.getXmlManifest(f"""
<manifest>
  <contactinfo bugurl="{bugurl}"/>
</manifest>
""")
    self.assertEqual(manifest.contactinfo.bugurl, bugurl)
    self.assertEqual(
        manifest.ToXml().toxml(),
        '<?xml version="1.0" ?><manifest>'
        f'<contactinfo bugurl="{bugurl}"/>'
        '</manifest>')


class DefaultElementTests(ManifestParseTestCase):
  """Tests for <default>."""

  def test_default(self):
    """Check default settings."""
    a = manifest_xml._Default()
    a.revisionExpr = 'foo'
    a.remote = manifest_xml._XmlRemote(name='remote')
    b = manifest_xml._Default()
    b.revisionExpr = 'bar'
    self.assertEqual(a, a)
    self.assertNotEqual(a, b)
    self.assertNotEqual(b, a.remote)
    self.assertNotEqual(a, 123)
    self.assertNotEqual(a, None)


class RemoteElementTests(ManifestParseTestCase):
  """Tests for <remote>."""

  def test_remote(self):
    """Check remote settings."""
    a = manifest_xml._XmlRemote(name='foo')
    a.AddAnnotation('key1', 'value1', 'true')
    b = manifest_xml._XmlRemote(name='foo')
    b.AddAnnotation('key2', 'value1', 'true')
    c = manifest_xml._XmlRemote(name='foo')
    c.AddAnnotation('key1', 'value2', 'true')
    d = manifest_xml._XmlRemote(name='foo')
    d.AddAnnotation('key1', 'value1', 'false')
    self.assertEqual(a, a)
    self.assertNotEqual(a, b)
    self.assertNotEqual(a, c)
    self.assertNotEqual(a, d)
    self.assertNotEqual(a, manifest_xml._Default())
    self.assertNotEqual(a, 123)
    self.assertNotEqual(a, None)


class RemoveProjectElementTests(ManifestParseTestCase):
  """Tests for <remove-project>."""

  def test_remove_one_project(self):
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <remove-project name="myproject" />
</manifest>
""")
    self.assertEqual(manifest.projects, [])

  def test_remove_one_project_one_remains(self):
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project name="myproject" />
  <project name="yourproject" />
  <remove-project name="myproject" />
</manifest>
""")

    self.assertEqual(len(manifest.projects), 1)
    self.assertEqual(manifest.projects[0].name, 'yourproject')

  def test_remove_one_project_doesnt_exist(self):
    with self.assertRaises(manifest_xml.ManifestParseError):
      manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <remove-project name="myproject" />
</manifest>
""")
      manifest.projects

  def test_remove_one_optional_project_doesnt_exist(self):
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <remove-project name="myproject" optional="true" />
</manifest>
""")
    self.assertEqual(manifest.projects, [])
