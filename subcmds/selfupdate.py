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

import optparse

from command import Command
from command import MirrorSafeCommand
from error import RepoExitError
from repo_logging import RepoLogger
from subcmds.sync import _PostRepoFetch
from subcmds.sync import _PostRepoUpgrade


logger = RepoLogger(__file__)


class SelfupdateError(RepoExitError):
    """Exit error for failed selfupdate command."""


class Selfupdate(Command, MirrorSafeCommand):
    COMMON = False
    helpSummary = "Update repo to the latest version"
    helpUsage = """
%prog
"""
    helpDescription = """
The '%prog' command upgrades repo to the latest version, if a
newer version is available.

Normally this is done automatically by 'repo sync' and does not
need to be performed by an end-user.
"""

    def _Options(self, p):
        g = p.add_option_group("repo Version options")
        g.add_option(
            "--no-repo-verify",
            dest="repo_verify",
            default=True,
            action="store_false",
            help="do not verify repo source code",
        )
        g.add_option(
            "--repo-upgraded",
            action="store_true",
            help=optparse.SUPPRESS_HELP,
        )

    def Execute(self, opt, args):
        rp = self.manifest.repoProject
        rp.PreSync()

        if opt.repo_upgraded:
            _PostRepoUpgrade(self.manifest)

        else:
            result = rp.Sync_NetworkHalf()
            if result.error:
                logger.error("error: can't update repo")
                raise SelfupdateError(aggregate_errors=[result.error])

            rp.bare_git.gc("--auto")
            _PostRepoFetch(rp, repo_verify=opt.repo_verify, verbose=True)
