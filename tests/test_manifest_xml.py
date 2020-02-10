# -*- coding:utf-8 -*-
#
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

from __future__ import print_function

import unittest

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
    for path in PATHS:
      self.assertRaises(
          error.ManifestInvalidPathError, self.check_both, path, 'a')
      self.assertRaises(
          error.ManifestInvalidPathError, self.check_both, 'a', path)
