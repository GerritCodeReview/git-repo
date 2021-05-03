# Copyright (C) 2021 The Android Open Source Project
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

"""Unittests for the git_superproject.py module."""

import os
import platform
import tempfile
import unittest
from unittest import mock

import git_superproject
import manifest_xml
import platform_utils


class SuperprojectTestCase(unittest.TestCase):
  """TestCase for the Superproject module."""

  def setUp(self):
    """Set up superproject every time."""
    self.tempdir = tempfile.mkdtemp(prefix='repo_tests')
    self.repodir = os.path.join(self.tempdir, '.repo')
    self.manifest_file = os.path.join(
        self.repodir, manifest_xml.MANIFEST_FILE_NAME)
    os.mkdir(self.repodir)
    self.platform = platform.system().lower()

    # The manifest parsing really wants a git repo currently.
    gitdir = os.path.join(self.repodir, 'manifests.git')
    os.mkdir(gitdir)
    with open(os.path.join(gitdir, 'config'), 'w') as fp:
      fp.write("""[remote "origin"]
        url = https://localhost:0/manifest
""")

    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <project path="art" name="platform/art" groups="notdefault,platform-""" + self.platform + """
  " /></manifest>
""")
    self._superproject = git_superproject.Superproject(manifest, self.repodir)

  def tearDown(self):
    """Tear down superproject every time."""
    platform_utils.rmtree(self.tempdir)

  def getXmlManifest(self, data):
    """Helper to initialize a manifest for testing."""
    with open(self.manifest_file, 'w') as fp:
      fp.write(data)
    return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

  def test_superproject_get_superproject_no_superproject(self):
    """Test with no url."""
    manifest = self.getXmlManifest("""
<manifest>
</manifest>
""")
    superproject = git_superproject.Superproject(manifest, self.repodir)
    self.assertFalse(superproject.Sync())

  def test_superproject_get_superproject_invalid_url(self):
    """Test with an invalid url."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
</manifest>
""")
    superproject = git_superproject.Superproject(manifest, self.repodir)
    self.assertFalse(superproject.Sync())

  def test_superproject_get_superproject_invalid_branch(self):
    """Test with an invalid branch."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="test-remote" fetch="localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
</manifest>
""")
    superproject = git_superproject.Superproject(manifest, self.repodir)
    with mock.patch.object(self._superproject, '_GetBranch', return_value='junk'):
      self.assertFalse(superproject.Sync())

  def test_superproject_get_superproject_mock_init(self):
    """Test with _Init failing."""
    with mock.patch.object(self._superproject, '_Init', return_value=False):
      self.assertFalse(self._superproject.Sync())

  def test_superproject_get_superproject_mock_fetch(self):
    """Test with _Fetch failing."""
    with mock.patch.object(self._superproject, '_Init', return_value=True):
      os.mkdir(self._superproject._superproject_path)
      with mock.patch.object(self._superproject, '_Fetch', return_value=False):
        self.assertFalse(self._superproject.Sync())

  def test_superproject_get_all_project_commit_ids_mock_ls_tree(self):
    """Test with LsTree being a mock."""
    data = ('120000 blob 158258bdf146f159218e2b90f8b699c4d85b5804\tAndroid.bp\x00'
            '160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00'
            '160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00'
            '120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00'
            '160000 commit ade9b7a0d874e25fff4bf2552488825c6f111928\tbuild/bazel\x00')
    with mock.patch.object(self._superproject, '_Init', return_value=True):
      with mock.patch.object(self._superproject, '_Fetch', return_value=True):
        with mock.patch.object(self._superproject, '_LsTree', return_value=data):
          commit_ids = self._superproject._GetAllProjectsCommitIds()
          self.assertEqual(commit_ids, {
              'art': '2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea',
              'bootable/recovery': 'e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06',
              'build/bazel': 'ade9b7a0d874e25fff4bf2552488825c6f111928'
          })

  def test_superproject_write_manifest_file(self):
    """Test with writing manifest to a file after setting revisionId."""
    self.assertEqual(len(self._superproject._manifest.projects), 1)
    project = self._superproject._manifest.projects[0]
    project.SetRevisionId('ABCDEF')
    # Create temporary directory so that it can write the file.
    os.mkdir(self._superproject._superproject_path)
    manifest_path = self._superproject._WriteManfiestFile()
    self.assertIsNotNone(manifest_path)
    with open(manifest_path, 'r') as fp:
      manifest_xml = fp.read()
    self.assertEqual(
        manifest_xml,
        '<?xml version="1.0" ?><manifest>'
        '<remote name="default-remote" fetch="http://localhost"/>'
        '<default remote="default-remote" revision="refs/heads/main"/>'
        '<project name="platform/art" path="art" revision="ABCDEF" '
        'groups="notdefault,platform-' + self.platform + '"/>'
        '<superproject name="superproject"/>'
        '</manifest>')

  def test_superproject_update_project_revision_id(self):
    """Test with LsTree being a mock."""
    self.assertEqual(len(self._superproject._manifest.projects), 1)
    projects = self._superproject._manifest.projects
    data = ('160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00'
            '160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00')
    with mock.patch.object(self._superproject, '_Init', return_value=True):
      with mock.patch.object(self._superproject, '_Fetch', return_value=True):
        with mock.patch.object(self._superproject,
                               '_LsTree',
                               return_value=data):
          # Create temporary directory so that it can write the file.
          os.mkdir(self._superproject._superproject_path)
          manifest_path = self._superproject.UpdateProjectsRevisionId(projects)
          self.assertIsNotNone(manifest_path)
          with open(manifest_path, 'r') as fp:
            manifest_xml = fp.read()
          self.assertEqual(
              manifest_xml,
              '<?xml version="1.0" ?><manifest>'
              '<remote name="default-remote" fetch="http://localhost"/>'
              '<default remote="default-remote" revision="refs/heads/main"/>'
              '<project name="platform/art" path="art" '
              'revision="2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea" '
              'groups="notdefault,platform-' + self.platform + '"/>'
              '<superproject name="superproject"/>'
              '</manifest>')

  def test_superproject_update_project_revision_id_with_different_remotes(self):
    """Test update of commit ids of a manifest with mutiple remotes."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <remote name="goog" fetch="http://localhost2" />
  <default remote="default-remote" revision="refs/heads/main" />
  <superproject name="superproject"/>
  <project path="vendor/x" name="platform/vendor/x" remote="goog" groups="vendor"
           revision="master-with-vendor" clone-depth="1" />
  <project path="art" name="platform/art" groups="notdefault,platform-""" + self.platform + """
  " /></manifest>
""")
    self.maxDiff = None
    self._superproject = git_superproject.Superproject(manifest, self.repodir)
    self.assertEqual(len(self._superproject._manifest.projects), 2)
    projects = self._superproject._manifest.projects
    data = ('160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00'
            '160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00')
    with mock.patch.object(self._superproject, '_Init', return_value=True):
      with mock.patch.object(self._superproject, '_Fetch', return_value=True):
        with mock.patch.object(self._superproject,
                               '_LsTree',
                               return_value=data):
          # Create temporary directory so that it can write the file.
          os.mkdir(self._superproject._superproject_path)
          manifest_path = self._superproject.UpdateProjectsRevisionId(projects)
          self.assertIsNotNone(manifest_path)
          with open(manifest_path, 'r') as fp:
            manifest_xml = fp.read()
          self.assertEqual(
              manifest_xml,
              '<?xml version="1.0" ?><manifest>'
              '<remote name="default-remote" fetch="http://localhost"/>'
              '<remote name="goog" fetch="http://localhost2"/>'
              '<default remote="default-remote" revision="refs/heads/main"/>'
              '<project name="platform/art" path="art" '
              'revision="2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea" '
              'groups="notdefault,platform-' + self.platform + '"/>'
              '<project name="platform/vendor/x" path="vendor/x" remote="goog" '
              'revision="master-with-vendor" groups="vendor" clone-depth="1"/>'
              '<superproject name="superproject"/>'
              '</manifest>')


if __name__ == '__main__':
  unittest.main()
