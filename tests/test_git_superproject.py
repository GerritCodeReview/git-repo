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
import tempfile
import unittest
from unittest import mock

from error import GitError
import git_superproject
import manifest_xml
import platform_utils


class SuperprojectTestCase(unittest.TestCase):
  """TestCase for the Superproject module."""

  def setUp(self):
    """Set up superproject every time."""
    self.tempdir = tempfile.mkdtemp(prefix='repo_tests')
    self.repodir = os.path.join(self.tempdir, '.repo')
    self._superproject = git_superproject.Superproject(self.repodir)
    self.manifest_file = os.path.join(
        self.repodir, manifest_xml.MANIFEST_FILE_NAME)
    os.mkdir(self.repodir)

    # The manifest parsing really wants a git repo currently.
    gitdir = os.path.join(self.repodir, 'manifests.git')
    os.mkdir(gitdir)
    with open(os.path.join(gitdir, 'config'), 'w') as fp:
      fp.write("""[remote "origin"]
        url = https://localhost:0/manifest
""")

  def tearDown(self):
    """Tear down superproject every time."""
    platform_utils.rmtree(self.tempdir)

  def getXmlManifest(self, data):
    """Helper to initialize a manifest for testing."""
    with open(self.manifest_file, 'w') as fp:
      fp.write(data)
    return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

  def test_superproject_get_project_shas_no_url(self):
    """Test with no url."""
    with self.assertRaises(ValueError):
      self._superproject._GetAllProjectsSHAs(url=None)

  def test_superproject_get_project_shas_invalid_url(self):
    """Test with an invalid url."""
    with self.assertRaises(GitError):
      self._superproject._GetAllProjectsSHAs(url='localhost')

  def test_superproject_get_project_shas_invalid_branch(self):
    """Test with an invalid branch."""
    with self.assertRaises(GitError):
      self._superproject._GetAllProjectsSHAs(
          url='sso://android/platform/superproject',
          branch='junk')

  def test_superproject_get_project_shas_mock_clone(self):
    """Test with _Clone failing."""
    with self.assertRaises(GitError):
      with mock.patch.object(self._superproject, '_Clone', return_value=False):
        self._superproject._GetAllProjectsSHAs(url='localhost')

  def test_superproject_get_project_shas_mock_pull(self):
    """Test with _Pull failing."""
    with self.assertRaises(GitError):
      with mock.patch.object(self._superproject, '_Clone', return_value=True):
        with mock.patch.object(self._superproject, '_Pull', return_value=False):
          self._superproject._GetAllProjectsSHAs(url='localhost')

  def test_superproject_get_project_shas_mock_ls_tree(self):
    """Test with LsTree being a mock."""
    data = ('120000 blob 158258bdf146f159218e2b90f8b699c4d85b5804\tAndroid.bp\x00'
            '160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00'
            '160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00'
            '120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00'
            '160000 commit ade9b7a0d874e25fff4bf2552488825c6f111928\tbuild/bazel\x00')
    with mock.patch.object(self._superproject, '_Clone', return_value=True):
      with mock.patch.object(self._superproject, '_LsTree', return_value=data):
        shas = self._superproject._GetAllProjectsSHAs(url='localhost', branch='junk')
        self.assertEqual(shas, {
            'art': '2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea',
            'bootable/recovery': 'e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06',
            'build/bazel': 'ade9b7a0d874e25fff4bf2552488825c6f111928'
        })

  def test_superproject_write_manifest_file(self):
    """Test with writing manifest to a file after setting revisionId."""
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
    # Create temporary directory so that it can write the file.
    os.mkdir(self._superproject._superproject_path)
    manifest_path = self._superproject._WriteManfiestFile(manifest)
    self.assertIsNotNone(manifest_path)
    with open(manifest_path, "r") as fp:
      manifest_xml = fp.read()
    self.assertEqual(
        manifest_xml,
        '<?xml version="1.0" ?><manifest>' +
        '<remote name="default-remote" fetch="http://localhost"/>' +
        '<default remote="default-remote" revision="refs/heads/main"/>' +
        '<project name="test-name" revision="ABCDEF"/>' +
        '</manifest>')

  def test_superproject_update_project_revision_id(self):
    """Test with LsTree being a mock."""
    manifest = self.getXmlManifest("""
<manifest>
  <remote name="default-remote" fetch="http://localhost" />
  <default remote="default-remote" revision="refs/heads/main" />
  <project path="art" name="platform/art" />
</manifest>
""")
    self.assertEqual(len(manifest.projects), 1)
    projects = manifest.projects
    data = ('160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00'
            '160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00')
    with mock.patch.object(self._superproject, '_Clone', return_value=True):
      with mock.patch.object(self._superproject, '_Pull', return_value=True):
        with mock.patch.object(self._superproject, '_LsTree', return_value=data):
          # Create temporary directory so that it can write the file.
          os.mkdir(self._superproject._superproject_path)
          manifest_path = self._superproject.UpdateProjectsRevisionId(
              manifest, projects, url='localhost')
          self.assertIsNotNone(manifest_path)
          with open(manifest_path, "r") as fp:
            manifest_xml = fp.read()
          self.assertEqual(
              manifest_xml,
              '<?xml version="1.0" ?><manifest>' +
              '<remote name="default-remote" fetch="http://localhost"/>' +
              '<default remote="default-remote" revision="refs/heads/main"/>' +
              '<project name="platform/art" path="art" ' +
              'revision="2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea"/>' +
              '</manifest>')


if __name__ == '__main__':
  unittest.main()
