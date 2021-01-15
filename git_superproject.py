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

  Usage:

  superproject = Superproject()
  project_shas = superproject.GetAllProjectsSHAs()
"""


import os
import shutil
import sys

from git_command import GitCommand


class Superproject(object):
  """Get SHAs from superproject.

  It contains project_shas which is a dictionary with project/sha entries.
  """

  def __init__(self):
    """Initializes superproject."""
    self._project_shas = None

  @property
  def project_shas(self):
    return self._project_shas

  def _Cleanup(self, chdir_dirpath, rmtree_dirpath):
    os.chdir(chdir_dirpath)
    shutil.rmtree(rmtree_dirpath)

  def _Clone(self, url, branch=None):
    """Do a git clone for the given url and branch.

    Args:
      url: superproject's url to be passed to git clone.
      branch: the branchname to be passed as argument to git clone.

    Returns:
      True if git clone '<url> <branch>' is successful, or False.
    """
    cmd = ['clone', url]
    if branch:
      cmd += ['--branch', branch]
    p = GitCommand(None, cmd, capture_stdout=True, capture_stderr=True,
                   bare=True)
    retval = p.Wait()
    if retval != 0:
      # `git clone` is documented to produce an exit status of `128` if
      # the requested url or branch are not present in the configuration.
      print("repo: error: 'git clone' call failed with return code: %r, stderr: %r" %
            (retval, p.stderr), file=sys.stderr)
      return False
    return True

  def _LsTree(self, superproject_dir):
    """Returns the data from 'git ls-tree -r HEAD'. Works only in git repositories.

    Args:
      superproject_dir: name of the directory where superproject was cloned into.

    Returns:
      data: data returned from ''git ls-tree -r HEAD' if successful, or None.
    """
    data = None
    os.chdir(superproject_dir)
    cmd = ['ls-tree', '-r', 'HEAD']
    p = GitCommand(None, cmd, capture_stdout=True, capture_stderr=True,
                   bare=True)
    retval = p.Wait()
    if retval == 0:
      # Strip trailing carriage-return in path.
      data = p.stdout.rstrip('\n')
    else:
      # `git clone` is documented to produce an exit status of `128` if
      # the requested url or branch are not present in the configuration.
      print("repo: error: 'git ls-tree' call failed with return code: %r, stderr: %r" % (
          retval, p.stderr), file=sys.stderr)
    return data

  def GetAllProjectsSHAs(self, url, branch=None):
    """Get SHAs for all projects from superproject and save them in _project_shas.

    Args:
      url: superproject's url to be passed to git clone.
      branch: the branchname to be passed as argument to git clone.

    Returns:
      A dictionay with the projects/SHAsif successful, otherwise None.
    """

    if not url:
      return None
    save_cwd = os.getcwd()
    superproject_dirname = "superproject"
    superproject_dir = os.path.join(save_cwd, superproject_dirname)
    if os.path.exists(superproject_dir):
      shutil.rmtree(superproject_dir)
    os.mkdir(superproject_dir)
    os.chdir(superproject_dir)

    if not self._Clone(url, branch):
      self._Cleanup(save_cwd, superproject_dir)
      return None

    data = self._LsTree(superproject_dirname)
    if not data:
      self._Cleanup(save_cwd, superproject_dir)
      return None

    r = data.split('\n')
    shas = {}
    for line in r:
      ls_data = line.split()
      if not ls_data:
        break
      if ls_data[0] != '160000':
        continue
      shas[ls_data[3]] = ls_data[2]

    self._Cleanup(save_cwd, superproject_dir)
    self._project_shas = shas
    return shas
