# -*- coding:utf-8 -*-
#
# Copyright (C) 2009 The Android Open Source Project
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

from manifest_xml import XmlManifest

def fixture():
  """Return a path relative to tests/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures')

class XmlManifestUnitTest(unittest.TestCase):
  """Tests the XmlManifest class."""

  def setUp(self):
    """Create a XmlManifest object from the manifest file."""
    manifest_dir = fixture()
    self.manifest = XmlManifest(manifest_dir)
    self.projects = []

  def test_projects_number(self):
    """Test the number of projects."""
    projects = self.manifest.projects
    self.assertEqual(len(projects), 6)

  def test_project_remote_fetchurl(self):
    """Test the project list."""
    projects = self.manifest.paths
    self.assertEqual(projects['m1/inc'].remote.fetchUrl, 'https://host_of_gerrit_1.com:889900')
    self.assertEqual(projects['m1/src'].remote.fetchUrl, 'https://host_of_gerrit_1.com:889900')
    self.assertEqual(projects['m2/inc'].remote.fetchUrl, 'https://host_of_gerrit_2.com:889900')
    self.assertEqual(projects['m2/inc'].remote.fetchUrl, 'https://host_of_gerrit_2.com:889900')
    self.assertEqual(projects['m3/inc'].remote.fetchUrl, 'https://host_of_gerrit_3.com:889900')
    self.assertEqual(projects['m3/inc'].remote.fetchUrl, 'https://host_of_gerrit_3.com:889900')
