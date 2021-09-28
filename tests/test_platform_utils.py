# Copyright 2021 The Android Open Source Project
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

"""Unittests for the platform_utils.py module."""

import os
import tempfile
import unittest

import platform_utils


class RemoveTests(unittest.TestCase):
  """Check remove() helper."""

  def testMissingOk(self):
    """Check missing_ok handling."""
    with tempfile.TemporaryDirectory() as tmpdir:
      path = os.path.join(tmpdir, 'test')

      # Should not fail.
      platform_utils.remove(path, missing_ok=True)

      # Should fail.
      self.assertRaises(OSError, platform_utils.remove, path)
      self.assertRaises(OSError, platform_utils.remove, path, missing_ok=False)

      # Should not fail if it exists.
      open(path, 'w').close()
      platform_utils.remove(path, missing_ok=True)
      self.assertFalse(os.path.exists(path))

      open(path, 'w').close()
      platform_utils.remove(path)
      self.assertFalse(os.path.exists(path))

      open(path, 'w').close()
      platform_utils.remove(path, missing_ok=False)
      self.assertFalse(os.path.exists(path))
