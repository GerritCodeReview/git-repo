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

"""Unittests for the git_config.py module."""

import os
import tempfile
import unittest

import git_config
import repo_trace
import pyfakefs



class RepoTraceTests(pyfakefs.fake_filesystem_unittest.TestCase):
  """Read-only tests of the GitConfig class."""

  def setUp(self):
    """Create a GitConfig object using the test.gitconfig fixture.
    """

    self.tempdirobj = tempfile.TemporaryDirectory(prefix='repo_tests')
    repo_trace._TRACE_FILE = os.path.join(self.tempdirobj.name, 'TRACE_FILE_from_test')

    with open('TEST_CHICKEN', mode='wb') as f:
        f.truncate(1048576)

    repo_trace._TRACE_FILE = 'TEST_CHICKEN'
    repo_trace._MAX_SIZE = .5

    self.setUpPyfakefs()

  def tearDown(self):
    self.tempdirobj.cleanup()

  def testTrace(self):
    with open('TEST_CHICKEN', mode='wb') as f:
      f.truncate(1048576)
    with repo_trace.Trace('Testing: command -arg1=%s', 'chicken', first_trace=True):
      print('testing trace')
