# Copyright (C) 2009 The Android Open Source Project
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
import re
from typing import Dict

import git_command
import platform_utils
import repo_trace


HEAD = "HEAD"
R_CHANGES = "refs/changes/"
R_HEADS = "refs/heads/"
R_TAGS = "refs/tags/"
R_PUB = "refs/published/"
R_WORKTREE = "refs/worktree/"
R_WORKTREE_M = R_WORKTREE + "m/"
R_M = "refs/remotes/m/"
# Maximum symbolic-ref indirection depth (matches Git SYMREF_MAXDEPTH).
_SYMREF_MAXDEPTH = 5
_HEX_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_BAD_REF_CHARS = frozenset(" ~^:?*[\\")


def _IsValidRefName(name: str) -> bool:
    """Validate a Git refname under refs/ per git-check-ref-format rules."""
    if not name or ".." in name or "@{" in name:
        return False
    if any(
        ch in _BAD_REF_CHARS or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name
    ):
        return False
    parts = name.split("/")
    if len(parts) < 2:
        return False
    for part in parts:
        if (
            not part
            or part.startswith(".")
            or part.endswith(".")
            or part.endswith(".lock")
        ):
            return False
    return True


class GitRefs:
    def __init__(self, gitdir):
        self._gitdir = gitdir
        self._phyref = None
        self._symref = None
        self._mtime = {}

    @property
    def all(self):
        self._EnsureLoaded()
        return self._phyref

    @property
    def head(self) -> str:
        """Return HEAD's symbolic target or detached object ID."""
        self._EnsureLoaded()
        return self._symref.get(HEAD) or self._phyref.get(HEAD, "")

    @property
    def is_loaded(self) -> bool:
        """Whether a ref snapshot has already been loaded."""
        return self._phyref is not None

    def get(self, name):
        try:
            return self.all[name]
        except KeyError:
            return ""

    def deleted(self, name):
        if self._phyref is not None:
            if name in self._phyref:
                del self._phyref[name]

            if name in self._symref:
                del self._symref[name]

            if name in self._mtime:
                del self._mtime[name]

    def symref(self, name):
        try:
            self._EnsureLoaded()
            return self._symref[name]
        except KeyError:
            return ""

    def UpdateSymref(self, name: str, target: str) -> None:
        """Update a symbolic reference in an already-loaded ref snapshot.

        Args:
            name: Full symbolic reference name (e.g. "refs/remotes/m/main").
            target: Target reference name that the symref points to.
        """
        if self._phyref is None:
            return
        if self._HasExternalRefChanges(name):
            self._phyref = None
            return

        self._symref[name] = target
        self._ResolveSymrefs()

        parts = name.strip("/").split("/")
        for idx in range(1, len(parts)):
            anc = os.path.join(*parts[:idx])
            self._TrackMtime(anc)
        self._TrackMtime(os.path.join(*parts))

    def UpdateRef(self, name: str) -> None:
        """Refresh a direct reference in an already-loaded ref snapshot.

        Args:
            name: Full reference name just updated on disk (e.g.
                "refs/remotes/m/main").
        """
        if self._phyref is None:
            return
        if self._HasExternalRefChanges(name):
            self._phyref = None
            return

        parts = name.strip("/").split("/")
        ref_rel = os.path.join(*parts)
        ref_path = os.path.join(self._gitdir, ref_rel)
        try:
            if platform_utils.islink(ref_path):
                self._phyref = None
                return
            with open(ref_path, "r", encoding="utf-8") as fd:
                oid = fd.readline().strip()
        except OSError:
            self._phyref = None
            return

        if not _HEX_OID_RE.match(oid) or self._IsNullRef(oid):
            self._phyref = None
            return

        self._symref.pop(name, None)
        self._phyref[name] = oid
        self._ResolveSymrefs()

        for idx in range(1, len(parts)):
            anc = os.path.join(*parts[:idx])
            self._TrackMtime(anc)
        self._TrackMtime(ref_rel)

    def _HasExternalRefChanges(self, updated_symref: str) -> bool:
        """Check whether refs outside |updated_symref| changed on disk.

        Args:
            updated_symref: Symbolic ref path just updated on disk.

        Returns:
            True if reftable is in use or any unrelated ref path changed.
        """
        if os.path.exists(os.path.join(self._gitdir, "reftable")):
            return True
        if "packed-refs" not in self._mtime and os.path.exists(
            os.path.join(self._gitdir, "packed-refs")
        ):
            return True

        parts = updated_symref.strip("/").split("/")
        expected_child = {
            "/".join(parts[:idx]): parts[idx] for idx in range(1, len(parts))
        }

        for tracked, mtime in self._mtime.items():
            norm = tracked.replace(os.sep, "/")
            if norm == updated_symref:
                continue
            full_path = os.path.join(self._gitdir, tracked)
            try:
                curr_mtime = os.path.getmtime(full_path)
            except OSError:
                return True
            if norm in expected_child:
                if curr_mtime != mtime:
                    try:
                        children = platform_utils.listdir(full_path)
                    except OSError:
                        return True
                    next_comp = expected_child[norm]
                    for child in children:
                        if child == next_comp:
                            continue
                        if os.path.join(tracked, child) not in self._mtime:
                            return True
            elif curr_mtime != mtime:
                return True

        for anc, next_comp in expected_child.items():
            anc_os = anc.replace("/", os.sep)
            if anc_os not in self._mtime:
                anc_full = os.path.join(self._gitdir, anc_os)
                try:
                    if platform_utils.listdir(anc_full) != [next_comp]:
                        return True
                except OSError:
                    return True
        return False

    def _ResolveSymrefs(self) -> None:
        """Resolve all symbolic references into _phyref up to max depth."""
        for name in self._symref:
            self._phyref.pop(name, None)

        scan = self._symref
        attempts = 0
        while scan and attempts < _SYMREF_MAXDEPTH:
            scan_next = {}
            for name, dest in scan.items():
                if dest in self._phyref:
                    self._phyref[name] = self._phyref[dest]
                else:
                    scan_next[name] = dest
            scan = scan_next
            attempts += 1

    def _EnsureLoaded(self):
        if self._phyref is None or self._NeedUpdate():
            self._LoadAll()

    def _NeedUpdate(self):
        with repo_trace.Trace(": scan refs %s", self._gitdir):
            for name, mtime in self._mtime.items():
                try:
                    if mtime != os.path.getmtime(
                        os.path.join(self._gitdir, name)
                    ):
                        return True
                except OSError:
                    return True
            return False

    def _LoadAll(self):
        with repo_trace.Trace(": load refs %s", self._gitdir):
            if not self._TryReadFilesBackend():
                self._phyref = {}
                self._symref = {}
                self._mtime = {}

                root_refs_loaded = self._ReadRefs()
                if not root_refs_loaded or (
                    HEAD not in self._phyref and HEAD not in self._symref
                ):
                    # --include-root-refs does not report an unborn HEAD.
                    self._ReadSymbolicRef(HEAD)

            self._ResolveSymrefs()
            self._RefreshMtimes()

    def _TryReadFilesBackend(self) -> bool:
        """Load HEAD, packed-refs, and loose refs directly when safe.

        Returns:
            True if the repository uses a standard files ref backend and all
            refs were read cleanly without invoking git; False to fall back.
        """
        if "GIT_DIR" in os.environ or "GIT_COMMON_DIR" in os.environ:
            return False
        if not os.path.isdir(self._gitdir):
            return False
        for special in ("reftable", "commondir"):
            if os.path.lexists(os.path.join(self._gitdir, special)):
                return False

        phyref: Dict[str, str] = {}
        symref: Dict[str, str] = {}
        try:
            cfg_path = os.path.join(self._gitdir, "config")
            if platform_utils.islink(cfg_path):
                return False
            with open(cfg_path, "rb") as cfg_fd:
                if b"refstorage" in cfg_fd.read().lower():
                    return False

            head_path = os.path.join(self._gitdir, HEAD)
            if platform_utils.islink(head_path):
                return False
            with open(head_path, "r", encoding="utf-8") as head_fd:
                head_line = head_fd.read(1024).rstrip("\r\n")
            if "\n" in head_line or "\r" in head_line:
                return False
            if head_line.startswith("ref:"):
                target = head_line[4:].strip()
                if (
                    not target
                    or target == R_HEADS + ".invalid"
                    or (target != HEAD and not _IsValidRefName(target))
                ):
                    return False
                symref[HEAD] = target
            else:
                oid = head_line.strip()
                if not _HEX_OID_RE.match(oid) or self._IsNullRef(oid):
                    return False
                phyref[HEAD] = oid

            packed_path = os.path.join(self._gitdir, "packed-refs")
            if os.path.lexists(packed_path):
                if platform_utils.islink(packed_path):
                    return False
                with open(packed_path, "r", encoding="utf-8") as packed_fd:
                    for raw_line in packed_fd:
                        if raw_line.startswith("#"):
                            continue
                        line = raw_line.rstrip("\r\n")
                        if line.startswith("^"):
                            if not _HEX_OID_RE.match(line[1:]):
                                return False
                            continue
                        parts = line.split(" ", 1)
                        if len(parts) != 2:
                            return False
                        oid, ref_name = parts
                        if (
                            not _HEX_OID_RE.match(oid)
                            or self._IsNullRef(oid)
                            or not ref_name.startswith("refs/")
                            or not _IsValidRefName(ref_name)
                        ):
                            return False
                        phyref[ref_name] = oid

            refs_dir = os.path.join(self._gitdir, "refs")
            if platform_utils.islink(refs_dir) or not os.path.isdir(refs_dir):
                return False
            to_scan = [("refs", refs_dir)]
            while to_scan:
                rel_prefix, abs_dir = to_scan.pop()
                with os.scandir(abs_dir) as entries:
                    for entry in entries:
                        if entry.is_symlink():
                            return False
                        ref_name = f"{rel_prefix}/{entry.name}"
                        if not _IsValidRefName(ref_name):
                            return False
                        if entry.is_dir(follow_symlinks=False):
                            if ref_name in phyref:
                                return False
                            to_scan.append((ref_name, entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            with open(
                                entry.path, "r", encoding="utf-8"
                            ) as ref_fd:
                                ref_line = ref_fd.read(1024).rstrip("\r\n")
                            if "\n" in ref_line or "\r" in ref_line:
                                return False
                            if ref_line.startswith("ref:"):
                                target = ref_line[4:].strip()
                                if (
                                    not target
                                    or target == R_HEADS + ".invalid"
                                    or (
                                        target != HEAD
                                        and not _IsValidRefName(target)
                                    )
                                ):
                                    return False
                                phyref.pop(ref_name, None)
                                symref[ref_name] = target
                            else:
                                oid = ref_line.strip()
                                if not _HEX_OID_RE.match(
                                    oid
                                ) or self._IsNullRef(oid):
                                    return False
                                symref.pop(ref_name, None)
                                phyref[ref_name] = oid
                        else:
                            return False
        except (OSError, UnicodeDecodeError):
            return False

        self._phyref = phyref
        self._symref = symref
        self._mtime = {}
        return True

    def _RefreshMtimes(self) -> None:
        """Record current modification times for ref storage paths."""
        self._mtime = {}
        self._TrackMtime(HEAD)
        self._TrackMtime("config")
        self._TrackMtime("packed-refs")
        self._TrackTreeMtimes("refs")
        self._TrackTreeMtimes("reftable")

    @staticmethod
    def _IsNullRef(ref_id: str) -> bool:
        """Check if a ref_id is a null object ID."""
        return ref_id and all(ch == "0" for ch in ref_id)

    def _ReadRefs(self) -> bool:
        """Read all references using git for-each-ref.

        Returns:
            Whether root refs, including HEAD when it exists, were loaded.
        """
        include_root_refs = git_command.git_require((2, 45, 0))
        cmd = [
            "for-each-ref",
            "--format=%(objectname)%00%(refname)%00%(symref)",
        ]
        if include_root_refs:
            cmd.insert(1, "--include-root-refs")
            # Avoid caching volatile root refs such as ORIG_HEAD.  HEAD and
            # refs/* are the only namespaces GitRefs exposes to callers.
            cmd.extend([HEAD, "refs"])
        p = git_command.GitCommand(
            None,
            cmd,
            capture_stdout=True,
            capture_stderr=True,
            bare=True,
            gitdir=self._gitdir,
        )
        if p.Wait() != 0:
            return False

        for line in p.stdout.splitlines():
            ref_id, name, symref = line.split("\0")
            if symref:
                self._symref[name] = symref
            elif ref_id and not self._IsNullRef(ref_id):
                self._phyref[name] = ref_id
        return include_root_refs

    def _ReadSymbolicRef(self, name: str) -> None:
        """Read a symbolic reference."""
        if name == HEAD:
            path = os.path.join(self._gitdir, HEAD)
            try:
                if not platform_utils.islink(path):
                    with open(
                        path, "r", encoding="utf-8", errors="replace"
                    ) as fd:
                        line = fd.readline().strip()
                    if line.startswith("ref:"):
                        ref = line[4:].strip()
                        if ref and ref != R_HEADS + ".invalid":
                            self._symref[name] = ref
                            return
            except OSError:
                pass

        p = git_command.GitCommand(
            None,
            ["symbolic-ref", "-q", name],
            capture_stdout=True,
            capture_stderr=True,
            bare=True,
            gitdir=self._gitdir,
        )
        if p.Wait() == 0:
            ref = p.stdout.strip()
            if ref:
                self._symref[name] = ref
                return

        p = git_command.GitCommand(
            None,
            ["rev-parse", "--verify", "-q", name],
            capture_stdout=True,
            capture_stderr=True,
            bare=True,
            gitdir=self._gitdir,
        )
        if p.Wait() == 0:
            ref_id = p.stdout.strip()
            if ref_id:
                self._phyref[name] = ref_id

    def _TrackMtime(self, name: str) -> None:
        """Track the modification time of a specific gitdir path."""
        path = os.path.join(self._gitdir, name)
        try:
            self._mtime[name] = os.path.getmtime(path)
        except OSError:
            return

    def _TrackTreeMtimes(self, root: str) -> None:
        """Recursively track modification times for a directory tree."""
        root_path = os.path.join(self._gitdir, root)
        try:
            if not platform_utils.isdir(root_path):
                return
        except OSError:
            return

        to_scan = [root]
        while to_scan:
            name = to_scan.pop()
            self._TrackMtime(name)
            path = os.path.join(self._gitdir, name)
            if not platform_utils.isdir(path):
                continue

            for child in platform_utils.listdir(path):
                child_name = os.path.join(name, child)
                child_path = os.path.join(self._gitdir, child_name)
                if platform_utils.isdir(child_path):
                    to_scan.append(child_name)
                else:
                    self._TrackMtime(child_name)
