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

import unittest

import git_superproject


class SuperprojectSHATestCase(unittest.TestCase):
  """TestCase for the SuperprojectSHA module."""

  def test_superproject_sha_no_url(self):
    """Test with no url."""
    superproject = git_superproject.SuperprojectSHA()
    self.assertIsNone(superproject.project_shas)

  def test_superproject_sha_invalid_url(self):
    """Test with an invalid url."""
    superproject = git_superproject.SuperprojectSHA(url="localhost")
    self.assertIsNone(superproject.project_shas)

  def test_superproject_sha_invalid_branch(self):
    """Test with an invalid branch."""
    superproject = git_superproject.SuperprojectSHA(url="sso://android/platform/superproject",
                                                    branch="junk")
    self.assertIsNone(superproject.project_shas)

  def test_superproject_sha_valid_url(self):
    """Test with valid url."""
    # TODO(rtenneti): Find a better way to test the following code.
    # superproject = git_superproject.SuperprojectSHA(url="sso://android/platform/superproject")
    # self.assertIsNotNone(superproject.project_shas)


if __name__ == '__main__':
  unittest.main()
