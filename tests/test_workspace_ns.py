# Copyright (C) 2026 The Android Open Source Project
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

"""Unittests for the workspace_ns.py module."""

import os
import socket
import sys
import tempfile
import unittest

import workspace_ns


class ComputeRuntimePreservationTests(unittest.TestCase):
    """Check the generic /run preservation policy against a synthetic tree."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.run = os.path.join(self.tempdir.name, "run")
        os.mkdir(self.run)
        self.uid = os.getuid()
        # Model a real /run: everything is root-owned unless listed here.
        self.user_owned = set()

    def tearDown(self):
        self.tempdir.cleanup()

    def _owner_of(self, path):
        return self.uid if path in self.user_owned else 0

    def _mkdir(self, *parts, owned=False):
        p = os.path.join(self.run, *parts)
        os.makedirs(p, exist_ok=True)
        if owned:
            self.user_owned.add(p)
        return p

    def _mkfile(self, *parts, owned=False):
        p = os.path.join(self.run, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w"):
            pass
        if owned:
            self.user_owned.add(p)
        return p

    def _mksock(self, *parts):
        p = os.path.join(self.run, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(p)
        self.addCleanup(s.close)
        return p

    def _compute(self, **kwargs):
        kwargs.setdefault("env", {})
        kwargs.setdefault("resolv_conf", os.path.join(self.run, "nonexist"))
        kwargs.setdefault("owner_of", self._owner_of)
        return workspace_ns.compute_runtime_preservation(
            self.uid, run_root=self.run, **kwargs
        )

    def test_empty(self):
        self.assertEqual(self._compute(), [])

    def test_root_owned_files_dropped(self):
        self._mkfile("utmp")
        self._mkdir("systemd", "system")
        self.assertEqual(self._compute(), [])

    def test_user_owned_entries(self):
        # /run/user is root-owned, /run/user/<uid> is ours: keep the latter.
        self._mkdir("user")
        mine = self._mkdir("user", str(self.uid), owned=True)
        self._mkdir("user", str(self.uid), "bus")
        # /run/credentials-cache/loas-<user> style.
        self._mkdir("credentials-cache")
        creds = self._mkdir("credentials-cache", "loas-me", owned=True)
        self.assertEqual(sorted(self._compute()), sorted([mine, creds]))

    def test_sockets_kept(self):
        s1 = self._mksock("daemon.sock")
        s2 = self._mksock("dbus", "system_bus_socket")
        self.assertEqual(sorted(self._compute()), sorted([s1, s2]))

    def test_depth_limit(self):
        # A socket three levels down inside root-owned dirs is not found.
        self._mksock("a", "b", "deep.sock")
        self.assertEqual(self._compute(), [])

    def test_env_vars(self):
        sock = self._mkfile("agent", "ssh.sock")
        xauth = self._mkfile("x", "auth")
        env = {
            "SSH_AUTH_SOCK": sock,
            "XAUTHORITY": xauth,
            "XDG_RUNTIME_DIR": "/elsewhere/not/under/run",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path="
            + os.path.join(self.run, "bus", "sock")
            + ",guid=abc",
        }
        res = self._compute(env=env)
        self.assertIn(sock, res)
        self.assertIn(xauth, res)
        self.assertIn(os.path.join(self.run, "bus", "sock"), res)
        self.assertNotIn("/elsewhere/not/under/run", res)

    def test_resolv_conf_symlink(self):
        target = self._mkfile("resolvconf", "resolv.conf")
        link = os.path.join(self.tempdir.name, "resolv.conf")
        os.symlink(target, link)
        res = self._compute(resolv_conf=link)
        self.assertIn(target, res)

    def test_extra(self):
        extra = self._mkfile("vendor", "thing")
        self.assertIn(extra, self._compute(extra=[extra]))
        # Extras outside run_root are ignored.
        self.assertEqual(self._compute(extra=["/nope"]), [])

    def test_dedup_parent_child(self):
        parent = self._mkdir("p")
        child = os.path.join(parent, "c")
        os.mkdir(child)
        res = self._compute(extra=[child, parent])
        self.assertEqual(res, [parent])


class ExplainUsernsFailureTests(unittest.TestCase):
    def test_always_returns_text(self):
        import errno

        self.assertTrue(workspace_ns.explain_userns_failure(errno.EPERM))
        self.assertTrue(workspace_ns.explain_userns_failure(errno.EINVAL))


class FakeLibc:
    """Records calls instead of touching the kernel."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or set()

    def unshare(self, flags, what):
        self.calls.append(("unshare", flags))
        if what in self.fail_on:
            raise workspace_ns.NamespaceError(what, 1)

    def mount(self, source, target, fstype, flags, data=None):
        self.calls.append(("mount", source, target, fstype, flags))
        if target in self.fail_on:
            raise workspace_ns.NamespaceError(f"mount {target}", 1)

    def prctl(self, option, arg2):
        self.calls.append(("prctl", option, arg2))


class OverlayValidationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.src = os.path.join(self.tempdir.name, "src")
        self.dst = os.path.join(self.tempdir.name, "dst")
        os.mkdir(self.src)
        os.mkdir(self.dst)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_missing_source_rejected_before_unshare(self):
        libc = FakeLibc()
        ov = workspace_ns.Overlay(
            [(os.path.join(self.tempdir.name, "nope"), self.dst)],
            preserve_runtime=False,
            libc=libc,
        )
        with self.assertRaises(workspace_ns.NamespaceError):
            ov.apply()
        self.assertEqual(libc.calls, [])

    def test_missing_target_rejected_before_unshare(self):
        libc = FakeLibc()
        ov = workspace_ns.Overlay(
            [(self.src, os.path.join(self.tempdir.name, "nope"))],
            preserve_runtime=False,
            libc=libc,
        )
        with self.assertRaises(workspace_ns.NamespaceError):
            ov.apply()
        self.assertEqual(libc.calls, [])


@unittest.skipUnless(sys.platform == "linux", "Linux namespaces only")
class RealOverlayTests(unittest.TestCase):
    """End-to-end overlay in a child process; skipped where userns is off."""

    @classmethod
    def setUpClass(cls):
        ok, _ = workspace_ns.is_supported()
        if not ok:
            raise unittest.SkipTest("namespaces unsupported")
        pid = os.fork()
        if pid == 0:
            try:
                workspace_ns.Libc().unshare(workspace_ns.CLONE_NEWUSER, "probe")
                os._exit(0)
            except Exception:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        if os.WEXITSTATUS(status) != 0:
            raise unittest.SkipTest("unprivileged user namespaces disabled")

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.src = os.path.join(self.tempdir.name, "src")
        self.dst = os.path.join(self.tempdir.name, "dst")
        os.mkdir(self.src)
        os.mkdir(self.dst)
        with open(os.path.join(self.src, "marker"), "w"):
            pass

    def tearDown(self):
        self.tempdir.cleanup()

    def test_bind_visible_inside_not_outside(self):
        ov = workspace_ns.Overlay(
            [(self.src, self.dst)], preserve_runtime=False
        )
        rc = workspace_ns.run_in_overlay(
            ov,
            ["sh", "-c", f"test -e {self.dst}/marker"],
            dict(os.environ),
        )
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.dst, "marker")))

    def test_exit_code_propagates(self):
        ov = workspace_ns.Overlay(
            [(self.src, self.dst)], preserve_runtime=False
        )
        rc = workspace_ns.run_in_overlay(
            ov, ["sh", "-c", "exit 42"], dict(os.environ)
        )
        self.assertEqual(rc, 42)

    def test_runtime_policy_keeps_run_usable(self):
        ov = workspace_ns.Overlay([(self.src, self.dst)], preserve_runtime=True)
        # /run exists and is writable by us afterwards (it is our tmpfs).
        rc = workspace_ns.run_in_overlay(
            ov,
            ["sh", "-c", "test -d /run && touch /run/repo-ws-probe"],
            dict(os.environ),
        )
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists("/run/repo-ws-probe"))
