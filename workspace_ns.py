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

"""Mount-namespace overlay used by `repo workspace`.

A workspace is a linked git worktree stored under .repo/workspaces/.  To make
it usable by build systems that key their state on the canonical project path,
we run the user's shell in a private user+mount namespace where the worktree is
bind-mounted over the project directory and a per-workspace output directory
is bind-mounted over <client>/out.

Only Linux syscalls via ctypes are used; there are no external dependencies.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import stat
import sys
from typing import Callable, Iterable, List, Optional, Sequence, Tuple


CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
MS_BIND = 0x1000
MS_REC = 0x4000
MS_PRIVATE = 1 << 18
PR_SET_NO_NEW_PRIVS = 38

RUN_ROOT = "/run"


class NamespaceError(Exception):
    """Raised when the overlay cannot be established."""


class Libc:
    """Thin wrapper around the handful of libc calls we need.

    Kept as a class so tests can substitute a fake.
    """

    def __init__(self):
        if sys.platform != "linux":
            raise NamespaceError(
                f"workspace overlays require Linux (got {sys.platform})"
            )
        self._libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        self._libc.unshare.argtypes = [ctypes.c_int]
        self._libc.unshare.restype = ctypes.c_int
        self._libc.mount.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self._libc.mount.restype = ctypes.c_int
        self._libc.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        self._libc.prctl.restype = ctypes.c_int

    def _check(self, ret: int, what: str) -> None:
        if ret != 0:
            err = ctypes.get_errno()
            raise NamespaceError(f"{what}: {os.strerror(err)}", err)

    def unshare(self, flags: int, what: str) -> None:
        self._check(self._libc.unshare(flags), what)

    def mount(
        self,
        source: Optional[str],
        target: str,
        fstype: Optional[str],
        flags: int,
        data: Optional[str] = None,
    ) -> None:
        src = source.encode() if source is not None else None
        fst = fstype.encode() if fstype is not None else None
        dat = data.encode() if data is not None else None
        self._check(
            self._libc.mount(src, target.encode(), fst, flags, dat),
            f"mount {source or ''} -> {target}",
        )

    def prctl(self, option: int, arg2: int) -> None:
        self._check(self._libc.prctl(option, arg2, 0, 0, 0), "prctl")


def is_supported() -> Tuple[bool, str]:
    """Return (ok, reason) describing whether overlays can work here."""
    if sys.platform != "linux":
        return False, f"workspace overlays require Linux (got {sys.platform})"
    try:
        Libc()
    except (NamespaceError, OSError, AttributeError) as e:
        return False, str(e)
    return True, ""


def explain_userns_failure(err: int) -> str:
    """Give the user something actionable when CLONE_NEWUSER fails."""
    hints = []
    if err in (errno.EPERM, errno.EACCES):
        for path, bad, msg in (
            (
                "/proc/sys/kernel/unprivileged_userns_clone",
                "0",
                "unprivileged user namespaces are disabled "
                "(sysctl kernel.unprivileged_userns_clone=0)",
            ),
            (
                "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
                "1",
                "AppArmor restricts unprivileged user namespaces "
                "(sysctl kernel.apparmor_restrict_unprivileged_userns=1)",
            ),
            (
                "/proc/sys/user/max_user_namespaces",
                "0",
                "user namespaces are disabled (user.max_user_namespaces=0)",
            ),
        ):
            try:
                with open(path) as f:
                    if f.read().strip() == bad:
                        hints.append(msg)
            except OSError:
                pass
    if not hints:
        hints.append(
            "the kernel or container runtime refused to create a user "
            "namespace"
        )
    return "; ".join(hints)


def _is_under(path: str, root: str) -> bool:
    root = root.rstrip("/") + "/"
    return path.startswith(root)


def _owned_or_socket(path: str, uid: int, owner_of=None) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return False
    owner = owner_of(path) if owner_of else st.st_uid
    return owner == uid or stat.S_ISSOCK(st.st_mode)


def compute_runtime_preservation(
    uid: int,
    env: Optional[dict] = None,
    run_root: str = RUN_ROOT,
    extra: Iterable[str] = (),
    listdir: Callable[[str], List[str]] = os.listdir,
    resolv_conf: str = "/etc/resolv.conf",
    owner_of: Optional[Callable[[str], int]] = None,
) -> List[str]:
    """Return host paths under |run_root| that must survive the /run tmpfs.

    The policy is deliberately generic: anything the user owns (depth <= 2),
    any Unix socket (depth <= 2), anything named by the usual runtime
    environment variables, the resolver file, plus explicit extras.

    |listdir| and |owner_of| exist so tests can model a root-owned /run.
    """
    if env is None:
        env = os.environ
    found = []

    def add(p: str) -> None:
        if not p or not _is_under(p, run_root):
            return
        p = os.path.normpath(p)
        if p == run_root or p in found:
            return
        # Drop anything already covered by a parent we are binding.
        for existing in found:
            if _is_under(p, existing):
                return
        found[:] = [e for e in found if not _is_under(e, p)]
        found.append(p)

    try:
        level1 = listdir(run_root)
    except OSError:
        level1 = []
    for name in sorted(level1):
        p1 = os.path.join(run_root, name)
        if _owned_or_socket(p1, uid, owner_of):
            add(p1)
            continue
        if not os.path.isdir(p1) or os.path.islink(p1):
            continue
        try:
            level2 = listdir(p1)
        except OSError:
            continue
        for name2 in sorted(level2):
            p2 = os.path.join(p1, name2)
            if _owned_or_socket(p2, uid, owner_of):
                add(p2)

    for var in ("XDG_RUNTIME_DIR", "SSH_AUTH_SOCK", "XAUTHORITY"):
        add(env.get(var, ""))
    dbus = env.get("DBUS_SESSION_BUS_ADDRESS", "")
    for part in dbus.split(";"):
        for kv in part.split(","):
            if kv.startswith("unix:path=") or kv.startswith("path="):
                add(kv.split("=", 1)[1])

    if os.path.islink(resolv_conf):
        try:
            add(os.path.realpath(resolv_conf))
        except OSError:
            pass

    for p in extra:
        add(os.path.abspath(p))

    return found


class Overlay:
    """Describes and applies a workspace overlay in the current process."""

    def __init__(
        self,
        binds: Sequence[Tuple[str, str]],
        preserve_runtime: bool = True,
        extra_runtime_binds: Iterable[str] = (),
        libc: Optional[Libc] = None,
    ):
        """
        Args:
            binds: (source, target) pairs bind-mounted after the runtime
                policy, in order.  Targets must already exist.
            preserve_runtime: apply the /run tmpfs + preservation policy.
            extra_runtime_binds: additional host paths to preserve.
        """
        self.binds = list(binds)
        self.preserve_runtime = preserve_runtime
        self.extra_runtime_binds = list(extra_runtime_binds)
        self._libc = libc

    def _enter_userns(self, libc: Libc) -> None:
        uid, gid = os.getuid(), os.getgid()
        try:
            libc.unshare(CLONE_NEWUSER, "unshare(CLONE_NEWUSER)")
        except NamespaceError as e:
            err = e.args[1] if len(e.args) > 1 else 0
            raise NamespaceError(f"{e.args[0]}: {explain_userns_failure(err)}")
        try:
            with open("/proc/self/setgroups", "w") as f:
                f.write("deny")
        except OSError:
            # Older kernels lack setgroups; gid_map still works.
            pass
        try:
            with open("/proc/self/uid_map", "w") as f:
                f.write(f"{uid} {uid} 1\n")
            with open("/proc/self/gid_map", "w") as f:
                f.write(f"{gid} {gid} 1\n")
        except OSError as e:
            raise NamespaceError(f"writing uid/gid map: {e}")

    def _apply_runtime_policy(self, libc: Libc) -> None:
        paths = compute_runtime_preservation(
            os.getuid(), extra=self.extra_runtime_binds
        )
        staged = []
        for p in paths:
            try:
                fd = os.open(p, os.O_PATH | os.O_NOFOLLOW)
            except OSError:
                continue
            staged.append((p, fd, os.path.isdir(p)))

        libc.mount("tmpfs", RUN_ROOT, "tmpfs", 0, "mode=0755")
        try:
            for p, fd, is_dir in staged:
                parent = os.path.dirname(p)
                os.makedirs(parent, exist_ok=True)
                if is_dir:
                    os.makedirs(p, exist_ok=True)
                elif not os.path.lexists(p):
                    os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o600))
                libc.mount(f"/proc/self/fd/{fd}", p, None, MS_BIND | MS_REC)
        finally:
            for _, fd, _ in staged:
                os.close(fd)

    def apply(self) -> None:
        """Enter the namespaces and perform all mounts.

        Raises NamespaceError on any failure; callers must not continue into
        a shell if this raises, since the overlay may be partially applied.
        """
        libc = self._libc or Libc()
        for src, dst in self.binds:
            if not os.path.isdir(src):
                raise NamespaceError(f"bind source missing: {src}")
            if not os.path.isdir(dst):
                raise NamespaceError(f"bind target missing: {dst}")

        self._enter_userns(libc)
        libc.unshare(CLONE_NEWNS, "unshare(CLONE_NEWNS)")
        libc.mount(None, "/", None, MS_REC | MS_PRIVATE)

        if self.preserve_runtime:
            self._apply_runtime_policy(libc)

        for src, dst in self.binds:
            libc.mount(src, dst, None, MS_BIND | MS_REC)

        libc.prctl(PR_SET_NO_NEW_PRIVS, 1)


def run_in_overlay(
    overlay: Overlay,
    argv: Sequence[str],
    env: dict,
    cwd: Optional[str] = None,
) -> int:
    """Fork, apply |overlay| in the child, exec |argv|; return exit status.

    The parent stays outside the namespace so repo can finish normally (write
    trace events, etc.).  SIGINT is ignored in the parent while waiting so a
    Ctrl-C reaches only the foreground job inside the workspace, as a shell
    would do.
    """
    import signal

    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            overlay.apply()
            if cwd:
                try:
                    os.chdir(cwd)
                except OSError:
                    os.chdir(os.path.expanduser("~"))
            os.execvpe(argv[0], list(argv), env)
        except NamespaceError as e:
            sys.stderr.write(f"error: workspace overlay failed: {e.args[0]}\n")
            sys.stderr.flush()
            code = 1
        except OSError as e:
            sys.stderr.write(f"error: cannot exec {argv[0]}: {e}\n")
            sys.stderr.flush()
            code = 127
        except Exception as e:  # noqa: B902
            sys.stderr.write(f"error: {e}\n")
            sys.stderr.flush()
            code = 1
        finally:
            os._exit(code)

    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        while True:
            try:
                _, status = os.waitpid(pid, 0)
                break
            except InterruptedError:
                continue
    finally:
        signal.signal(signal.SIGINT, old)

    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)
