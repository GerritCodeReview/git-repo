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


def fixture(*paths):
  """Return a path relative to tests/fixtures."""
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)


class SuperprojectTestCase(unittest.TestCase):
  """TestCase for the Superproject module."""

  def setUp(self):
    """Set up superoroject every time."""
    self.tempdir = tempfile.mkdtemp(prefix='repo_tests')
    self.repodir = os.path.join(self.tempdir, '.repo')
    os.mkdir(self.repodir)
    self._superproject = git_superproject.Superproject(self.repodir)

  def tearDown(self):
    platform_utils.rmtree(self.tempdir)

  def test_superproject_get_project_shas_no_url(self):
    """Test with no url."""
    with self.assertRaises(ValueError):
      self._superproject.GetAllProjectsSHAs(url=None)

  def test_superproject_get_project_shas_invalid_url(self):
    """Test with an invalid url."""
    with self.assertRaises(GitError):
      self._superproject.GetAllProjectsSHAs(url="localhost")

  def test_superproject_get_project_shas_invalid_branch(self):
    """Test with an invalid branch."""
    with self.assertRaises(GitError):
      self._superproject.GetAllProjectsSHAs(
          url="sso://android/platform/superproject",
          branch="junk")

  def test_superproject_get_project_shas_mock_clone(self):
    """Test with _Clone failing."""
    with self.assertRaises(GitError):
      with mock.patch.object(self._superproject, '_Clone', return_value=False):
        self._superproject.GetAllProjectsSHAs(url="localhost")

  def test_superproject_get_project_shas_mock_ls_tree(self):
    """Test with LsTree being a mock."""
    filename = fixture('test_ls_tree.data')
    with open(filename, 'r', encoding='utf-8') as my_file:
      data = my_file.read()
    with mock.patch.object(self._superproject, '_Clone', return_value=True):
      with mock.patch.object(self._superproject, '_LsTree', return_value=data):
        shas = self._superproject.GetAllProjectsSHAs(url='localhost', branch='junk')
        self.assertEqual(len(shas), 3)
        self.assertEqual(shas, {'art': 'ef28d24d7625943cc2b53e10bbece86a305b3ffd',
                                'bootable/recovery': '40d4bc9e199d93dd62615d512b24ec5d5d600075',
                                'build/bazel': '600f42f7e6dfbb98e5ccb0fd7a565cd30239c7db'})


if __name__ == '__main__':
  unittest.main()
