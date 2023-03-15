# Copyright (C) 2008 The Android Open Source Project
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

import re
import sys
import textwrap

from subcmds import all_commands
from color import Coloring
from command import (
    PagedCommand,
    MirrorSafeCommand,
    GitcAvailableCommand,
    GitcClientCommand,
)
import gitc_utils
from wrapper import Wrapper


class Help(PagedCommand, MirrorSafeCommand):
    COMMON = False
    helpSummary = "Display detailed help on a command"
    helpUsage = """
%prog [--all|command]
"""
    helpDescription = """
Displays detailed usage information about a command.
"""

    def _PrintCommands(self, commandNames):
        """Helper to display |commandNames| summaries."""
        maxlen = 0
        for name in commandNames:
            maxlen = max(maxlen, len(name))
        fmt = "  %%-%ds  %%s" % maxlen

        for name in commandNames:
            command = all_commands[name]()
            try:
                summary = command.helpSummary.strip()
            except AttributeError:
                summary = ""
            print(fmt % (name, summary))

    def _PrintAllCommands(self):
        print("usage: repo COMMAND [ARGS]")
        self.PrintAllCommandsBody()

    def PrintAllCommandsBody(self):
        print("The complete list of recognized repo commands is:")
        commandNames = list(sorted(all_commands))
        self._PrintCommands(commandNames)
        print(
            "See 'repo help <command>' for more information on a "
            "specific command."
        )
        print("Bug reports:", Wrapper().BUG_URL)

    def _PrintCommonCommands(self):
        print("usage: repo COMMAND [ARGS]")
        self.PrintCommonCommandsBody()

    def PrintCommonCommandsBody(self):
        print("The most commonly used repo commands are:")

        def gitc_supported(cmd):
            if not isinstance(cmd, GitcAvailableCommand) and not isinstance(
                cmd, GitcClientCommand
            ):
                return True
            if self.client.isGitcClient:
                return True
            if isinstance(cmd, GitcClientCommand):
                return False
            if gitc_utils.get_gitc_manifest_dir():
                return True
            return False

        commandNames = list(
            sorted(
                [
                    name
                    for name, command in all_commands.items()
                    if command.COMMON and gitc_supported(command)
                ]
            )
        )
        self._PrintCommands(commandNames)

        print(
            "See 'repo help <command>' for more information on a specific "
            "command.\nSee 'repo help --all' for a complete list of recognized "
            "commands."
        )
        print("Bug reports:", Wrapper().BUG_URL)

    def _PrintCommandHelp(self, cmd, header_prefix=""):
        class _Out(Coloring):
            def __init__(self, gc):
                Coloring.__init__(self, gc, "help")
                self.heading = self.printer("heading", attr="bold")
                self._first = True

            def _PrintSection(self, heading, bodyAttr):
                try:
                    body = getattr(cmd, bodyAttr)
                except AttributeError:
                    return
                if body == "" or body is None:
                    return

                if not self._first:
                    self.nl()
                self._first = False

                self.heading("%s%s", header_prefix, heading)
                self.nl()
                self.nl()

                me = "repo %s" % cmd.NAME
                body = body.strip()
                body = body.replace("%prog", me)

                # Extract the title, but skip any trailing {#anchors}.
                asciidoc_hdr = re.compile(r"^\n?#+ ([^{]+)(\{#.+\})?$")
                for para in body.split("\n\n"):
                    if para.startswith(" "):
                        self.write("%s", para)
                        self.nl()
                        self.nl()
                        continue

                    m = asciidoc_hdr.match(para)
                    if m:
                        self.heading("%s%s", header_prefix, m.group(1))
                        self.nl()
                        self.nl()
                        continue

                    lines = textwrap.wrap(
                        para.replace("  ", " "),
                        width=80,
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                    for line in lines:
                        self.write("%s", line)
                        self.nl()
                    self.nl()

        out = _Out(self.client.globalConfig)
        out._PrintSection("Summary", "helpSummary")
        cmd.OptionParser.print_help()
        out._PrintSection("Description", "helpDescription")

    def _PrintAllCommandHelp(self):
        for name in sorted(all_commands):
            cmd = all_commands[name](manifest=self.manifest)
            self._PrintCommandHelp(cmd, header_prefix="[%s] " % (name,))

    def _Options(self, p):
        p.add_option(
            "-a",
            "--all",
            dest="show_all",
            action="store_true",
            help="show the complete list of commands",
        )
        p.add_option(
            "--help-all",
            dest="show_all_help",
            action="store_true",
            help="show the --help of all commands",
        )

    def Execute(self, opt, args):
        if len(args) == 0:
            if opt.show_all_help:
                self._PrintAllCommandHelp()
            elif opt.show_all:
                self._PrintAllCommands()
            else:
                self._PrintCommonCommands()

        elif len(args) == 1:
            name = args[0]

            try:
                cmd = all_commands[name](manifest=self.manifest)
            except KeyError:
                print(
                    "repo: '%s' is not a repo command." % name, file=sys.stderr
                )
                sys.exit(1)

            self._PrintCommandHelp(cmd)

        else:
            self._PrintCommandHelp(self)
