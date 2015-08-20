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

from __future__ import print_function
import os
import sys

from command import Command
from git_config import IsId
from git_command import git
import gitc_utils
from progress import Progress
from project import SyncBuffer

class Start(Command):
  common = True
  helpSummary = "Start a new branch for development"
  helpUsage = """
%prog <newbranchname> [--all | <project>...]
"""
  helpDescription = """
'%prog' begins a new branch of development, starting from the
revision specified in the manifest.
"""

  def _Options(self, p):
    p.add_option('--all',
                 dest='all', action='store_true',
                 help='begin branch in all projects')

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    if not git.check_ref_format('heads/%s' % nb):
      print("error: '%s' is not a valid name" % nb, file=sys.stderr)
      sys.exit(1)

    err = []
    projects = []
    if not opt.all:
      projects = args[1:]
      if len(projects) < 1:
        print("error: at least one project must be specified", file=sys.stderr)
        sys.exit(1)

    _, gitc_client_dir = gitc_utils.parse_clientdir_info(os.getcwd())
    if gitc_client_dir:
      gitc_manifest = os.path.join(gitc_client_dir, '.manifest')
      original_manifest = self.manifest.manifestFile
      self.manifest.Override(gitc_manifest)
      all_projects = self.GetProjects(projects, missing_ok=True)

      for project in all_projects:
        if not IsId(project.revisionExpr):
          continue
        proj_localdir = os.path.join(gitc_client_dir, project.relpath)
        project.worktree = proj_localdir
        if not os.path.exists(proj_localdir):
          os.makedirs(proj_localdir)
        project.Sync_NetworkHalf(current_branch_only=True)
        sync_buf = SyncBuffer(self.manifest.manifestProject.config)
        project.Sync_LocalHalf(sync_buf)
        project.revisionExpr = None
      # Save the GITC manifest.
      gitc_utils.save_manifest(gitc_client_dir, self.manifest)
      self.manifest.Override(original_manifest)

    all_projects = self.GetProjects(projects)

    pm = Progress('Starting %s' % nb, len(all_projects))
    for project in all_projects:
      pm.update()
      # If the current revision is a specific SHA1 then we can't push back
      # to it; so substitute with dest_branch if defined, or with manifest
      # default revision instead.
      if IsId(project.revisionExpr):
        if project.dest_branch:
          project.revisionExpr = project.dest_branch
        else:
          project.revisionExpr = self.manifest.default.revisionExpr
      if not project.StartBranch(nb):
        err.append(project)
    pm.end()

    if err:
      for p in err:
        print("error: %s/: cannot start %s" % (p.relpath, nb),
              file=sys.stderr)
      sys.exit(1)
