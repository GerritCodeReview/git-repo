# Copyright (C) 2026 The Android Open Source Project
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

import optparse
import re
from typing import List

from command import Command
from command import MirrorSafeCommand
from error import SilentRepoExitError
from git_config import RepoConfig


class NotSetError(SilentRepoExitError):
    """Exit quietly when a requested setting is not set, like `git config`."""


# Matches `section.name` or `section.subsection.name` like git does.  The
# section and the final name are restricted to alphanumerics and dashes, and
# the name must not start with a digit.  Any subsection is accepted verbatim.
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*\.(.+\.)?[A-Za-z][A-Za-z0-9-]*$")


class Config(Command, MirrorSafeCommand):
    """Read and write repo's per-user settings."""

    COMMON = False
    helpSummary = "Read and write per-user repo settings"
    helpUsage = """
%prog <name>
%prog <name> <value>
%prog --unset <name>
%prog --list
"""
    helpDescription = """
The '%prog' command reads and writes repo's own per-user settings, which are
stored in ~/.repoconfig/config (or $REPO_CONFIG_DIR/.repoconfig/config if that
environment variable is set).  The file uses the git-config format, so
'%prog' is a convenience wrapper around:

  git config --file ~/.repoconfig/config ...

Settings are named <section>.<name>, e.g. sync.smartsync.  See
docs/repoconfig.md for the list of settings repo understands.

Examples:

  # Always smart sync by default.
  $ repo config sync.smartsync true

  # Show the current value.
  $ repo config sync.smartsync

  # Go back to following the manifest default.
  $ repo config --unset sync.smartsync

  # Show all per-user settings.
  $ repo config --list
"""

    def _Options(self, p: optparse.OptionParser) -> None:
        p.add_option(
            "-l",
            "--list",
            action="store_true",
            help="list all settings and their values",
        )
        p.add_option(
            "--unset",
            action="store_true",
            help="remove the setting",
        )

    def ValidateOptions(self, opt: optparse.Values, args: List[str]) -> None:
        if opt.list and opt.unset:
            self.OptionParser.error("--list and --unset cannot be combined")

        if opt.list:
            if args:
                self.OptionParser.error("--list does not take arguments")
            return

        if opt.unset:
            if len(args) != 1:
                self.OptionParser.error("--unset requires exactly one <name>")
        elif not 1 <= len(args) <= 2:
            self.Usage()

        name = args[0]
        if not _KEY_RE.match(name):
            self.OptionParser.error(
                f"invalid setting name '{name}'; expected <section>.<name>"
            )

    @staticmethod
    def _GetConfig() -> RepoConfig:
        """Returns the per-user config.

        Split out so tests can easily substitute their own instance.
        """
        return RepoConfig.ForUser()

    def Execute(self, opt: optparse.Values, args: List[str]) -> None:
        config = self._GetConfig()

        if opt.list:
            for key, value in sorted(config.DumpConfigDict().items()):
                print(f"{key}={value}")
            return

        name = args[0]
        if opt.unset:
            config.SetString(name, None)
        elif len(args) == 2:
            config.SetString(name, args[1])
        else:
            values = config.GetString(name, all_keys=True)
            if not values:
                # Match `git config`: a missing key is a quiet exit 1.
                raise NotSetError(exit_code=1)
            for value in values:
                print(value)
