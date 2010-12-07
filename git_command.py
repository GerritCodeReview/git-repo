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

import os
import sys
import subprocess
import tempfile
from signal import SIGTERM
from error import GitError
from trace import REPO_TRACE, IsTrace, Trace

GIT = 'git'
MIN_GIT_VERSION = (1, 5, 4)
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
    dir = '/tmp'
    if not os.path.exists(dir):
      dir = tempfile.gettempdir()
    _ssh_sock_path = os.path.join(
      tempfile.mkdtemp('', 'ssh-', dir),
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

class _GitCall(object):
  def version(self):
    p = GitCommand(None, ['--version'], capture_stdout=True)
    if p.Wait() == 0:
      return p.stdout
    return None

  def __getattr__(self, name):
    name = name.replace('_','-')
    def fun(*cmdv):
      command = [name]
      command.extend(cmdv)
      return GitCommand(None, command).Wait() == 0
    return fun
git = _GitCall()

_git_version = None

def git_require(min_version, fail=False):
  global _git_version

  if _git_version is None:
    ver_str = git.version()
    if ver_str.startswith('git version '):
      _git_version = tuple(
        map(lambda x: int(x),
          ver_str[len('git version '):].strip().split('.')[0:3]
        ))
    else:
      print >>sys.stderr, 'fatal: "%s" unsupported' % ver_str
      sys.exit(1)

  if min_version <= _git_version:
    return True
  if fail:
    need = '.'.join(map(lambda x: str(x), min_version))
    print >>sys.stderr, 'fatal: git %s or later required' % need
    sys.exit(1)
  return False

def _setenv(env, name, value):
  env[name] = value.encode()

class GitCommand(object):
  def __init__(self,
               project,
               cmdv,
               bare = False,
               provide_stdin = False,
               capture_stdout = False,
               capture_stderr = False,
               disable_editor = False,
               ssh_proxy = False,
               cwd = None,
               gitdir = None):
    env = os.environ.copy()

    for e in [REPO_TRACE,
              GIT_DIR,
              'GIT_ALTERNATE_OBJECT_DIRECTORIES',
              'GIT_OBJECT_DIRECTORY',
              'GIT_WORK_TREE',
              'GIT_GRAFT_FILE',
              'GIT_INDEX_FILE']:
      if e in env:
        del env[e]

    if disable_editor:
      _setenv(env, 'GIT_EDITOR', ':')
    if ssh_proxy:
      _setenv(env, 'REPO_SSH_SOCK', ssh_sock())
      _setenv(env, 'GIT_SSH', _ssh_proxy())

    if project:
      if not cwd:
        cwd = project.worktree
      if not gitdir:
        gitdir = project.gitdir

    command = [GIT]
    if bare:
      if gitdir:
        _setenv(env, GIT_DIR, gitdir)
      cwd = None
    command.extend(cmdv)

    if provide_stdin:
      stdin = subprocess.PIPE
    else:
      stdin = None

    if capture_stdout:
      stdout = subprocess.PIPE
    else:
      stdout = None

    if capture_stderr:
      stderr = subprocess.PIPE
    else:
      stderr = None

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
      Trace('%s', dbg)

    try:
      p = subprocess.Popen(command,
                           cwd = cwd,
                           env = env,
                           stdin = stdin,
                           stdout = stdout,
                           stderr = stderr)
    except Exception, e:
      raise GitError('%s: %s' % (command[1], e))

    if ssh_proxy:
      _add_ssh_client(p)

    self.process = p
    self.stdin = p.stdin

  def Wait(self):
    p = self.process

    if p.stdin:
      p.stdin.close()
      self.stdin = None

    if p.stdout:
      self.stdout = p.stdout.read()
      p.stdout.close()
    else:
      p.stdout = None

    if p.stderr:
      self.stderr = p.stderr.read()
      p.stderr.close()
    else:
      p.stderr = None

    try:
      rc = p.wait()
    finally:
      _remove_ssh_client(p)
    return rc
