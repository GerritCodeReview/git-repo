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

import os
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
