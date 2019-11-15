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

"""Unittests for the editor.py module."""

from __future__ import print_function

import unittest

from editor import Editor


class EditorTestCase(unittest.TestCase):
  """Take care of resetting Editor state across tests."""

  def setUp(self):
    self.setEditor(None)

  def tearDown(self):
    self.setEditor(None)

  @staticmethod
  def setEditor(editor):
    Editor._editor = editor


class GetEditor(EditorTestCase):
  """Check GetEditor behavior."""

  def test_basic(self):
    """Basic checking of _GetEditor."""
    self.setEditor(':')
    self.assertEqual(':', Editor._GetEditor())


class EditString(EditorTestCase):
  """Check EditString behavior."""

  def test_no_editor(self):
    """Check behavior when no editor is available."""
    self.setEditor(':')
    self.assertEqual('foo', Editor.EditString('foo'))

  def test_cat_editor(self):
    """Check behavior when editor is `cat`."""
    self.setEditor('cat')
    self.assertEqual('foo', Editor.EditString('foo'))
