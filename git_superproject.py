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

  git_superproject_shas = SuperprojectSHA().project_shas
"""


import os
import shutil
import sys

from git_command import GitCommand


class SuperprojectSHA(object):
  """Get SHAs from superproject.

  It contains project_shas which is a dictionary with project/sha entries.
  """

  def __init__(self, url=None, branch=None):
    """Initializes all project's SHAs from superproject.

    Args:
      url: superproject's url to be passed to git clone.
      branch: the branchname to be passed as argument to git clone.
    """
    self._project_shas = self._GetSHAsFromSuperproject(url, branch)

  @property
  def project_shas(self):
    return self._project_shas

  def _Cleanup(self, chdir_dirpath, rmtree_dirpath):
    os.chdir(chdir_dirpath)
    shutil.rmtree(rmtree_dirpath)

  def _GetSHAsFromSuperproject(self, url=None, branch=None):
    """Gets SHAs from superproject.

    Args:
      url: superproject's url to be passed to git clone.
      branch: the branchname to be passed as argument to git clone.

    Returns:
      A dictionay with the projects/SHAs, otherwise None
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

    cmd = ['clone', url]
    if branch:
      cmd += ['--branch', branch]
    p = GitCommand(None, cmd, capture_stdout=True, capture_stderr=True,
                   bare=True)
    if p.Wait() != 0:
      print("error: Failed to run git clone")
      print(p.stderr, file=sys.stderr)
      self._Cleanup(save_cwd, superproject_dir)
      return None

    os.chdir(superproject_dirname)
    cmd = ['ls-tree', '-r', 'HEAD']
    p = GitCommand(None, cmd, capture_stdout=True, capture_stderr=True,
                   bare=True)
    retval = p.Wait()
    if retval != 0:
      print("error: Failed to run git ls-tree")
      print(p.stderr, file=sys.stderr)
      self._Cleanup(save_cwd, superproject_dir)
      return None

    r = p.stdout.split('\n')
    shas = {}
    for line in r:
      ls_data = line.split()
      if not ls_data:
        break
      if ls_data[0] != '160000':
        continue
      shas[ls_data[3]] = ls_data[2]

    self._Cleanup(save_cwd, superproject_dir)
    return shas
