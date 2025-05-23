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

"""Unittests for the hooks.py module."""

import hooks
import unittest

class RepoHookShebang(unittest.TestCase):
  """Check shebang parsing in RepoHook."""

  def test_no_shebang(self):
    """Lines w/out shebangs should be rejected."""
    DATA = (
        '',
        '#\n# foo\n',
        '# Bad shebang in script\n#!/foo\n'
    )
    for data in DATA:
      self.assertIsNone(hooks.RepoHook._ExtractInterpFromShebang(data))

  def test_direct_interp(self):
    """Lines whose shebang points directly to the interpreter."""
    DATA = (
        ('#!/foo', '/foo'),
        ('#! /foo', '/foo'),
        ('#!/bin/foo ', '/bin/foo'),
        ('#! /usr/foo ', '/usr/foo'),
        ('#! /usr/foo -args', '/usr/foo'),
    )
    for shebang, interp in DATA:
      self.assertEqual(hooks.RepoHook._ExtractInterpFromShebang(shebang),
                       interp)

  def test_env_interp(self):
    """Lines whose shebang launches through `env`."""
    DATA = (
        ('#!/usr/bin/env foo', 'foo'),
        ('#!/bin/env foo', 'foo'),
        ('#! /bin/env /bin/foo ', '/bin/foo'),
    )
    for shebang, interp in DATA:
      self.assertEqual(hooks.RepoHook._ExtractInterpFromShebang(shebang),
                       interp)
