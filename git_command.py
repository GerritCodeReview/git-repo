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

import functools
import os
import sys
import subprocess
from typing import Any, Optional

from error import GitError
from git_refs import HEAD
import platform_utils
from repo_trace import REPO_TRACE, IsTrace, Trace
from wrapper import Wrapper

GIT = 'git'
# NB: These do not need to be kept in sync with the repo launcher script.
# These may be much newer as it allows the repo launcher to roll between
# different repo releases while source versions might require a newer git.
#
# The soft version is when we start warning users that the version is old and
# we'll be dropping support for it.  We'll refuse to work with versions older
# than the hard version.
#
# git-1.7 is in (EOL) Ubuntu Precise.  git-1.9 is in Ubuntu Trusty.
MIN_GIT_VERSION_SOFT = (1, 9, 1)
MIN_GIT_VERSION_HARD = (1, 7, 2)
GIT_DIR = 'GIT_DIR'

LAST_GITDIR = None
LAST_CWD = None


class _GitCall(object):
  @functools.lru_cache(maxsize=None)
  def version_tuple(self):
    ret = Wrapper().ParseGitVersion()
    if ret is None:
      print('fatal: unable to detect git version', file=sys.stderr)
      sys.exit(1)
    return ret

  def __getattr__(self, name):
    name = name.replace('_', '-')

    def fun(*cmdv):
      command = [name]
      command.extend(cmdv)
      return GitCommand(None, command).Wait() == 0
    return fun


git = _GitCall()


def RepoSourceVersion():
  """Return the version of the repo.git tree."""
  ver = getattr(RepoSourceVersion, 'version', None)

  # We avoid GitCommand so we don't run into circular deps -- GitCommand needs
  # to initialize version info we provide.
  if ver is None:
    env = GitCommand._GetBasicEnv()

    proj = os.path.dirname(os.path.abspath(__file__))
    env[GIT_DIR] = os.path.join(proj, '.git')
    result = subprocess.run([GIT, 'describe', HEAD], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, encoding='utf-8',
                            env=env, check=False)
    if result.returncode == 0:
      ver = result.stdout.strip()
      if ver.startswith('v'):
        ver = ver[1:]
    else:
      ver = 'unknown'
    setattr(RepoSourceVersion, 'version', ver)

  return ver


class UserAgent(object):
  """Mange User-Agent settings when talking to external services

  We follow the style as documented here:
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent
  """

  _os = None
  _repo_ua = None
  _git_ua = None

  @property
  def os(self):
    """The operating system name."""
    if self._os is None:
      os_name = sys.platform
      if os_name.lower().startswith('linux'):
        os_name = 'Linux'
      elif os_name == 'win32':
        os_name = 'Win32'
      elif os_name == 'cygwin':
        os_name = 'Cygwin'
      elif os_name == 'darwin':
        os_name = 'Darwin'
      self._os = os_name

    return self._os

  @property
  def repo(self):
    """The UA when connecting directly from repo."""
    if self._repo_ua is None:
      py_version = sys.version_info
      self._repo_ua = 'git-repo/%s (%s) git/%s Python/%d.%d.%d' % (
          RepoSourceVersion(),
          self.os,
          git.version_tuple().full,
          py_version.major, py_version.minor, py_version.micro)

    return self._repo_ua

  @property
  def git(self):
    """The UA when running git."""
    if self._git_ua is None:
      self._git_ua = 'git/%s (%s) git-repo/%s' % (
          git.version_tuple().full,
          self.os,
          RepoSourceVersion())

    return self._git_ua


user_agent = UserAgent()


def git_require(min_version, fail=False, msg=''):
  git_version = git.version_tuple()
  if min_version <= git_version:
    return True
  if fail:
    need = '.'.join(map(str, min_version))
    if msg:
      msg = ' for ' + msg
    print('fatal: git %s or later required%s' % (need, msg), file=sys.stderr)
    sys.exit(1)
  return False


def _build_env(
    _kwargs_only=(),
    bare: Optional[bool] = False,
    disable_editor: Optional[bool] = False,
    ssh_proxy: Optional[Any] = None,
    gitdir: Optional[str] = None,
    objdir: Optional[str] = None
):
  """Constucts an env dict for command execution."""

  assert _kwargs_only == (), '_build_env only accepts keyword arguments.'

  env = GitCommand._GetBasicEnv()

  if disable_editor:
    env['GIT_EDITOR'] = ':'
  if ssh_proxy:
    env['REPO_SSH_SOCK'] = ssh_proxy.sock()
    env['GIT_SSH'] = ssh_proxy.proxy
    env['GIT_SSH_VARIANT'] = 'ssh'
  if 'http_proxy' in env and 'darwin' == sys.platform:
    s = "'http.proxy=%s'" % (env['http_proxy'],)
    p = env.get('GIT_CONFIG_PARAMETERS')
    if p is not None:
      s = p + ' ' + s
    env['GIT_CONFIG_PARAMETERS'] = s
  if 'GIT_ALLOW_PROTOCOL' not in env:
    env['GIT_ALLOW_PROTOCOL'] = (
        'file:git:http:https:ssh:persistent-http:persistent-https:sso:rpc')
  env['GIT_HTTP_USER_AGENT'] = user_agent.git

  if objdir:
    # Set to the place we want to save the objects.
    env['GIT_OBJECT_DIRECTORY'] = objdir

    alt_objects = os.path.join(gitdir, 'objects') if gitdir else None
    if alt_objects and os.path.realpath(alt_objects) != os.path.realpath(objdir):
      # Allow git to search the original place in case of local or unique refs
      # that git will attempt to resolve even if we aren't fetching them.
      env['GIT_ALTERNATE_OBJECT_DIRECTORIES'] = alt_objects
  if bare and gitdir is not None:
      env[GIT_DIR] = gitdir

  return env


class GitCommand(object):
  """Wrapper around a single git invocation."""

  def __init__(self,
               project,
               cmdv,
               bare=False,
               input=None,
               capture_stdout=False,
               capture_stderr=False,
               merge_output=False,
               disable_editor=False,
               ssh_proxy=None,
               cwd=None,
               gitdir=None,
               objdir=None):

    if project:
      if not cwd:
        cwd = project.worktree
      if not gitdir:
        gitdir = project.gitdir

    # Git on Windows wants its paths only using / for reliability.
    if platform_utils.isWindows():
      if objdir:
        objdir = objdir.replace('\\', '/')
      if gitdir:
        gitdir = gitdir.replace('\\', '/')

    env = _build_env(
        disable_editor=disable_editor,
        ssh_proxy=ssh_proxy,
        objdir=objdir,
        gitdir=gitdir,
        bare=bare,
    )

    command = [GIT]
    if bare:
      cwd = None
    command.append(cmdv[0])
    # Need to use the --progress flag for fetch/clone so output will be
    # displayed as by default git only does progress output if stderr is a TTY.
    if sys.stderr.isatty() and cmdv[0] in ('fetch', 'clone'):
      if '--progress' not in cmdv and '--quiet' not in cmdv:
        command.append('--progress')
    command.extend(cmdv[1:])

    stdin = subprocess.PIPE if input else None
    stdout = subprocess.PIPE if capture_stdout else None
    stderr = (subprocess.STDOUT if merge_output else
              (subprocess.PIPE if capture_stderr else None))

    dbg = ''
    if IsTrace():
      global LAST_CWD
      global LAST_GITDIR

      if cwd and LAST_CWD != cwd:
        if LAST_GITDIR or LAST_CWD:
          dbg += '\n'
        dbg += ': cd %s\n' % cwd
        LAST_CWD = cwd

      if GIT_DIR in env and LAST_GITDIR != env[GIT_DIR]:
        if LAST_GITDIR or LAST_CWD:
          dbg += '\n'
        dbg += ': export GIT_DIR=%s\n' % env[GIT_DIR]
        LAST_GITDIR = env[GIT_DIR]

      if 'GIT_OBJECT_DIRECTORY' in env:
        dbg += ': export GIT_OBJECT_DIRECTORY=%s\n' % env['GIT_OBJECT_DIRECTORY']
      if 'GIT_ALTERNATE_OBJECT_DIRECTORIES' in env:
        dbg += ': export GIT_ALTERNATE_OBJECT_DIRECTORIES=%s\n' % (
            env['GIT_ALTERNATE_OBJECT_DIRECTORIES'])

      dbg += ': '
      dbg += ' '.join(command)
      if stdin == subprocess.PIPE:
        dbg += ' 0<|'
      if stdout == subprocess.PIPE:
        dbg += ' 1>|'
      if stderr == subprocess.PIPE:
        dbg += ' 2>|'
      elif stderr == subprocess.STDOUT:
        dbg += ' 2>&1'

    with Trace('git command %s %s with debug: %s', LAST_GITDIR, command, dbg):
      try:
        p = subprocess.Popen(command,
                             cwd=cwd,
                             env=env,
                             encoding='utf-8',
                             errors='backslashreplace',
                             stdin=stdin,
                             stdout=stdout,
                             stderr=stderr)
      except Exception as e:
        raise GitError('%s: %s' % (command[1], e))

      if ssh_proxy:
        ssh_proxy.add_client(p)

      self.process = p

      try:
        self.stdout, self.stderr = p.communicate(input=input)
      finally:
        if ssh_proxy:
          ssh_proxy.remove_client(p)
      self.rc = p.wait()

  @staticmethod
  def _GetBasicEnv():
    """Return a basic env for running git under.

    This is guaranteed to be side-effect free.
    """
    env = os.environ.copy()
    for key in (REPO_TRACE,
                GIT_DIR,
                'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                'GIT_OBJECT_DIRECTORY',
                'GIT_WORK_TREE',
                'GIT_GRAFT_FILE',
                'GIT_INDEX_FILE'):
      env.pop(key, None)
    return env

  def Wait(self):
    return self.rc
