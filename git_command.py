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
from error import GitError

GIT = 'git'
MIN_GIT_VERSION = (1, 5, 4)
GIT_DIR = 'GIT_DIR'
REPO_TRACE = 'REPO_TRACE'

LAST_GITDIR = None
LAST_CWD = None
try:
  TRACE = os.environ[REPO_TRACE] == '1'
except KeyError:
  TRACE = False


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

class GitCommand(object):
  def __init__(self,
               project,
               cmdv,
               bare = False,
               provide_stdin = False,
               capture_stdout = False,
               capture_stderr = False,
               disable_editor = False,
               cwd = None,
               gitdir = None):
    env = dict(os.environ)

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
      env['GIT_EDITOR'] = ':'

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

    if TRACE:
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
      print >>sys.stderr, dbg

    try:
      p = subprocess.Popen(command,
                           cwd = cwd,
                           env = env,
                           stdin = stdin,
                           stdout = stdout,
                           stderr = stderr)
    except Exception, e:
      raise GitError('%s: %s' % (command[1], e))

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

    return self.process.wait()
