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
  UpdateProjectsResult = superproject.UpdateProjectsRevisionId(projects)
"""

import hashlib
import functools
import os
import sys
import time
from typing import NamedTuple

from git_command import git_require, GitCommand
from git_config import RepoConfig
from git_refs import R_HEADS
from manifest_xml import LOCAL_MANIFEST_GROUP_PREFIX

_SUPERPROJECT_GIT_NAME = 'superproject.git'
_SUPERPROJECT_MANIFEST_NAME = 'superproject_override.xml'


class SyncResult(NamedTuple):
  """Return the status of sync and whether caller should exit."""

  # Whether the superproject sync was successful.
  success: bool
  # Whether the caller should exit.
  fatal: bool


class CommitIdsResult(NamedTuple):
  """Return the commit ids and whether caller should exit."""

  # A dictionary with the projects/commit ids on success, otherwise None.
  commit_ids: dict
  # Whether the caller should exit.
  fatal: bool


class UpdateProjectsResult(NamedTuple):
  """Return the overriding manifest file and whether caller should exit."""

  # Path name of the overriding manfiest file if successful, otherwise None.
  manifest_path: str
  # Whether the caller should exit.
  fatal: bool


class Superproject(object):
  """Get commit ids from superproject.

  Initializes a local copy of a superproject for the manifest. This allows
  lookup of commit ids for all projects. It contains _project_commit_ids which
  is a dictionary with project/commit id entries.
  """
  def __init__(self, manifest, repodir, git_event_log,
               superproject_dir='exp-superproject', quiet=False):
    """Initializes superproject.

    Args:
      manifest: A Manifest object that is to be written to a file.
      repodir: Path to the .repo/ dir for holding all internal checkout state.
          It must be in the top directory of the repo client checkout.
      git_event_log: A git trace2 event log to log events.
      superproject_dir: Relative path under |repodir| to checkout superproject.
      quiet:  If True then only print the progress messages.
    """
    self._project_commit_ids = None
    self._manifest = manifest
    self._git_event_log = git_event_log
    self._quiet = quiet
    self._branch = self._GetBranch()
    self._repodir = os.path.abspath(repodir)
    self._superproject_dir = superproject_dir
    self._superproject_path = os.path.join(self._repodir, superproject_dir)
    self._manifest_path = os.path.join(self._superproject_path,
                                       _SUPERPROJECT_MANIFEST_NAME)
    git_name = ''
    if self._manifest.superproject:
      remote_name = self._manifest.superproject['remote'].name
      git_name = hashlib.md5(remote_name.encode('utf8')).hexdigest() + '-'
    self._work_git_name = git_name + _SUPERPROJECT_GIT_NAME
    self._work_git = os.path.join(self._superproject_path, self._work_git_name)

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

  def _LogError(self, message):
    """Logs message to stderr and _git_event_log."""
    print(message, file=sys.stderr)
    self._git_event_log.ErrorEvent(message, '')

  def _Init(self):
    """Sets up a local Git repository to get a copy of a superproject.

    Returns:
      True if initialization is successful, or False.
    """
    if not os.path.exists(self._superproject_path):
      os.mkdir(self._superproject_path)
    if not self._quiet and not os.path.exists(self._work_git):
      print('%s: Performing initial setup for superproject; this might take '
            'several minutes.' % self._work_git)
    cmd = ['init', '--bare', self._work_git_name]
    p = GitCommand(None,
                   cmd,
                   cwd=self._superproject_path,
                   capture_stdout=True,
                   capture_stderr=True)
    retval = p.Wait()
    if retval:
      self._LogError(f'repo: error: git init call failed, command: git {cmd}, '
                     f'return code: {retval}, stderr: {p.stderr}')
      return False
    return True

  def _Fetch(self, url):
    """Fetches a local copy of a superproject for the manifest based on url.

    Args:
      url: superproject's url.

    Returns:
      True if fetch is successful, or False.
    """
    if not os.path.exists(self._work_git):
      self._LogError(f'git fetch missing directory: {self._work_git}')
      return False
    if not git_require((2, 28, 0)):
      print('superproject requires a git version 2.28 or later', file=sys.stderr)
      return False
    cmd = ['fetch', url, '--depth', '1', '--force', '--no-tags', '--filter', 'blob:none']
    if self._branch:
      cmd += [self._branch + ':' + self._branch]
    p = GitCommand(None,
                   cmd,
                   cwd=self._work_git,
                   capture_stdout=True,
                   capture_stderr=True)
    retval = p.Wait()
    if retval:
      self._LogError(f'repo: error: git fetch call failed, command: git {cmd}, '
                     f'return code: {retval}, stderr: {p.stderr}')
      return False
    return True

  def _LsTree(self):
    """Gets the commit ids for all projects.

    Works only in git repositories.

    Returns:
      data: data returned from 'git ls-tree ...' instead of None.
    """
    if not os.path.exists(self._work_git):
      self._LogError(f'git ls-tree missing directory: {self._work_git}')
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
      self._LogError(f'repo: error: git ls-tree call failed, command: git {cmd}, '
                     f'return code: {retval}, stderr: {p.stderr}')
    return data

  def Sync(self):
    """Gets a local copy of a superproject for the manifest.

    Returns:
      SyncResult
    """
    print('NOTICE: --use-superproject is in beta; report any issues to the '
          'address described in `repo version`', file=sys.stderr)

    if not self._manifest.superproject:
      self._LogError(f'repo error: superproject tag is not defined in manifest: '
                     f'{self._manifest.manifestFile}')
      return SyncResult(False, False)

    should_exit = True
    url = self._manifest.superproject['remote'].url
    if not url:
      self._LogError(f'repo error: superproject URL is not defined in manifest: '
                     f'{self._manifest.manifestFile}')
      return SyncResult(False, should_exit)

    if not self._Init():
      return SyncResult(False, should_exit)
    if not self._Fetch(url):
      return SyncResult(False, should_exit)
    if not self._quiet:
      print('%s: Initial setup for superproject completed.' % self._work_git)
    return SyncResult(True, False)

  def _GetAllProjectsCommitIds(self):
    """Get commit ids for all projects from superproject and save them in _project_commit_ids.

    Returns:
      CommitIdsResult
    """
    sync_result = self.Sync()
    if not sync_result.success:
      return CommitIdsResult(None, sync_result.fatal)

    data = self._LsTree()
    if not data:
      print('warning: git ls-tree failed to return data for superproject',
            file=sys.stderr)
      return CommitIdsResult(None, True)

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
    return CommitIdsResult(commit_ids, False)

  def _WriteManfiestFile(self):
    """Writes manifest to a file.

    Returns:
      manifest_path: Path name of the file into which manifest is written instead of None.
    """
    if not os.path.exists(self._superproject_path):
      self._LogError(f'error: missing superproject directory: {self._superproject_path}')
      return None
    manifest_str = self._manifest.ToXml(groups=self._manifest.GetGroupsStr()).toxml()
    manifest_path = self._manifest_path
    try:
      with open(manifest_path, 'w', encoding='utf-8') as fp:
        fp.write(manifest_str)
    except IOError as e:
      self._LogError(f'error: cannot write manifest to : {manifest_path} {e}')
      return None
    return manifest_path

  def _SkipUpdatingProjectRevisionId(self, project):
    """Checks if a project's revision id needs to be updated or not.

    Revision id for projects from local manifest will not be updated.

    Args:
      project: project whose revision id is being updated.

    Returns:
      True if a project's revision id should not be updated, or False,
    """
    path = project.relpath
    if not path:
      return True
    # Skip the project with revisionId.
    if project.revisionId:
      return True
    # Skip the project if it comes from the local manifest.
    return any(s.startswith(LOCAL_MANIFEST_GROUP_PREFIX) for s in project.groups)

  def UpdateProjectsRevisionId(self, projects):
    """Update revisionId of every project in projects with the commit id.

    Args:
      projects: List of projects whose revisionId needs to be updated.

    Returns:
      UpdateProjectsResult
    """
    commit_ids_result = self._GetAllProjectsCommitIds()
    commit_ids = commit_ids_result.commit_ids
    if not commit_ids:
      print('warning: Cannot get project commit ids from manifest', file=sys.stderr)
      return UpdateProjectsResult(None, commit_ids_result.fatal)

    projects_missing_commit_ids = []
    for project in projects:
      if self._SkipUpdatingProjectRevisionId(project):
        continue
      path = project.relpath
      commit_id = commit_ids.get(path)
      if not commit_id:
        projects_missing_commit_ids.append(path)

    # If superproject doesn't have a commit id for a project, then report an
    # error event and continue as if do not use superproject is specified.
    if projects_missing_commit_ids:
      self._LogError(f'error: please file a bug using {self._manifest.contactinfo.bugurl} '
                     f'to report missing commit_ids for: {projects_missing_commit_ids}')
      return UpdateProjectsResult(None, False)

    for project in projects:
      if not self._SkipUpdatingProjectRevisionId(project):
        project.SetRevisionId(commit_ids.get(project.relpath))

    manifest_path = self._WriteManfiestFile()
    return UpdateProjectsResult(manifest_path, False)


@functools.lru_cache(maxsize=None)
def _UseSuperprojectFromConfiguration():
  """Returns the user choice of whether to use superproject."""
  user_cfg = RepoConfig.ForUser()
  system_cfg = RepoConfig.ForSystem()
  time_now = int(time.time())

  user_value = user_cfg.GetBoolean('repo.superprojectChoice')
  if user_value is not None:
    user_expiration = user_cfg.GetInt('repo.superprojectChoiceExpire')
    if user_expiration is not None and (user_expiration <= 0 or user_expiration >= time_now):
      # TODO(b/190688390) - Remove prompt when we are comfortable with the new
      # default value.
      print(('You are currently enrolled in Git submodules experiment '
             '(go/android-submodules-quickstart).  Use --no-use-superproject '
             'to override.\n'), file=sys.stderr)
    return user_value

  # We don't have an unexpired choice, ask for one.
  system_value = system_cfg.GetBoolean('repo.superprojectChoice')
  if system_value:
    # The system configuration is proposing that we should enable the
    # use of superproject. Present this to user for confirmation if we
    # are on a TTY, or, when we are not on a TTY, accept the system
    # default for this time only.
    #
    # TODO(b/190688390) - Remove prompt when we are comfortable with the new
    # default value.
    prompt = ('Repo can now use Git submodules (go/android-submodules-quickstart) '
              'instead of manifests to represent the state of the Android '
              'superproject, which results in faster syncs and better atomicity.\n\n')
    if sys.stdout.isatty():
      prompt += 'Would you like to opt in for two weeks (y/N)? '
      response = input(prompt).lower()
      time_choiceexpire = time_now + (86400 * 14)
      if response in ('y', 'yes'):
        userchoice = True
      elif response in ('a', 'always'):
        userchoice = True
        time_choiceexpire = 0
      elif response == 'never':
        userchoice = False
        time_choiceexpire = 0
      elif response in ('n', 'no'):
        userchoice = False
      else:
        # Unrecognized user response, assume the intention was no, but
        # only for 2 hours instead of 2 weeks to balance between not
        # being overly pushy while still retain the opportunity to
        # enroll.
        userchoice = False
        time_choiceexpire = time_now + 7200

      user_cfg.SetString('repo.superprojectChoiceExpire', str(time_choiceexpire))
      user_cfg.SetBoolean('repo.superprojectChoice', userchoice)

      return userchoice
    else:
      print('Accepting once since we are not on a TTY', file=sys.stderr)
      return True

  # For all other cases, we would not use superproject by default.
  return False


def UseSuperproject(opt, manifest):
  """Returns a boolean if use-superproject option is enabled."""

  if opt.use_superproject is not None:
    return opt.use_superproject
  else:
    client_value = manifest.manifestProject.config.GetBoolean('repo.superproject')
    if client_value is not None:
      return client_value
    else:
      return _UseSuperprojectFromConfiguration()
