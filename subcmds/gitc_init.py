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

import git_command
from command import InteractiveCommand, MirrorSafeCommand
from subcmds import init


GITC_MANIFEST_DIR = '/usr/local/google/gitc'
GITC_FS_ROOT_DIR = '/gitc/sha/rw'
NUM_BATCH_RETREIVE_REVISIONID = 300


class GitcInit(init.Init):
  common = True
  helpSummary = "Initialize a GITC Client."
  helpUsage = """
%prog [options] [client name]
"""
  helpDescription = """
GITC INIT HELP DESSCRIPTION
"""

  def _Options(self, p):
    super(GitcInit, self)._Options(p)
    g = p.add_option_group('GITC options')
    g.add_option('-f', '--manifest-file',
                 dest='manifest_file', default=None,
                 help='Optional manifest file to use for this GITC client.')
    g.add_option('-c', '--gitc-client',
                 dest='gitc_client', default=None,
                 help='The name for the new gitc_client instance.')

  def SetVariablesFromOptions(self, opt):
    """ Initalizes instance variables based off of the supplied options.

    For GitcInit, this will set the repodir to be be in the local
    GITC manifest directory.
    """
    if not opt.gitc_client:
      print('fatal: gitc client (-c) is required', file=sys.stderr)
      sys.exit(1)
    self.client_dir = os.path.join(GITC_MANIFEST_DIR, opt.gitc_client)
    self.repodir = os.path.join(self.client_dir, '.repo')

  def Execute(self, opt, args):
    if not os.path.exists(GITC_MANIFEST_DIR):
      os.makedirs(GITC_MANIFEST_DIR)
    if not os.path.exists(self.client_dir):
      os.mkdir(self.client_dir)
    print(opt)
    super(GitcInit, self).Execute(opt, args)
    self._GenerateGITCManifest()
    print('Please run `cd %s` to view your GITC client.' %
          os.path.join(GITC_FS_ROOT_DIR, opt.gitc_client))

  def _ProcessProjGitcmdDict(self, project_gitcmd_dict):
    for proj, gitcmd in project_gitcmd_dict.iteritems():
      if gitcmd.Wait():
        print('FATAL: Failed to retrieve revisionID for %s' % project)
        sys.exit(1)
      proj.revisionExpr = gitcmd.stdout.split('\t')[0]

  def _GenerateGITCManifest(self):
    """Generate a manifest for shafsd to use for this GITC client."""
    print('Generating GITC Manifest by fetching HEAD SHAs for each project.')
    manifest = self.manifest
    #print(manifest.manifestUrl)
    #sys.exit(1)
    project_gitcmd_dict = {}
    i = 0
    for project in manifest.projects:
      project_gitcmd_dict[project] = git_command.GitCommand(
          None, ['ls-remote', os.path.join('persistent-https://googleplex-android.git.corp.google.com', project.name),
                 'HEAD'], capture_stdout=True)
      i = i + 1
      if i == NUM_BATCH_RETREIVE_REVISIONID:
        self._ProcessProjGitcmdDict(project_gitcmd_dict)
        i = 0
        project_gitcmd_dict = {}
    # Process the remaining projects.
    self._ProcessProjGitcmdDict(project_gitcmd_dict)
    # Save the manifest.
    with open(os.path.join(self.client_dir, '.manifest'), 'w') as f:
      manifest.Save(f)
