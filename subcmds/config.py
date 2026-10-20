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
from typing import List

import command
import error
import git_config


class Error(error.RepoExitError):
    """Exit error when the config command fails."""


class NotSetError(error.SilentRepoExitError):
    """Exit quietly when a requested setting is not set, like `git config`."""


# Subcommand name -> number of positional arguments it takes.
_ACTIONS = {
    "get": 1,
    "set": 2,
    "unset": 1,
    "list": 0,
}


class Config(command.Command, command.MirrorSafeCommand):
    """Read and write repo's per-user settings."""

    COMMON = True
    MULTI_MANIFEST_SUPPORT = True
    helpSummary = "Read and write per-user repo settings"
    helpUsage = """
%prog get <name>
%prog set <name> <value>
%prog unset <name>
%prog list
"""
    helpDescription = """
The '%prog' command reads and writes repo's own per-user settings.  These
are separate from git's config and from a checkout's settings; see
docs/repoconfig.md for where they live and which settings repo understands.

Settings are named <section>.<name>, e.g. sync.smartsync.  'get' prints
every value of the setting and exits 1 without output if it is not set,
like `git config`.
"""

    def ValidateOptions(self, opt: optparse.Values, args: List[str]) -> None:
        if not args:
            self.Usage()
        action, rest = args[0], args[1:]
        if action not in _ACTIONS:
            self.OptionParser.error(f"unknown action '{action}'")
        if len(rest) != _ACTIONS[action]:
            self.Usage()

    def Execute(self, opt: optparse.Values, args: List[str]) -> None:
        config = git_config.RepoConfig.ForUser()
        action, rest = args[0], args[1:]

        if action == "list":
            for key in sorted(config.DumpConfigDict()):
                for value in config.GetString(key, all_keys=True):
                    print(key if value is None else f"{key}={value}")
            return

        name = rest[0]
        if action == "get":
            values = config.GetString(name, all_keys=True)
            if not values:
                raise NotSetError(exit_code=1)
            for value in values:
                # A key without `=` in the file has no value; git prints a
                # blank line.
                print("" if value is None else value)
            return

        # Writes go through `git config`, which also validates the name.
        value = rest[1] if action == "set" else None
        try:
            config.SetString(name, value)
        except error.GitError as e:
            raise Error(str(e))
