# Copyright 2019 The Android Open Source Project
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

"""Unittests for the ssh.py module."""

import unittest
from unittest import mock

import ssh


class SshTests(unittest.TestCase):
  """Tests the ssh functions."""

  def test_parse_ssh_version(self):
    """Check _parse_ssh_version() handling."""
    ver = ssh._parse_ssh_version('Unknown\n')
    self.assertEqual(ver, ())
    ver = ssh._parse_ssh_version('OpenSSH_1.0\n')
    self.assertEqual(ver, (1, 0))
    ver = ssh._parse_ssh_version('OpenSSH_6.6.1p1 Ubuntu-2ubuntu2.13, OpenSSL 1.0.1f 6 Jan 2014\n')
    self.assertEqual(ver, (6, 6, 1))
    ver = ssh._parse_ssh_version('OpenSSH_7.6p1 Ubuntu-4ubuntu0.3, OpenSSL 1.0.2n  7 Dec 2017\n')
    self.assertEqual(ver, (7, 6))

  def test_version(self):
    """Check version() handling."""
    with mock.patch('ssh._run_ssh_version', return_value='OpenSSH_1.2\n'):
      self.assertEqual(ssh.version(), (1, 2))

  def test_ssh_sock(self):
    """Check sock() function."""
    with mock.patch('tempfile.mkdtemp', return_value='/tmp/foo'):
      # old ssh version uses port
      with mock.patch('ssh.version', return_value=(6, 6)):
        self.assertTrue(ssh.sock().endswith('%p'))
      ssh._ssh_sock_path = None
      # new ssh version uses hash
      with mock.patch('ssh.version', return_value=(6, 7)):
        self.assertTrue(ssh.sock().endswith('%C'))
      ssh._ssh_sock_path = None
