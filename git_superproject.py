# Copyright (C) 2021 The Android Open Source Project
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

"""Provide functionality to get all projects and their commit ids from Superproject.

For more information on superproject, check out:
https://en.wikibooks.org/wiki/Git/Submodules_and_Superprojects

Examples:
  superproject = Superproject()
  project_commit_ids = superproject.UpdateProjectsRevisionId(projects)
"""

import os
import sys

from error import BUG_REPORT_URL
from git_command import GitCommand
from git_refs import R_HEADS
import platform_utils

_SUPERPROJECT_GIT_NAME = 'superproject.git'
_SUPERPROJECT_MANIFEST_NAME = 'superproject_override.xml'


class Superproject(object):
  """Get commit ids from superproject.

  It does a 'git clone' of superproject and 'git ls-tree' to get list of commit ids
  for all projects. It contains project_commit_ids which is a dictionary with
  project/commit id entries.
  """
  def __init__(self, manifest, repodir, superproject_dir='exp-superproject'):
    """Initializes superproject.

    Args:
      manifest: A Manifest object that is to be written to a file.
      repodir: Path to the .repo/ dir for holding all internal checkout state.
          It must be in the top directory of the repo client checkout.
      superproject_dir: Relative path under |repodir| to checkout superproject.
    """
    self._project_commit_ids = None
    self._manifest = manifest
    self._branch = self._GetBranch()
    self._repodir = os.path.abspath(repodir)
    self._superproject_dir = superproject_dir
    self._superproject_path = os.path.join(self._repodir, superproject_dir)
    self._manifest_path = os.path.join(self._superproject_path,
                                       _SUPERPROJECT_MANIFEST_NAME)
    self._work_git = os.path.join(self._superproject_path,
                                  _SUPERPROJECT_GIT_NAME)

  @property
  def project_commit_ids(self):
    """Returns a dictionary of projects and their commit ids."""
    return self._project_commit_ids

  def _GetBranch(self):
    """Returns the branch name for getting the approved manifest."""
    p = self._manifest.manifestProject
    b = p.GetBranch(p.CurrentBranch)
    if not b:
      return None
    branch = b.merge
    if branch and branch.startswith(R_HEADS):
      branch = branch[len(R_HEADS):]
    return branch

  def _Clone(self, url):
    """Do a 'git clone' for the given url.

    Args:
      url: superproject's url to be passed to git clone.

    Returns:
      True if git clone is successful, or False.
    """
    if not os.path.exists(self._superproject_path):
      os.mkdir(self._superproject_path)
    cmd = ['clone', url, '--filter', 'blob:none', '--bare']
    if self._branch:
      cmd += ['--branch', self._branch]
    p = GitCommand(None,
                   cmd,
                   cwd=self._superproject_path,
                   capture_stdout=True,
                   capture_stderr=True)
    retval = p.Wait()
    if retval:
      # `git clone` is documented to produce an exit status of `128` if
      # the requested url or branch are not present in the configuration.
      print('repo: error: git clone call failed with return code: %r, stderr: %r' %
            (retval, p.stderr), file=sys.stderr)
      return False
    return True

  def _Fetch(self):
    """Do a 'git fetch' to to fetch the latest content.

    Returns:
      True if 'git fetch' is successful, or False.
    """
    if not os.path.exists(self._work_git):
      print('git fetch missing drectory: %s' % self._work_git,
            file=sys.stderr)
      return False
    cmd = ['fetch', 'origin', '+refs/heads/*:refs/heads/*', '--prune']
    p = GitCommand(None,
                   cmd,
                   cwd=self._work_git,
                   capture_stdout=True,
                   capture_stderr=True)
    retval = p.Wait()
    if retval:
      print('repo: error: git fetch call failed with return code: %r, stderr: %r' %
            (retval, p.stderr), file=sys.stderr)
      return False
    return True

  def _LsTree(self):
    """Returns the data from 'git ls-tree ...'.

    Works only in git repositories.

    Returns:
      data: data returned from 'git ls-tree ...' instead of None.
    """
    if not os.path.exists(self._work_git):
      print('git ls-tree missing drectory: %s' % self._work_git,
            file=sys.stderr)
      return None
    data = None
    branch = 'HEAD' if not self._branch else self._branch
    cmd = ['ls-tree', '-z', '-r', branch]

    p = GitCommand(None,
                   cmd,
                   cwd=self._work_git,
                   capture_stdout=True,
                   capture_stderr=True)
    retval = p.Wait()
    if retval == 0:
      data = p.stdout
    else:
      # `git clone` is documented to produce an exit status of `128` if
      # the requested url or branch are not present in the configuration.
      print('repo: error: git ls-tree call failed with return code: %r, stderr: %r' % (
          retval, p.stderr), file=sys.stderr)
    return data

  def Sync(self):
    """Sync superproject either by git clone/fetch.

    Returns:
      True if sync of superproject is successful, or False.
    """
    print('WARNING: --use-superproject is experimental and not '
          'for general use', file=sys.stderr)

    if not self._manifest.superproject:
      print('error: superproject tag is not defined in manifest',
            file=sys.stderr)
      return False

    url = self._manifest.superproject['remote'].url
    if not url:
      print('error: superproject URL is not defined in manifest',
            file=sys.stderr)
      return False

    do_clone = True
    if os.path.exists(self._superproject_path):
      if not self._Fetch():
        # If fetch fails due to a corrupted git directory, then do a git clone.
        platform_utils.rmtree(self._superproject_path)
      else:
        do_clone = False
    if do_clone:
      if not self._Clone(url):
        print('error: git clone failed for url: %s' % url, file=sys.stderr)
        return False
    return True

  def _GetAllProjectsCommitIds(self):
    """Get commit ids for all projects from superproject and save them in _project_commit_ids.

    Returns:
      A dictionary with the projects/commit ids on success, otherwise None.
    """
    if not self.Sync():
      return None

    data = self._LsTree()
    if not data:
      print('error: git ls-tree failed for superproject', file=sys.stderr)
      return None

    # Parse lines like the following to select lines starting with '160000' and
    # build a dictionary with project path (last element) and its commit id (3rd element).
    #
    # 160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00
    # 120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00
    commit_ids = {}
    for line in data.split('\x00'):
      ls_data = line.split(None, 3)
      if not ls_data:
        break
      if ls_data[0] == '160000':
        commit_ids[ls_data[3]] = ls_data[2]

    self._project_commit_ids = commit_ids
    return commit_ids

  def _WriteManfiestFile(self):
    """Writes manifest to a file.

    Returns:
      manifest_path: Path name of the file into which manifest is written instead of None.
    """
    if not os.path.exists(self._superproject_path):
      print('error: missing superproject directory %s' %
            self._superproject_path,
            file=sys.stderr)
      return None
    manifest_str = self._manifest.ToXml().toxml()
    manifest_path = self._manifest_path
    try:
      with open(manifest_path, 'w', encoding='utf-8') as fp:
        fp.write(manifest_str)
    except IOError as e:
      print('error: cannot write manifest to %s:\n%s'
            % (manifest_path, e),
            file=sys.stderr)
      return None
    return manifest_path

  def UpdateProjectsRevisionId(self, projects):
    """Update revisionId of every project in projects with the commit id.

    Args:
      projects: List of projects whose revisionId needs to be updated.

    Returns:
      manifest_path: Path name of the overriding manfiest file instead of None.
    """
    commit_ids = self._GetAllProjectsCommitIds()
    if not commit_ids:
      print('error: Cannot get project commit ids from manifest', file=sys.stderr)
      return None

    projects_missing_commit_ids = []
    for project in projects:
      path = project.relpath
      if not path:
        continue
      commit_id = commit_ids.get(path)
      if commit_id:
        project.SetRevisionId(commit_id)
      else:
        projects_missing_commit_ids.append(path)
    if projects_missing_commit_ids:
      print('error: please file a bug using %s to report missing commit_ids for: %s' %
            (BUG_REPORT_URL, projects_missing_commit_ids), file=sys.stderr)
      return None

    manifest_path = self._WriteManfiestFile()
    return manifest_path
