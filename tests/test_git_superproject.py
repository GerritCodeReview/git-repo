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
import platform_utils


class SuperprojectTestCase(unittest.TestCase):
  """TestCase for the Superproject module."""

  def setUp(self):
    """Set up superproject every time."""
    self.tempdir = tempfile.mkdtemp(prefix='repo_tests')
    self.repodir = os.path.join(self.tempdir, '.repo')
    os.mkdir(self.repodir)
    self._superproject = git_superproject.Superproject(self.repodir)

  def tearDown(self):
    """Tear down superproject every time."""
    platform_utils.rmtree(self.tempdir)

  def test_superproject_get_project_shas_no_url(self):
    """Test with no url."""
    with self.assertRaises(ValueError):
      self._superproject.GetAllProjectsSHAs(url=None)

  def test_superproject_get_project_shas_invalid_url(self):
    """Test with an invalid url."""
    with self.assertRaises(GitError):
      self._superproject.GetAllProjectsSHAs(url='localhost')

  def test_superproject_get_project_shas_invalid_branch(self):
    """Test with an invalid branch."""
    with self.assertRaises(GitError):
      self._superproject.GetAllProjectsSHAs(
          url='sso://android/platform/superproject',
          branch='junk')

  def test_superproject_get_project_shas_mock_clone(self):
    """Test with _Clone failing."""
    with self.assertRaises(GitError):
      with mock.patch.object(self._superproject, '_Clone', return_value=False):
        self._superproject.GetAllProjectsSHAs(url='localhost')

  def test_superproject_get_project_shas_mock_ls_tree(self):
    """Test with LsTree being a mock."""
    data = ('120000 blob 158258bdf146f159218e2b90f8b699c4d85b5804\tAndroid.bp\x00'
            '160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00'
            '160000 commit e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06\tbootable/recovery\x00'
            '120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00'
            '160000 commit ade9b7a0d874e25fff4bf2552488825c6f111928\tbuild/bazel\x00')
    with mock.patch.object(self._superproject, '_Clone', return_value=True):
      with mock.patch.object(self._superproject, '_LsTree', return_value=data):
        shas = self._superproject.GetAllProjectsSHAs(url='localhost', branch='junk')
        self.assertEqual(shas, {
            'art': '2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea',
            'bootable/recovery': 'e9d25da64d8d365dbba7c8ee00fe8c4473fe9a06',
            'build/bazel': 'ade9b7a0d874e25fff4bf2552488825c6f111928'
        })


if __name__ == '__main__':
  unittest.main()
