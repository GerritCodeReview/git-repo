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

"""Provide functionality to get all projects and their SHAs from Superproject.

For more information on superproject, check out:
https://en.wikibooks.org/wiki/Git/Submodules_and_Superprojects

Examples:
  superproject = Superproject()
  project_shas = superproject.GetAllProjectsSHAs()
"""

import os
import sys

from error import GitError
from git_command import GitCommand
import platform_utils


class Superproject(object):
  """Get SHAs from superproject.

  It does a 'git clone' of superproject and 'git ls-tree' to get list of SHAs for all projects.
  It contains project_shas which is a dictionary with project/sha entries.
  """
  def __init__(self, repodir, superproject_dir='exp-superproject'):
    """Initializes superproject.

    Args:
      repodir: Path to the .repo/ dir for holding all internal checkout state.
      superproject_dir: Relative path under |repodir| to checkout superproject.
    """
    self._project_shas = None
    self._repodir = os.path.abspath(repodir)
    self._superproject_dir = superproject_dir
    self._superproject_path = os.path.join(self._repodir, superproject_dir)

  @property
  def project_shas(self):
    """Returns a dictionary of projects and their SHAs."""
    return self._project_shas

  def _Clone(self, url, branch=None):
    """Do a 'git clone' for the given url and branch.

    Args:
      url: superproject's url to be passed to git clone.
      branch: the branchname to be passed as argument to git clone.

    Returns:
      True if 'git clone <url> <branch>' is successful, or False.
    """
    cmd = ['clone', url, '--depth', '1']
    if branch:
      cmd += ['--branch', branch]
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

  def _LsTree(self):
    """Returns the data from 'git ls-tree -r HEAD'.

    Works only in git repositories.

    Returns:
      data: data returned from 'git ls-tree -r HEAD' instead of None.
    """
    git_dir = os.path.join(self._superproject_path, 'superproject')
    if not os.path.exists(git_dir):
      raise GitError('git ls-tree. Missing drectory: %s' % git_dir)
    data = None
    cmd = ['ls-tree', '-z', '-r', 'HEAD']
    p = GitCommand(None,
                   cmd,
                   cwd=git_dir,
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

  def GetAllProjectsSHAs(self, url, branch=None):
    """Get SHAs for all projects from superproject and save them in _project_shas.

    Args:
      url: superproject's url to be passed to git clone.
      branch: the branchname to be passed as argument to git clone.

    Returns:
      A dictionary with the projects/SHAs instead of None.
    """
    if not url:
      raise ValueError('url argument is not supplied.')
    if os.path.exists(self._superproject_path):
      platform_utils.rmtree(self._superproject_path)
    os.mkdir(self._superproject_path)

    # TODO(rtenneti): we shouldn't be cloning the repo from scratch every time.
    if not self._Clone(url, branch):
      raise GitError('git clone failed for url: %s' % url)

    data = self._LsTree()
    if not data:
      raise GitError('git ls-tree failed for url: %s' % url)

    # Parse lines like the following to select lines starting with '160000' and
    # build a dictionary with project path (last element) and its SHA (3rd element).
    #
    # 160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00
    # 120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00
    shas = {}
    for line in data.split('\x00'):
      ls_data = line.split(None, 3)
      if not ls_data:
        break
      if ls_data[0] == '160000':
        shas[ls_data[3]] = ls_data[2]

    self._project_shas = shas
    return shas
