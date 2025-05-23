# Copyright (C) 2020 The Android Open Source Project
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

"""Unittests for the subcmds/init.py module."""

import unittest

from subcmds import init


class InitCommand(unittest.TestCase):
  """Check registered all_commands."""

  def setUp(self):
    self.cmd = init.Init()

  def test_cli_parser_good(self):
    """Check valid command line options."""
    ARGV = (
        [],
    )
    for argv in ARGV:
      opts, args = self.cmd.OptionParser.parse_args(argv)
      self.cmd.ValidateOptions(opts, args)

  def test_cli_parser_bad(self):
    """Check invalid command line options."""
    ARGV = (
        # Too many arguments.
        ['url', 'asdf'],

        # Conflicting options.
        ['--mirror', '--archive'],
    )
    for argv in ARGV:
      opts, args = self.cmd.OptionParser.parse_args(argv)
      with self.assertRaises(SystemExit):
        self.cmd.ValidateOptions(opts, args)
