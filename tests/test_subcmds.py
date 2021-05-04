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

"""Unittests for the subcmds module (mostly __init__.py than subcommands)."""

import optparse
import unittest

import subcmds


class AllCommands(unittest.TestCase):
  """Check registered all_commands."""

  def test_required_basic(self):
    """Basic checking of registered commands."""
    # NB: We don't test all subcommands as we want to avoid "change detection"
    # tests, so we just look for the most common/important ones here that are
    # unlikely to ever change.
    for cmd in {'cherry-pick', 'help', 'init', 'start', 'sync', 'upload'}:
      self.assertIn(cmd, subcmds.all_commands)

  def test_naming(self):
    """Verify we don't add things that we shouldn't."""
    for cmd in subcmds.all_commands:
      # Reject filename suffixes like "help.py".
      self.assertNotIn('.', cmd)

      # Make sure all '_' were converted to '-'.
      self.assertNotIn('_', cmd)

      # Reject internal python paths like "__init__".
      self.assertFalse(cmd.startswith('__'))

  def test_help_desc_style(self):
    """Force some consistency in option descriptions.

    Python's optparse & argparse has a few default options like --help.  Their
    option description text uses lowercase sentence fragments, so enforce our
    options follow the same style so UI is consistent.

    We enforce:
    * Text starts with lowercase.
    * Text doesn't end with period.
    """
    for name, cls in subcmds.all_commands.items():
      cmd = cls()
      parser = cmd.OptionParser
      for option in parser.option_list:
        if option.help == optparse.SUPPRESS_HELP:
          continue

        c = option.help[0]
        self.assertEqual(
            c.lower(), c,
            msg=f'subcmds/{name}.py: {option.get_opt_string()}: help text '
                f'should start with lowercase: "{option.help}"')

        self.assertNotEqual(
            option.help[-1], '.',
            msg=f'subcmds/{name}.py: {option.get_opt_string()}: help text '
                f'should not end in a period: "{option.help}"')
