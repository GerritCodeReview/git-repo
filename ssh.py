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

from git_command import git
import platform_utils
from repo_trace import Trace


PROXY_PATH = os.path.join(os.path.dirname(__file__), "git_ssh")


def _run_ssh_version():
    """run ssh -V to display the version number"""
    return subprocess.check_output(
        ["ssh", "-V"], stderr=subprocess.STDOUT
    ).decode()


def _parse_ssh_version(ver_str=None):
    """parse a ssh version string into a tuple"""
    if ver_str is None:
        ver_str = _run_ssh_version()
    m = re.match(r"^OpenSSH_([0-9.]+)(p[0-9]+)?[\s,]", ver_str)
    if m:
        return tuple(int(x) for x in m.group(1).split("."))
    else:
        return ()


@functools.lru_cache(maxsize=None)
def version():
    """return ssh version as a tuple"""
    try:
        return _parse_ssh_version()
    except FileNotFoundError:
        print("fatal: ssh not installed", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(
            "fatal: unable to detect ssh version"
            f" (code={e.returncode}, output={e.stdout})",
            file=sys.stderr,
        )
        sys.exit(1)


URI_SCP = re.compile(r"^([^@:]*@?[^:/]{1,}):")
URI_ALL = re.compile(r"^([a-z][a-z+-]*)://([^@/]*@?[^/]*)/")


class ProxyManager:
    """Manage various ssh clients & masters that we spawn.

    This will take care of sharing state between multiprocessing children, and
    make sure that if we crash, we don't leak any of the ssh sessions.

    The code should work with a single-process scenario too, and not add too
    much overhead due to the manager.
    """

    # Path to the ssh program to run which will pass our master settings along.
    # Set here more as a convenience API.
    proxy = PROXY_PATH

    def __init__(self, manager):
        # Protect access to the list of active masters.
        self._lock = multiprocessing.Lock()
        # List of active masters (pid).  These will be spawned on demand, and we
        # are responsible for shutting them all down at the end.
        self._masters = manager.list()
        # Set of active masters indexed by "host:port" information.
        # The value isn't used, but multiprocessing doesn't provide a set class.
        self._master_keys = manager.dict()
        # Whether ssh masters are known to be broken, so we give up entirely.
        self._master_broken = manager.Value("b", False)
        # List of active ssh sesssions.  Clients will be added & removed as
        # connections finish, so this list is just for safety & cleanup if we
        # crash.
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
            except:  # noqa: E722
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

        We won't grab any locks, so the caller has to do that.  This helps keep
        the business logic of actually creating the master separate from
        grabbing locks.
        """
        # Check to see whether we already think that the master is running; if
        # we think it's already running, return right away.
        if port is not None:
            key = f"{host}:{port}"
        else:
            key = host

        if key in self._master_keys:
            return True

        if self._master_broken.value or "GIT_SSH" in os.environ:
            # Failed earlier, so don't retry.
            return False

        # We will make two calls to ssh; this is the common part of both calls.
        command_base = ["ssh", "-o", "ControlPath %s" % self.sock(), host]
        if port is not None:
            command_base[1:1] = ["-p", str(port)]

        # Since the key wasn't in _master_keys, we think that master isn't
        # running... but before actually starting a master, we'll double-check.
        # This can be important because we can't tell that that 'git@myhost.com'
        # is the same as 'myhost.com' where "User git" is setup in the user's
        # ~/.ssh/config file.
        check_command = command_base + ["-O", "check"]
        with Trace("Call to ssh (check call): %s", " ".join(check_command)):
            try:
                check_process = subprocess.Popen(
                    check_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                check_process.communicate()  # read output, but ignore it...
                isnt_running = check_process.wait()

                if not isnt_running:
                    # Our double-check found that the master _was_ infact
                    # running.  Add to the list of keys.
                    self._master_keys[key] = True
                    return True
            except Exception:
                # Ignore excpetions.  We we will fall back to the normal command
                # and print to the log there.
                pass

        # Git protocol V2 is a new feature in git 2.18.0, made default in
        # git 2.26.0
        # It is faster and more efficient than V1.
        # To enable it when using SSH, the environment variable GIT_PROTOCOL
        # must be set in the SSH side channel when establishing the connection
        # to the git server.
        # See https://git-scm.com/docs/protocol-v2#_ssh_and_file_transport
        # Normally git does this by itself. But here, where the SSH connection
        # is established manually over ControlMaster via the repo-tool, it must
        # be passed in explicitly instead.
        # Based on https://git-scm.com/docs/gitprotocol-pack#_extra_parameters,
        # GIT_PROTOCOL is considered an "Extra Parameter" and must be ignored
        # by servers that do not understand it. This means that it is safe to
        # set it even when connecting to older servers.
        # It should also be safe to set the environment variable for older
        # local git versions, since it is only part of the ssh side channel.
        git_protocol_version = _get_git_protocol_version()
        ssh_git_protocol_args = [
            "-o",
            f"SetEnv GIT_PROTOCOL=version={git_protocol_version}",
        ]

        command = (
            command_base[:1]
            + ["-M", "-N", *ssh_git_protocol_args]
            + command_base[1:]
        )
        p = None
        try:
            with Trace("Call to ssh: %s", " ".join(command)):
                p = subprocess.Popen(command)
        except Exception as e:
            self._master_broken.value = True
            print(
                "\nwarn: cannot enable ssh control master for %s:%s\n%s"
                % (host, port, str(e)),
                file=sys.stderr,
            )
            return False

        time.sleep(1)
        ssh_died = p.poll() is not None
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
        # Bail before grabbing the lock if we already know that we aren't going
        # to try creating new masters below.
        if sys.platform in ("win32", "cygwin"):
            return False

        # Acquire the lock.  This is needed to prevent opening multiple masters
        # for the same host when we're running "repo sync -jN" (for N > 1) _and_
        # the manifest <remote fetch="ssh://xyz"> specifies a different host
        # from the one that was passed to repo init.
        with self._lock:
            return self._open_unlocked(host, port)

    def preconnect(self, url):
        """If |uri| will create a ssh connection, setup the ssh master for it."""  # noqa: E501
        m = URI_ALL.match(url)
        if m:
            scheme = m.group(1)
            host = m.group(2)
            if ":" in host:
                host, port = host.split(":")
            else:
                port = None
            if scheme in ("ssh", "git+ssh", "ssh+git"):
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
            tmp_dir = "/tmp"
            if not os.path.exists(tmp_dir):
                tmp_dir = tempfile.gettempdir()
            if version() < (6, 7):
                tokens = "%r@%h:%p"
            else:
                tokens = "%C"  # hash of %l%h%p%r
            self._sock_path = os.path.join(
                tempfile.mkdtemp("", "ssh-", tmp_dir), "master-" + tokens
            )
        return self._sock_path


@functools.lru_cache(maxsize=1)
def _get_git_protocol_version() -> str:
    """Return the git protocol version.

    The version is found by first reading the global git config.
    If no git config for protocol version exists, try to deduce the default
    protocol version based on the git version.

    See https://git-scm.com/docs/gitprotocol-v2 for details.
    """
    try:
        return subprocess.check_output(
            ["git", "config", "--get", "--global", "protocol.version"],
            encoding="utf-8",
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            # Exit code 1 means that the git config key was not found.
            # Try to imitate the defaults that git would have used.
            git_version = git.version_tuple()
            if git_version >= (2, 26, 0):
                # Since git version 2.26, protocol v2 is the default.
                return "2"
            return "1"
        # Other exit codes indicate error with reading the config.
        raise
