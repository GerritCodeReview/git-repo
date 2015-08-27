#
# Copyright (C) 2015 The Android Open Source Project
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

from __future__ import print_function
import os
import sys

from command import Command
import gitc_utils

class Pause(Command):
  common = True
  helpSummary = "Pause local development and return to the GITC FS View."
  helpUsage = """
%prog <branchname> [<project>...]

This subcommand restores a project to view remote sources via the GITC
filesystem. repo pause and repo start allows you switch between local and
remote sources easily.

"""
  def _Options(self, p):
    p.add_option('--all',
                 dest='all', action='store_true',
                 help='Pause local development in all projects.')


  def Execute(self, opt, args):
    projects = []
    if not opt.all:
      projects = args
      if len(projects) < 1:
        print('error: at least one project must be specified', file=sys.stderr)
        sys.exit(1)
    _, gitc_client_dir = gitc_utils.parse_clientdir_info(os.getcwd())
    if not gitc_client_dir:
      print('error: Repo pause can only be used in a GITC checkout.')

    gitc_manifest = os.path.join(gitc_client_dir, '.manifest')
    self.manifest.Override(gitc_manifest)
    all_projects = self.GetProjects(projects, missing_ok=True)

    print('Closed the following projects:')
    for project in all_projects:
      if project.old_revision:
        project.revisionExpr = project.old_revision
        project.old_revision = ''
        print(project.name)
    gitc_utils.save_manifest(gitc_client_dir, self.manifest)
