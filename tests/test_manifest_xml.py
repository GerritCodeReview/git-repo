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


class ManifestValidateCopyFilePaths(unittest.TestCase):
  """Check _ValidateCopyFilePaths helper.

  This doesn't access a real filesystem.
  """

  def setUp(self):
    self.check = manifest_xml.XmlManifest._ValidateCopyFilePaths

  def testNormalPath(self):
    """Make sure good paths are accepted."""
    self.check('foo', 'bar')
    self.check('foo/bar', 'bar')
    self.check('./foo', './bar')
    self.check('./foo/bar/cow', './foo/bar/milk')
    self.check('./foo/../bar', './foo')
    self.check('./././foo', './bar')

  def testBadPaths(self):
    """Make sure bad paths are rejected."""
    PATHS = (
        '..',
        '../',
        '../foo',
        'foo/../../bar',
        '/foo',
        './../foo',
    )
    for path in PATHS:
      self.assertRaises(error.ManifestInvalidPathError, self.check, path, 'a')
      self.assertRaises(error.ManifestInvalidPathError, self.check, 'a', path)


class ManifestValidateLinkFilePaths(unittest.TestCase):
  """Check _ValidateLinkFilePaths helper.

  This doesn't access a real filesystem.
  """

  def setUp(self):
    self.check = manifest_xml.XmlManifest._ValidateLinkFilePaths

  def testNormalPath(self):
    """Make sure good paths are accepted."""
    self.check('foo', 'bar')
    self.check('foo/bar', 'bar')
    self.check('./foo', './bar')
    self.check('./foo/bar/cow', './foo/bar/milk')
    self.check('./foo/../bar', './foo')
    self.check('./././foo', './bar')

  def testBadPaths(self):
    """Make sure bad paths are rejected."""
    PATHS = (
        '..',
        '../',
        '../foo',
        'foo/../../bar',
        '/foo',
        './../foo',
    )
    for path in PATHS:
      self.assertRaises(error.ManifestInvalidPathError, self.check, path, 'a')
      self.assertRaises(error.ManifestInvalidPathError, self.check, 'a', path)
