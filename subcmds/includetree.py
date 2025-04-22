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

import os

from command import PagedCommand
from repo_logging import RepoLogger


logger = RepoLogger(__file__)


class Includetree(PagedCommand):
    COMMON = False
    helpSummary = (
        "Print the hierarchy of all recursivelly included manifest files"
    )
    helpUsage = """
%prog [-m MANIFEST.xml] [-f]
"""
    _helpDescription = """
With the -a option, display all elements of the manifest, not just includes.

With the -f option, display only elements matching those of the provided filter,
by comparing all attribute values with the filter.

When either of -a or -f are used, the output will display complete xml elements,
otherwise only the include names will be shown. Note that child-elements,
such as <copyfile> and <linkfile> are not displayed in either case.

Submanifests are currently not supported by this command.
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
            "-m",
            "--manifest-name",
            help="temporary manifest to use for this sync",
            metavar="NAME.xml",
        )
        p.add_option(
            "--no-local-manifests",
            default=False,
            action="store_true",
            dest="ignore_local_manifests",
            help="ignore local manifests",
        )
        p.add_option(
            "-f",
            "--filter",
            type="string",
            dest="filter",
            help="display only elements matching the filter",
        )
        p.add_option(
            "-a",
            "--full",
            default=False,
            action="store_true",
            dest="full",
            help="display all elements of the manifest, not just includes",
        )

    def _Output(self, opt):
        # If alternate manifest is specified, override the manifest file that
        # we're using.
        if opt.manifest_name:
            self.manifest.Override(opt.manifest_name, False)

        for manifest in self.ManifestList(opt):
            print(manifest.FormatIncludeTree(full=opt.full, filter=opt.filter))

    def ValidateOptions(self, opt, args):
        if args:
            self.Usage()

    def Execute(self, opt, args):
        self._Output(opt)
