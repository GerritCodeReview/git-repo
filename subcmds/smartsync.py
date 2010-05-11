#
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

from optparse import SUPPRESS_HELP
from sync import Sync

class Smartsync(Sync):
  common = True
  helpSummary = "Update working tree to the latest known good revision"
  helpUsage = """
%prog [<project>...]
"""
  helpDescription = """
The '%prog' command is a shortcut for sync -s.
"""

  def _Options(self, p):
    p.add_option('-l','--local-only',
                 dest='local_only', action='store_true',
                 help="only update working tree, don't fetch")
    p.add_option('-n','--network-only',
                 dest='network_only', action='store_true',
                 help="fetch only, don't update working tree")
    p.add_option('-d','--detach',
                 dest='detach_head', action='store_true',
                 help='detach projects back to manifest revision')

    g = p.add_option_group('repo Version options')
    g.add_option('--no-repo-verify',
                 dest='no_repo_verify', action='store_true',
                 help='do not verify repo source code')
    g.add_option('--repo-upgraded',
                 dest='repo_upgraded', action='store_true',
                 help=SUPPRESS_HELP)

  def Execute(self, opt, args):
    opt.smart_sync = True
    Sync.Execute(self, opt, args)
