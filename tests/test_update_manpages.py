# Copyright 2022 The Android Open Source Project
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

"""Unittests for the update_manpages module."""

import unittest

from release import update_manpages


class UpdateManpagesTest(unittest.TestCase):
  """Tests the update-manpages code."""

  def test_replace_regex(self):
    """Check that replace_regex works."""
    data = '\n\033[1mSummary\033[m\n'
    self.assertEqual(update_manpages.replace_regex(data),'\nSummary\n')
