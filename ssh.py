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
import multiprocessing
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

import platform_utils
from repo_trace import Trace


PROXY_PATH = os.path.join(os.path.dirname(__file__), 'git_ssh')


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


URI_SCP = re.compile(r'^([^@:]*@?[^:/]{1,}):')
URI_ALL = re.compile(r'^([a-z][a-z+-]*)://([^@/]*@?[^/]*)/')


class ProxyManager:
  """Manage various ssh clients & masters that we spawn.

  This will take care of sharing state between multiprocessing children, and
  make sure that if we crash, we don't leak any of the ssh sessions.

  The code should work with a single-process scenario too, and not add too much
  overhead due to the manager.
  """

  # Path to the ssh program to run which will pass our master settings along.
  # Set here more as a convenience API.
  proxy = PROXY_PATH

  def __init__(self, manager):
    # Protect access to the list of active masters.
    self._lock = multiprocessing.Lock()
    # List of active masters (pid).  These will be spawned on demand, and we are
    # responsible for shutting them all down at the end.
    self._masters = manager.list()
    # Set of active masters indexed by "host:port" information.
    # The value isn't used, but multiprocessing doesn't provide a set class.
    self._master_keys = manager.dict()
    # Whether ssh masters are known to be broken, so we give up entirely.
    self._master_broken = manager.Value('b', False)
    # List of active ssh sesssions.  Clients will be added & removed as
    # connections finish, so this list is just for safety & cleanup if we crash.
    self._clients = manager.list()
    # Path to directory for holding master sockets.
    self._sock_path = None

  def __enter__(self):
    """Enter a new context."""
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    """Exit a context & clean up all resources."""
    self.close()

  def add_client(self, proc):
    """Track a new ssh session."""
    self._clients.append(proc.pid)

  def remove_client(self, proc):
    """Remove a completed ssh session."""
    try:
      self._clients.remove(proc.pid)
    except ValueError:
      pass

  def add_master(self, proc):
    """Track a new master connection."""
    self._masters.append(proc.pid)

  def _terminate(self, procs):
    """Kill all |procs|."""
    for pid in procs:
      try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
      except OSError:
        pass

    # The multiprocessing.list() API doesn't provide many standard list()
    # methods, so we have to manually clear the list.
    while True:
      try:
        procs.pop(0)
      except:
        break

  def close(self):
    """Close this active ssh session.

    Kill all ssh clients & masters we created, and nuke the socket dir.
    """
    self._terminate(self._clients)
    self._terminate(self._masters)

    d = self.sock(create=False)
    if d:
      try:
        platform_utils.rmdir(os.path.dirname(d))
      except OSError:
        pass

  def _open_unlocked(self, host, port=None):
    """Make sure a ssh master session exists for |host| & |port|.

    If one doesn't exist already, we'll create it.

    We won't grab any locks, so the caller has to do that.  This helps keep the
    business logic of actually creating the master separate from grabbing locks.
    """
    # Check to see whether we already think that the master is running; if we
    # think it's already running, return right away.
    if port is not None:
      key = '%s:%s' % (host, port)
    else:
      key = host

    if key in self._master_keys:
      return True

    if self._master_broken.value or 'GIT_SSH' in os.environ:
      # Failed earlier, so don't retry.
      return False

    # We will make two calls to ssh; this is the common part of both calls.
    command_base = ['ssh', '-o', 'ControlPath %s' % self.sock(), host]
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
        self._master_keys[key] = True
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
      self._master_broken.value = True
      print('\nwarn: cannot enable ssh control master for %s:%s\n%s'
            % (host, port, str(e)), file=sys.stderr)
      return False

    time.sleep(1)
    ssh_died = (p.poll() is not None)
    if ssh_died:
      return False

    self.add_master(p)
    self._master_keys[key] = True
    return True

  def _open(self, host, port=None):
    """Make sure a ssh master session exists for |host| & |port|.

    If one doesn't exist already, we'll create it.

    This will obtain any necessary locks to avoid inter-process races.
    """
    # Bail before grabbing the lock if we already know that we aren't going to
    # try creating new masters below.
    if sys.platform in ('win32', 'cygwin'):
      return False

    # Acquire the lock.  This is needed to prevent opening multiple masters for
    # the same host when we're running "repo sync -jN" (for N > 1) _and_ the
    # manifest <remote fetch="ssh://xyz"> specifies a different host from the
    # one that was passed to repo init.
    with self._lock:
      return self._open_unlocked(host, port)

  def preconnect(self, url):
    """If |uri| will create a ssh connection, setup the ssh master for it."""
    m = URI_ALL.match(url)
    if m:
      scheme = m.group(1)
      host = m.group(2)
      if ':' in host:
        host, port = host.split(':')
      else:
        port = None
      if scheme in ('ssh', 'git+ssh', 'ssh+git'):
        return self._open(host, port)
      return False

    m = URI_SCP.match(url)
    if m:
      host = m.group(1)
      return self._open(host)

    return False

  def sock(self, create=True):
    """Return the path to the ssh socket dir.

    This has all the master sockets so clients can talk to them.
    """
    if self._sock_path is None:
      if not create:
        return None
      tmp_dir = '/tmp'
      if not os.path.exists(tmp_dir):
        tmp_dir = tempfile.gettempdir()
      if version() < (6, 7):
        tokens = '%r@%h:%p'
      else:
        tokens = '%C'  # hash of %l%h%p%r
      self._sock_path = os.path.join(
          tempfile.mkdtemp('', 'ssh-', tmp_dir),
          'master-' + tokens)
    return self._sock_path
