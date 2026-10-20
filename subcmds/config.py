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
from error import GitError
from error import RepoExitError
from error import SilentRepoExitError
from git_config import RepoConfig


class Error(RepoExitError):
    """Exit error when the config command fails."""


class NotSetError(SilentRepoExitError):
    """Exit quietly when a requested setting is not set, like `git config`."""


# A conservative subset of the key syntax git accepts: `section.name` or
# `section.subsection.name`, where section and name are alphanumerics and
# dashes and name does not start with a digit.  Any subsection is accepted
# verbatim.  Git validates the key again when the file is written.
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*\.(.+\.)?[A-Za-z][A-Za-z0-9-]*$")


class Config(Command, MirrorSafeCommand):
    """Read and write repo's per-user settings."""

    COMMON = True
    MULTI_MANIFEST_SUPPORT = True
    helpSummary = "Read and write per-user repo settings"
    helpUsage = """
%prog <name>
%prog <name> <value>
%prog --unset <name>
%prog --list
"""
    helpDescription = """
The '%prog' command reads and writes repo's own per-user settings.  These
are separate from git's config and from a checkout's settings; see
docs/repoconfig.md for where they live and which settings repo understands.

Settings are named <section>.<name>, e.g. sync.smartsync.  Reading a
setting that is not set exits 1 without output, like `git config`.
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

    def Execute(self, opt: optparse.Values, args: List[str]) -> None:
        config = RepoConfig.ForUser()

        if opt.list:
            for key in sorted(config.DumpConfigDict()):
                for value in config.GetString(key, all_keys=True):
                    print(key if value is None else f"{key}={value}")
            return

        name = args[0]
        if opt.unset or len(args) == 2:
            value = None if opt.unset else args[1]
            try:
                config.SetString(name, value)
            except GitError as e:
                raise Error(f"error: failed to update {config.file}: {e}")
            return

        values = config.GetString(name, all_keys=True)
        if not values:
            raise NotSetError(exit_code=1)
        for value in values:
            # A key without `=` in the file has no value; git prints a blank.
            print("" if value is None else value)
