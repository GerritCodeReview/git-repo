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
import time

import git_command
import git_config


# TODO (sbasi) - Remove this constant and fetch manifest dir from /gitc/.config
GITC_MANIFEST_DIR = '/usr/local/google/gitc/'
GITC_FS_ROOT_DIR = '/gitc/manifest-rw/'
NUM_BATCH_RETRIEVE_REVISIONID = 300

def parse_clientdir_info(gitc_fs_path):
  """Parse a path in the GITC FS and return its client name and directory.

  @param gitc_fs_path: A subdirectory path within the GITC_FS_ROOT_DIR.

  @returns: A tuple of format (client_name, client_dir) specifying the client's
            name and the path to its GITC manifest directory.
  """
  if (gitc_fs_path == GITC_FS_ROOT_DIR or
      not gitc_fs_path.startswith(GITC_FS_ROOT_DIR)):
    return None, None
  client_name = gitc_fs_path.split(GITC_FS_ROOT_DIR)[1].split('/')[0]
  client_dir = os.path.join(GITC_MANIFEST_DIR, client_name)
  return client_name, client_dir

def _set_project_revisions(projects):
  """Sets the revisionExpr for a list of projects.

  Because of the limit of open file descriptors allowed, length of projects
  should not be overly large. Recommend calling this function multiple times
  with each call not exceeding NUM_BATCH_RETRIEVE_REVISIONID projects.

  @param projects: List of project objects to set the revionExpr for.
  """
  # Retrieve the commit id for each project based off of it's current
  # revisionExpr and it is not already a commit id.
  project_gitcmds = [(
      project, git_command.GitCommand(None,
                                      ['ls-remote',
                                       project.remote.url,
                                       project.revisionExpr],
                                      capture_stdout=True, cwd='/tmp'))
      for project in projects if not git_config.IsId(project.revisionExpr)]
  for proj, gitcmd in project_gitcmds:
    if gitcmd.Wait():
      print('FATAL: Failed to retrieve revisionExpr for %s' % project)
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
        manifest.projects[index:(index+NUM_BATCH_RETRIEVE_REVISIONID)])
    index += NUM_BATCH_RETRIEVE_REVISIONID
  # Save the manifest.
  save_manifest(client_dir, manifest)

def save_manifest(client_dir, manifest):
  """Save the manifest file in the client_dir.

  @param client_dir: Client directory to save the manifest in.
  @param manifest: Manifest object to save.
  """
  with open(os.path.join(client_dir, '.manifest'), 'w') as f:
    manifest.Save(f)
  # TODO(sbasi/jorg): Come up with a solution to remove the sleep below.
  # Give the GITC filesystem time to register the manifest changes.
  time.sleep(3)