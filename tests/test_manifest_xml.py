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
import shutil
import tempfile
import unittest
import xml.dom.minidom

import error
import manifest_xml


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
    PATHS = (
        '..',
        '../',
        './',
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
    )
    # Make sure platforms that use path separators (e.g. Windows) are also
    # rejected properly.
    if os.path.sep != '/':
      PATHS += tuple(x.replace('/', os.path.sep) for x in PATHS)

    for path in PATHS:
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


class XmlManifestTests(unittest.TestCase):
  """Check manifest processing."""

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
        manifest.ToXml().toxml(),
        '<?xml version="1.0" ?><manifest>' +
        '<remote name="test-remote" fetch="http://localhost"/>' +
        '<default remote="test-remote" revision="refs/heads/main"/>' +
        '<superproject name="superproject"/>' +
        '</manifest>')

  def test_superproject_with_remote(self):
    """Check superproject settings."""
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
        manifest.ToXml().toxml(),
        '<?xml version="1.0" ?><manifest>' +
        '<remote name="default-remote" fetch="http://localhost"/>' +
        '<remote name="superproject-remote" fetch="http://localhost"/>' +
        '<default remote="default-remote" revision="refs/heads/main"/>' +
        '<superproject name="platform/superproject" remote="superproject-remote"/>' +
        '</manifest>')

  def test_superproject_with_defalut_remote(self):
    """Check superproject settings."""
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
        manifest.ToXml().toxml(),
        '<?xml version="1.0" ?><manifest>' +
        '<remote name="default-remote" fetch="http://localhost"/>' +
        '<default remote="default-remote" revision="refs/heads/main"/>' +
        '<superproject name="superproject"/>' +
        '</manifest>')

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
        manifest.ToXml().toxml(),
        '<?xml version="1.0" ?><manifest>' +
        '<remote name="test-remote" fetch="http://localhost"/>' +
        '<default remote="test-remote" revision="refs/heads/main"/>' +
        '<superproject name="superproject"/>' +
        '</manifest>')

  def test_project_group(self):
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

  def test_project_set_revision_id(self):
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
        manifest.ToXml().toxml(),
        '<?xml version="1.0" ?><manifest>' +
        '<remote name="default-remote" fetch="http://localhost"/>' +
        '<default remote="default-remote" revision="refs/heads/main"/>' +
        '<project name="test-name" revision="ABCDEF"/>' +
        '</manifest>')

  def test_include_levels(self):
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
