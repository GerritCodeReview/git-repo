# -*- coding:utf-8 -*-
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
import subprocess
import tempfile
from signal import SIGTERM

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

_ssh_proxy_path = None
_ssh_sock_path = None
_ssh_clients = []


def ssh_sock(create=True):
  global _ssh_sock_path
  if _ssh_sock_path is None:
    if not create:
      return None
    tmp_dir = '/tmp'
    if not os.path.exists(tmp_dir):
      tmp_dir = tempfile.gettempdir()
    _ssh_sock_path = os.path.join(
        tempfile.mkdtemp('', 'ssh-', tmp_dir),
        'master-%r@%h:%p')
  return _ssh_sock_path


def _ssh_proxy():
  global _ssh_proxy_path
  if _ssh_proxy_path is None:
    _ssh_proxy_path = os.path.join(
        os.path.dirname(__file__),
        'git_ssh')
  return _ssh_proxy_path


def _add_ssh_client(p):
  _ssh_clients.append(p)


def _remove_ssh_client(p):
  try:
    _ssh_clients.remove(p)
  except ValueError:
    pass


def terminate_ssh_clients():
  global _ssh_clients
  for p in _ssh_clients:
    try:
      os.kill(p.pid, SIGTERM)
      p.wait()
    except OSError:
      pass
  _ssh_clients = []


_git_version = None


class _GitCall(object):
  def version_tuple(self):
    global _git_version
    if _git_version is None:
      _git_version = Wrapper().ParseGitVersion()
      if _git_version is None:
        print('fatal: unable to detect git version', file=sys.stderr)
        sys.exit(1)
    return _git_version

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

    p = subprocess.Popen([GIT, 'describe', HEAD], stdout=subprocess.PIPE,
                         env=env)
    if p.wait() == 0:
      ver = p.stdout.read().strip().decode('utf-8')
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


class GitCommand(object):
  def __init__(self,
               project,
               cmdv,
               bare=False,
               provide_stdin=False,
               capture_stdout=False,
               capture_stderr=False,
               merge_output=False,
               disable_editor=False,
               ssh_proxy=False,
               cwd=None,
               gitdir=None):
    env = self._GetBasicEnv()

    # If we are not capturing std* then need to print it.
    self.tee = {'stdout': not capture_stdout, 'stderr': not capture_stderr}

    if disable_editor:
      env['GIT_EDITOR'] = ':'
    if ssh_proxy:
      env['REPO_SSH_SOCK'] = ssh_sock()
      env['GIT_SSH'] = _ssh_proxy()
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

    if project:
      if not cwd:
        cwd = project.worktree
      if not gitdir:
        gitdir = project.gitdir

    command = [GIT]
    if bare:
      if gitdir:
        env[GIT_DIR] = gitdir
      cwd = None
    command.append(cmdv[0])
    # Need to use the --progress flag for fetch/clone so output will be
    # displayed as by default git only does progress output if stderr is a TTY.
    if sys.stderr.isatty() and cmdv[0] in ('fetch', 'clone'):
      if '--progress' not in cmdv and '--quiet' not in cmdv:
        command.append('--progress')
    command.extend(cmdv[1:])

    if provide_stdin:
      stdin = subprocess.PIPE
    else:
      stdin = None

    stdout = subprocess.PIPE
    stderr = subprocess.STDOUT if merge_output else subprocess.PIPE

    if IsTrace():
      global LAST_CWD
      global LAST_GITDIR

      dbg = ''

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
      Trace('%s', dbg)

    try:
      p = subprocess.Popen(command,
                           cwd=cwd,
                           env=env,
                           stdin=stdin,
                           stdout=stdout,
                           stderr=stderr)
    except Exception as e:
      raise GitError('%s: %s' % (command[1], e))

    if ssh_proxy:
      _add_ssh_client(p)

    self.process = p
    self.stdin = p.stdin

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
    try:
      p = self.process
      rc = self._CaptureOutput()
    finally:
      _remove_ssh_client(p)
    return rc

  def _CaptureOutput(self):
    p = self.process
    s_in = platform_utils.FileDescriptorStreams.create()
    s_in.add(p.stdout, sys.stdout, 'stdout')
    if p.stderr is not None:
      s_in.add(p.stderr, sys.stderr, 'stderr')
    self.stdout = ''
    self.stderr = ''

    while not s_in.is_done:
      in_ready = s_in.select()
      for s in in_ready:
        buf = s.read()
        if not buf:
          s_in.remove(s)
          continue
        if not hasattr(buf, 'encode'):
          buf = buf.decode()
        if s.std_name == 'stdout':
          self.stdout += buf
        else:
          self.stderr += buf
        if self.tee[s.std_name]:
          s.dest.write(buf)
          s.dest.flush()
    return p.wait()
