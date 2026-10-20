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
from typing import List, Optional

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

# Spellings `git config --type=bool` accepts, and their canonical form.
_BOOL_VALUES = {
    "true": "true",
    "yes": "true",
    "on": "true",
    "1": "true",
    "false": "false",
    "no": "false",
    "off": "false",
    "0": "false",
}

# Suffixes `git config --type=int` accepts.
_INT_SUFFIXES = {"k": 1024, "m": 1024**2, "g": 1024**3}


def _CanonicalizeBool(name: str, value: str) -> str:
    """Returns |value| as "true"/"false", or raises Error."""
    try:
        return _BOOL_VALUES[value.lower()]
    except KeyError:
        raise Error(f"error: {name}: '{value}' is not a boolean")


def _CanonicalizeInt(name: str, value: str) -> str:
    """Returns |value| as a plain decimal integer, or raises Error."""
    v = value.strip().lower()
    mult = _INT_SUFFIXES.get(v[-1:], 1)
    if mult != 1:
        v = v[:-1]
    try:
        return str(int(v, 0) * mult)
    except ValueError:
        raise Error(f"error: {name}: '{value}' is not an integer")


_TYPES = {
    "bool": _CanonicalizeBool,
    "int": _CanonicalizeInt,
}


class Config(command.Command, command.MirrorSafeCommand):
    """Read and write repo's per-user settings."""

    COMMON = True
    MULTI_MANIFEST_SUPPORT = True
    helpSummary = "Read and write per-user repo settings"
    helpUsage = """
%prog [--type=<type>] [-z] get <name>
%prog [--type=<type>] set <name> <value>
%prog unset <name>
%prog [-z] list
"""
    helpDescription = """
The '%prog' command reads and writes repo's own per-user settings.  These
are separate from git's config and from a checkout's settings; see
docs/repoconfig.md for where they live and which settings repo understands.

Settings are named <section>.<name>, e.g. sync.smartsync.  'get' prints
every value of the setting and exits 1 without output if it is not set,
like `git config`.

Values are stored as strings.  With --type, 'set' validates the value and
stores it in canonical form (e.g. "on" as "true", "1k" as "1024"), and
'get' prints the canonical form, like `git config --type`.
"""

    def _Options(self, p: optparse.OptionParser) -> None:
        p.add_option(
            "--type",
            choices=sorted(_TYPES),
            help="validate and canonicalize the value as this type for "
            "get and set (%s)" % ", ".join(sorted(_TYPES)),
        )
        p.add_option(
            "-z",
            "--null",
            action="store_true",
            help="terminate output of get and list with NUL instead of "
            "newline, and separate key and value with a newline",
        )

    def ValidateOptions(self, opt: optparse.Values, args: List[str]) -> None:
        if not args:
            self.Usage()
        action, rest = args[0], args[1:]
        if action not in _ACTIONS:
            self.OptionParser.error(f"unknown action '{action}'")
        if len(rest) != _ACTIONS[action]:
            self.Usage()
        if opt.type and action not in ("get", "set"):
            self.OptionParser.error("--type only applies to get and set")
        if opt.null and action not in ("get", "list"):
            self.OptionParser.error("-z/--null only applies to get and list")

    def Execute(self, opt: optparse.Values, args: List[str]) -> None:
        config = git_config.RepoConfig.ForUser()
        action, rest = args[0], args[1:]
        dispatch = {
            "get": self._ExecuteGet,
            "set": self._ExecuteSet,
            "unset": self._ExecuteUnset,
            "list": self._ExecuteList,
        }[action]
        dispatch(opt, config, *rest)

    @staticmethod
    def _Print(opt: optparse.Values, text: str) -> None:
        """Prints |text| terminated by NUL with -z, else by newline."""
        print(text, end="\0" if opt.null else "\n")

    @staticmethod
    def _Format(opt: optparse.Values, name: str, value: Optional[str]) -> str:
        """Formats a value for output, canonicalizing it per --type."""
        if value is None:
            # A key without `=` in the file has no value; git prints a blank.
            return ""
        if opt.type:
            return _TYPES[opt.type](name, value)
        return value

    def _ExecuteGet(
        self, opt: optparse.Values, config: git_config.RepoConfig, name: str
    ) -> None:
        values = config.GetString(name, all_keys=True)
        if not values:
            raise NotSetError(exit_code=1)
        for value in values:
            self._Print(opt, self._Format(opt, name, value))

    def _ExecuteSet(
        self,
        opt: optparse.Values,
        config: git_config.RepoConfig,
        name: str,
        value: str,
    ) -> None:
        if opt.type:
            value = _TYPES[opt.type](name, value)
        self._Write(config, name, value)

    def _ExecuteUnset(
        self, opt: optparse.Values, config: git_config.RepoConfig, name: str
    ) -> None:
        self._Write(config, name, None)

    def _ExecuteList(
        self, opt: optparse.Values, config: git_config.RepoConfig
    ) -> None:
        sep = "\n" if opt.null else "="
        for key in sorted(config.DumpConfigDict()):
            for value in config.GetString(key, all_keys=True):
                self._Print(opt, key if value is None else f"{key}{sep}{value}")

    @staticmethod
    def _Write(
        config: git_config.RepoConfig, name: str, value: Optional[str]
    ) -> None:
        """Writes |value| (None to delete) via `git config`, which also
        validates the name."""
        try:
            config.SetString(name, value)
        except error.GitError as e:
            raise Error(str(e))
