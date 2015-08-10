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
import shutil

import git_command


GITC_MANIFEST_DIR = '/usr/local/google/gitc/'
GITC_FS_ROOT_DIR = '/gitc/sha/rw/'
NUM_BATCH_RETRIEVE_REVISIONID = 300

def _set_project_revisions(projects, branch):
  """Sets the revisionExpr for a list of projects.

  Because of the limit of open file descriptors allowed, length of projects
  should not be overly large. Recommend calling this function multiple times
  with each call not exceeding NUM_BATCH_RETRIEVE_REVISIONID projects.

  @param projects: List of project objects to set the revionExpr for.
  @param branch: The remote branch to retrieve the SHA from. If branch is
               None, 'HEAD' is used.
  """
  project_gitcmds = [(
      project, git_command.GitCommand(None,
                                      ['ls-remote',
                                       project.remote.url,
                                       branch], capture_stdout=True))
      for project in projects]
  for proj, gitcmd in project_gitcmds:
    if gitcmd.Wait():
      print('FATAL: Failed to retrieve revisionID for %s' % project)
      sys.exit(1)
    proj.revisionExpr = gitcmd.stdout.split('\t')[0]

def generate_gitc_manifest(client_dir, manifest):
  """Generate a manifest for shafsd to use for this GITC client.

  @param client_dir: GITC client directory to install the .manifest file in.
  @param manifest: XmlManifest object representing the repo manifest.
  """
  print('Generating GITC Manifest by fetching revision SHAs for each '
        'project.')
  project_gitcmd_dict = {}
  index = 0
  while index < len(manifest.projects):
    _set_project_revisions(
        manifest.projects[index:(index+NUM_BATCH_RETRIEVE_REVISIONID)],
        manifest.default.revisionExpr)
    index += NUM_BATCH_RETRIEVE_REVISIONID
  # Save the manifest.
  with open(os.path.join(client_dir, '.manifest'), 'w') as f:
    manifest.Save(f)
  sync_manifests(client_dir)

def sync_manifests(client_dir):
  """Sync the GITC client manifest with repo's manifest.

  Copies over the GITC client manifest and installs it as repo's.

  # TODO (sbasi): Remove the need for this function and just use symlinks
                  instead. Currently using symlink causes GITC to crash,
                  therefore this needs to be fixed in the FS first.

  @param client_dir: GITC client directory to sync manifests in.
  """
  shutil.copyfile(os.path.join(client_dir, '.manifest'),
                  os.path.join(client_dir, '.repo', 'manifest.xml'))
