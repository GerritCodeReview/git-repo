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

import enum
import json
import optparse
import os
import sys

from command import PagedCommand
from repo_logging import RepoLogger


logger = RepoLogger(__file__)


class OutputFormat(enum.Enum):
    """Type for the requested output format."""

    # Canonicalized manifest in XML format.
    XML = enum.auto()

    # Canonicalized manifest in JSON format.
    JSON = enum.auto()


class Manifest(PagedCommand):
    COMMON = False
    helpSummary = "Manifest inspection utility"
    helpUsage = """
%prog [-o {-|NAME.xml}] [-m MANIFEST.xml] [-r]
"""
    _helpDescription = """

With the -o option, exports the current manifest for inspection.
The manifest and (if present) local_manifests/ are combined
together to produce a single manifest file.  This file can be stored
in a Git repository for use during future 'repo init' invocations.

The -r option can be used to generate a manifest file with project
revisions set to the current commit hash.  These are known as
"revision locked manifests", as they don't follow a particular branch.
In this case, the 'upstream' attribute is set to the ref we were on
when the manifest was generated.  The 'dest-branch' attribute is set
to indicate the remote ref to push changes to via 'repo upload'.

Multiple output formats are supported via --format.  The default output
is XML, and formats are generally "condensed".  Use --pretty for more
human-readable variations.
"""

    @property
    def helpDescription(self):
        helptext = self._helpDescription + "\n"
        r = os.path.dirname(__file__)
        r = os.path.dirname(r)
        with open(os.path.join(r, "docs", "manifest-format.md")) as fd:
            for line in fd:
                helptext += line
        return helptext

    def _Options(self, p):
        p.add_option(
            "-r",
            "--revision-as-HEAD",
            dest="peg_rev",
            action="store_true",
            help="save revisions as current HEAD",
        )
        p.add_option(
            "-m",
            "--manifest-name",
            help="temporary manifest to use for this sync",
            metavar="NAME.xml",
        )
        p.add_option(
            "--suppress-upstream-revision",
            dest="peg_rev_upstream",
            default=True,
            action="store_false",
            help="if in -r mode, do not write the upstream field "
            "(only of use if the branch names for a sha1 manifest are "
            "sensitive)",
        )
        p.add_option(
            "--suppress-dest-branch",
            dest="peg_rev_dest_branch",
            default=True,
            action="store_false",
            help="if in -r mode, do not write the dest-branch field "
            "(only of use if the branch names for a sha1 manifest are "
            "sensitive)",
        )
        # Replaced with --format=json.  Kept for backwards compatibility.
        # Can delete in Jun 2026 or later.
        p.add_option(
            "--json",
            action="store_const",
            dest="format",
            const=OutputFormat.JSON.name.lower(),
            help=optparse.SUPPRESS_HELP,
        )
        formats = tuple(x.lower() for x in OutputFormat.__members__.keys())
        p.add_option(
            "--format",
            default=OutputFormat.XML.name.lower(),
            choices=formats,
            help=f"output format: {', '.join(formats)} (default: %default)",
        )
        p.add_option(
            "--pretty",
            default=False,
            action="store_true",
            help="format output for humans to read",
        )
        p.add_option(
            "--no-local-manifests",
            default=False,
            action="store_true",
            dest="ignore_local_manifests",
            help="ignore local manifests",
        )
        p.add_option(
            "-o",
            "--output-file",
            default="-",
            help="file to save the manifest to. (Filename prefix for "
            "multi-tree.)",
            metavar="-|NAME.xml",
        )

    def _Output(self, opt):
        # If alternate manifest is specified, override the manifest file that
        # we're using.
        if opt.manifest_name:
            self.manifest.Override(opt.manifest_name, False)

        output_format = OutputFormat[opt.format.upper()]

        for manifest in self.ManifestList(opt):
            output_file = opt.output_file
            if output_file == "-":
                fd = sys.stdout
            else:
                if manifest.path_prefix:
                    output_file = (
                        f"{opt.output_file}:"
                        f'{manifest.path_prefix.replace("/", "%2f")}'
                    )
                fd = open(output_file, "w")

            manifest.SetUseLocalManifests(not opt.ignore_local_manifests)

            if output_format == OutputFormat.JSON:
                doc = manifest.ToDict(
                    peg_rev=opt.peg_rev,
                    peg_rev_upstream=opt.peg_rev_upstream,
                    peg_rev_dest_branch=opt.peg_rev_dest_branch,
                )

                json_settings = {
                    # JSON style guide says Unicode characters are fully
                    # allowed.
                    "ensure_ascii": False,
                    # We use 2 space indent to match JSON style guide.
                    "indent": 2 if opt.pretty else None,
                    "separators": (",", ": ") if opt.pretty else (",", ":"),
                    "sort_keys": True,
                }
                fd.write(json.dumps(doc, **json_settings) + "\n")
            else:
                manifest.Save(
                    fd,
                    peg_rev=opt.peg_rev,
                    peg_rev_upstream=opt.peg_rev_upstream,
                    peg_rev_dest_branch=opt.peg_rev_dest_branch,
                )
            if output_file != "-":
                fd.close()
                if manifest.path_prefix:
                    logger.warning(
                        "Saved %s submanifest to %s",
                        manifest.path_prefix,
                        output_file,
                    )
                else:
                    logger.warning("Saved manifest to %s", output_file)

    def ValidateOptions(self, opt, args):
        if args:
            self.Usage()

    def Execute(self, opt, args):
        self._Output(opt)
