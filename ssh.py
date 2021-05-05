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

"""Common SSH management logic."""

import functools
import os
import re
import signal
import subprocess
import sys
import tempfile
try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading
import time

import platform_utils
from repo_trace import Trace


_ssh_proxy_path = None
_ssh_sock_path = None
_ssh_clients = []


def _run_ssh_version():
  """run ssh -V to display the version number"""
  return subprocess.check_output(['ssh', '-V'], stderr=subprocess.STDOUT).decode()


def _parse_ssh_version(ver_str=None):
  """parse a ssh version string into a tuple"""
  if ver_str is None:
    ver_str = _run_ssh_version()
  m = re.match(r'^OpenSSH_([0-9.]+)(p[0-9]+)?\s', ver_str)
  if m:
    return tuple(int(x) for x in m.group(1).split('.'))
  else:
    return ()


@functools.lru_cache(maxsize=None)
def version():
  """return ssh version as a tuple"""
  try:
    return _parse_ssh_version()
  except subprocess.CalledProcessError:
    print('fatal: unable to detect ssh version', file=sys.stderr)
    sys.exit(1)


def proxy():
  global _ssh_proxy_path
  if _ssh_proxy_path is None:
    _ssh_proxy_path = os.path.join(
        os.path.dirname(__file__),
        'git_ssh')
  return _ssh_proxy_path


def add_client(p):
  _ssh_clients.append(p)


def remove_client(p):
  try:
    _ssh_clients.remove(p)
  except ValueError:
    pass


def _terminate_clients():
  global _ssh_clients
  for p in _ssh_clients:
    try:
      os.kill(p.pid, signal.SIGTERM)
      p.wait()
    except OSError:
      pass
  _ssh_clients = []


_master_processes = []
_master_keys = set()
_ssh_master = True
_master_keys_lock = None


def init():
  """Should be called once at the start of repo to init ssh master handling.

  At the moment, all we do is to create our lock.
  """
  global _master_keys_lock
  assert _master_keys_lock is None, "Should only call init once"
  _master_keys_lock = _threading.Lock()


def _open_ssh(host, port=None):
  global _ssh_master

  # Bail before grabbing the lock if we already know that we aren't going to
  # try creating new masters below.
  if sys.platform in ('win32', 'cygwin'):
    return False

  # Acquire the lock.  This is needed to prevent opening multiple masters for
  # the same host when we're running "repo sync -jN" (for N > 1) _and_ the
  # manifest <remote fetch="ssh://xyz"> specifies a different host from the
  # one that was passed to repo init.
  _master_keys_lock.acquire()
  try:

    # Check to see whether we already think that the master is running; if we
    # think it's already running, return right away.
    if port is not None:
      key = '%s:%s' % (host, port)
    else:
      key = host

    if key in _master_keys:
      return True

    if not _ssh_master or 'GIT_SSH' in os.environ:
      # Failed earlier, so don't retry.
      return False

    # We will make two calls to ssh; this is the common part of both calls.
    command_base = ['ssh',
                    '-o', 'ControlPath %s' % sock(),
                    host]
    if port is not None:
      command_base[1:1] = ['-p', str(port)]

    # Since the key wasn't in _master_keys, we think that master isn't running.
    # ...but before actually starting a master, we'll double-check.  This can
    # be important because we can't tell that that 'git@myhost.com' is the same
    # as 'myhost.com' where "User git" is setup in the user's ~/.ssh/config file.
    check_command = command_base + ['-O', 'check']
    try:
      Trace(': %s', ' '.join(check_command))
      check_process = subprocess.Popen(check_command,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
      check_process.communicate()  # read output, but ignore it...
      isnt_running = check_process.wait()

      if not isnt_running:
        # Our double-check found that the master _was_ infact running.  Add to
        # the list of keys.
        _master_keys.add(key)
        return True
    except Exception:
      # Ignore excpetions.  We we will fall back to the normal command and print
      # to the log there.
      pass

    command = command_base[:1] + ['-M', '-N'] + command_base[1:]
    try:
      Trace(': %s', ' '.join(command))
      p = subprocess.Popen(command)
    except Exception as e:
      _ssh_master = False
      print('\nwarn: cannot enable ssh control master for %s:%s\n%s'
            % (host, port, str(e)), file=sys.stderr)
      return False

    time.sleep(1)
    ssh_died = (p.poll() is not None)
    if ssh_died:
      return False

    _master_processes.append(p)
    _master_keys.add(key)
    return True
  finally:
    _master_keys_lock.release()


def close():
  global _master_keys_lock

  _terminate_clients()

  for p in _master_processes:
    try:
      os.kill(p.pid, signal.SIGTERM)
      p.wait()
    except OSError:
      pass
  del _master_processes[:]
  _master_keys.clear()

  d = sock(create=False)
  if d:
    try:
      platform_utils.rmdir(os.path.dirname(d))
    except OSError:
      pass

  # We're done with the lock, so we can delete it.
  _master_keys_lock = None


URI_SCP = re.compile(r'^([^@:]*@?[^:/]{1,}):')
URI_ALL = re.compile(r'^([a-z][a-z+-]*)://([^@/]*@?[^/]*)/')


def preconnect(url):
  m = URI_ALL.match(url)
  if m:
    scheme = m.group(1)
    host = m.group(2)
    if ':' in host:
      host, port = host.split(':')
    else:
      port = None
    if scheme in ('ssh', 'git+ssh', 'ssh+git'):
      return _open_ssh(host, port)
    return False

  m = URI_SCP.match(url)
  if m:
    host = m.group(1)
    return _open_ssh(host)

  return False

def sock(create=True):
  global _ssh_sock_path
  if _ssh_sock_path is None:
    if not create:
      return None
    tmp_dir = '/tmp'
    if not os.path.exists(tmp_dir):
      tmp_dir = tempfile.gettempdir()
    if version() < (6, 7):
      tokens = '%r@%h:%p'
    else:
      tokens = '%C'  # hash of %l%h%p%r
    _ssh_sock_path = os.path.join(
        tempfile.mkdtemp('', 'ssh-', tmp_dir),
        'master-' + tokens)
  return _ssh_sock_path
