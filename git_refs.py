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
import stat
from typing import Dict, Optional, Set, Tuple

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
_StatKey = Tuple[int, int, int, int]


def _IsValidRefName(name: str) -> bool:
    """Validate a Git refname per git-check-ref-format rules."""
    if not name or name.endswith(".") or ".." in name or "@{" in name:
        return False
    if any(
        ch in _BAD_REF_CHARS or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name
    ):
        return False
    parts = name.split("/")
    if len(parts) < 2:
        return False
    for part in parts:
        if not part or part.startswith(".") or part.endswith(".lock"):
            return False
    return True


class GitRefs:
    def __init__(self, gitdir):
        self._gitdir = gitdir
        self._phyref: Optional[Dict[str, str]] = None
        self._symref: Optional[Dict[str, str]] = None
        self._mtime: Dict[str, Optional[_StatKey]] = {}
        self._files_authoritative = False

    @property
    def all(self) -> Dict[str, str]:
        self._EnsureLoaded()
        assert self._phyref is not None
        return self._phyref

    @property
    def head(self) -> str:
        """Return HEAD's symbolic target or detached object ID."""
        self._EnsureLoaded()
        assert self._symref is not None and self._phyref is not None
        return self._symref.get(HEAD) or self._phyref.get(HEAD, "")

    @property
    def is_loaded(self) -> bool:
        """Whether a ref snapshot has already been loaded."""
        return self._phyref is not None

    @property
    def is_files_authoritative(self) -> bool:
        """Whether the loaded snapshot came from a complete files scan."""
        return self._phyref is not None and self._files_authoritative

    def Invalidate(self) -> None:
        """Discard any cached ref snapshot so the next access reloads."""
        self._phyref = None
        self._symref = None
        self._mtime = {}
        self._files_authoritative = False

    def get(self, name):
        try:
            return self.all[name]
        except KeyError:
            return ""

    def deleted(self, name):
        if self._phyref is not None:
            if name in self._phyref:
                del self._phyref[name]

            if self._symref is not None and name in self._symref:
                del self._symref[name]

            if name in self._mtime:
                del self._mtime[name]
            norm_os = os.path.join(*name.strip("/").split("/"))
            if norm_os in self._mtime:
                del self._mtime[norm_os]

    def symref(self, name):
        try:
            self._EnsureLoaded()
            assert self._symref is not None
            return self._symref[name]
        except KeyError:
            return ""

    def TryResolveRef(self, name: str) -> Optional[str]:
        """Resolve a single ref directly on the files backend without git.

        Args:
            name: Reference name ("HEAD" or "refs/...").

        Returns:
            The resolved hex object ID if present, "" if the repository uses a
            clean files backend and the ref is authoritatively absent or
            unborn, or None if git must be invoked as a fallback.
        """
        if name != HEAD and (
            not name.startswith("refs/") or not _IsValidRefName(name)
        ):
            return None

        if self._phyref is not None and not self._NeedUpdate():
            if name in self._phyref:
                return self._phyref[name]
            if self._files_authoritative:
                return ""
            return None

        if self._CheckFilesBackendConfig() is None:
            return None
        refs_dir = os.path.join(self._gitdir, "refs")
        if platform_utils.islink(refs_dir) or not os.path.isdir(refs_dir):
            return None
        head_file = os.path.join(self._gitdir, HEAD)
        if platform_utils.islink(head_file) or not os.path.isfile(head_file):
            return None

        cur = name
        for _ in range(_SYMREF_MAXDEPTH + 1):
            parts = cur.split("/")
            for idx in range(1, len(parts) + 1):
                if platform_utils.islink(
                    os.path.join(self._gitdir, *parts[:idx])
                ):
                    return None
            ref_path = os.path.join(self._gitdir, *parts)
            if os.path.lexists(ref_path + ".lock"):
                return None

            if os.path.lexists(ref_path):
                if os.path.isdir(ref_path):
                    return None
                parsed = self._ParseLooseRefFile(ref_path)
                if parsed is None:
                    return None
                is_sym, val, _ = parsed
                if not is_sym:
                    return val
                cur = val
                continue

            if cur == HEAD:
                return None

            packed_path = os.path.join(self._gitdir, "packed-refs")
            if os.path.lexists(packed_path):
                packed_res = self._ReadPackedRefs(packed_path)
                if packed_res is None:
                    return None
                packed_map, _ = packed_res
            else:
                packed_map = {}

            if os.path.lexists(ref_path):
                return None
            return packed_map.get(cur, "")

        return ""

    def UpdateSymref(self, name: str, target: str) -> None:
        """Update a symbolic reference in an already-loaded ref snapshot.

        Args:
            name: Full symbolic reference name (e.g. "refs/remotes/m/main").
            target: Target reference name that the symref points to.
        """
        if self._phyref is None or self._symref is None:
            return
        if self._HasExternalRefChanges(name):
            self.Invalidate()
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
        if self._phyref is None or self._symref is None:
            return
        if self._HasExternalRefChanges(name):
            self.Invalidate()
            return

        parts = name.strip("/").split("/")
        ref_rel = os.path.join(*parts)
        parsed = self._ParseLooseRefFile(os.path.join(self._gitdir, ref_rel))
        if parsed is None or parsed[0]:
            self.Invalidate()
            return

        _, oid, ref_stat = parsed
        self._symref.pop(name, None)
        self._phyref[name] = oid
        self._ResolveSymrefs()

        for idx in range(1, len(parts)):
            self._TrackMtime(os.path.join(*parts[:idx]))
        self._mtime[ref_rel] = ref_stat

    def _HasExternalRefChanges(self, updated_ref: str) -> bool:
        """Check whether refs outside |updated_ref| changed on disk.

        Args:
            updated_ref: Reference path just updated on disk.

        Returns:
            True if files backend is unsafe or any unrelated ref path changed.
        """
        if self._CheckFilesBackendConfig() is None:
            return True
        if "packed-refs" not in self._mtime and os.path.lexists(
            os.path.join(self._gitdir, "packed-refs")
        ):
            return True

        parts = updated_ref.strip("/").split("/")
        expected_child = {
            "/".join(parts[:idx]): parts[idx] for idx in range(1, len(parts))
        }

        for tracked, prev_stat in self._mtime.items():
            norm = tracked.replace(os.sep, "/")
            if norm == updated_ref:
                continue
            full_path = os.path.join(self._gitdir, tracked)
            curr_stat = self._StatPath(full_path)
            if prev_stat is None:
                if curr_stat is not None:
                    return True
                continue
            if curr_stat is None:
                return True
            if norm in expected_child:
                if curr_stat != prev_stat:
                    try:
                        children = platform_utils.listdir(full_path)
                    except OSError:
                        return True
                    next_comp = expected_child[norm]
                    for child in children:
                        if child == next_comp:
                            continue
                        child_key = os.path.join(tracked, child)
                        if self._mtime.get(child_key) is None:
                            return True
            elif curr_stat != prev_stat:
                return True

        for anc, next_comp in expected_child.items():
            anc_os = anc.replace("/", os.sep)
            if self._mtime.get(anc_os) is None:
                anc_full = os.path.join(self._gitdir, anc_os)
                try:
                    if platform_utils.listdir(anc_full) != [next_comp]:
                        return True
                except OSError:
                    return True
        return False

    def _ResolveSymrefs(self) -> None:
        """Resolve all symbolic references into _phyref up to max depth."""
        assert self._symref is not None and self._phyref is not None
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

    def _NeedUpdate(self) -> bool:
        with repo_trace.Trace(": scan refs %s", self._gitdir):
            for name, prev_stat in self._mtime.items():
                if (
                    self._StatPath(os.path.join(self._gitdir, name))
                    != prev_stat
                ):
                    return True
            return False

    def _LoadAll(self):
        with repo_trace.Trace(": load refs %s", self._gitdir):
            if self._TryReadFilesBackend():
                self._ResolveSymrefs()
                return

            self._files_authoritative = False
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

    def _CheckFilesBackendConfig(self) -> Optional[_StatKey]:
        """Verify standard files ref backend preconditions and stat config."""
        if "GIT_DIR" in os.environ or "GIT_COMMON_DIR" in os.environ:
            return None
        if not os.path.isdir(self._gitdir):
            return None
        for special in ("reftable", "commondir"):
            if os.path.lexists(os.path.join(self._gitdir, special)):
                return None

        cfg_path = os.path.join(self._gitdir, "config")
        if platform_utils.islink(cfg_path):
            return None
        try:
            with open(cfg_path, "rb") as cfg_fd:
                if b"refstorage" in cfg_fd.read().lower():
                    return None
                return self._FormatStat(os.fstat(cfg_fd.fileno()))
        except OSError:
            return None

    @classmethod
    def _ParseLooseRefFile(
        cls, path: str
    ) -> Optional[Tuple[bool, str, _StatKey]]:
        """Parse a loose ref or HEAD file into (is_symref, val, stat)."""
        if platform_utils.islink(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fd:
                raw = fd.read(1024)
                st = cls._FormatStat(os.fstat(fd.fileno()))
        except (OSError, UnicodeDecodeError):
            return None

        line = raw.rstrip("\r\n")
        if not line or "\n" in line or "\r" in line:
            return None
        if line.startswith("ref:"):
            target = line[4:].strip()
            if not target or target == R_HEADS + ".invalid":
                return None
            if target != HEAD and (
                not target.startswith("refs/") or not _IsValidRefName(target)
            ):
                return None
            return (True, target, st)

        oid = line.strip()
        if not _HEX_OID_RE.match(oid) or cls._IsNullRef(oid):
            return None
        return (False, oid, st)

    @classmethod
    def _ReadPackedRefs(
        cls, packed_path: str
    ) -> Optional[Tuple[Dict[str, str], _StatKey]]:
        """Parse a packed-refs file into (ref_map, stat)."""
        if platform_utils.islink(packed_path):
            return None
        packed: Dict[str, str] = {}
        try:
            with open(packed_path, "r", encoding="utf-8") as packed_fd:
                for raw_line in packed_fd:
                    if raw_line.startswith("#"):
                        continue
                    line = raw_line.rstrip("\r\n")
                    if line.startswith("^"):
                        if not _HEX_OID_RE.match(line[1:]):
                            return None
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) != 2:
                        return None
                    oid, ref_name = parts
                    if (
                        not _HEX_OID_RE.match(oid)
                        or cls._IsNullRef(oid)
                        or not ref_name.startswith("refs/")
                        or not _IsValidRefName(ref_name)
                    ):
                        return None
                    packed[ref_name] = oid
                st = cls._FormatStat(os.fstat(packed_fd.fileno()))
        except (OSError, UnicodeDecodeError):
            return None
        return (packed, st)

    def _TryReadFilesBackend(self) -> bool:
        """Load HEAD, packed-refs, and loose refs directly when safe.

        Returns:
            True if the repository uses a standard files ref backend and all
            refs and stat fingerprints were read cleanly without invoking git.
        """
        cfg_stat = self._CheckFilesBackendConfig()
        if cfg_stat is None:
            return False

        mtime: Dict[str, Optional[_StatKey]] = {
            "config": cfg_stat,
            "reftable": None,
        }
        phyref: Dict[str, str] = {}
        symref: Dict[str, str] = {}

        parsed_head = self._ParseLooseRefFile(os.path.join(self._gitdir, HEAD))
        if parsed_head is None:
            return False
        head_is_sym, head_val, head_stat = parsed_head
        mtime[HEAD] = head_stat
        if head_is_sym:
            symref[HEAD] = head_val
        else:
            phyref[HEAD] = head_val

        packed_path = os.path.join(self._gitdir, "packed-refs")
        packed_stat: Optional[_StatKey] = None
        if os.path.lexists(packed_path):
            packed_res = self._ReadPackedRefs(packed_path)
            if packed_res is None:
                return False
            packed_map, packed_stat = packed_res
            phyref.update(packed_map)
        mtime["packed-refs"] = packed_stat

        refs_dir = os.path.join(self._gitdir, "refs")
        if platform_utils.islink(refs_dir):
            return False
        refs_stat = self._StatPath(refs_dir)
        if refs_stat is None or not stat.S_ISDIR(refs_stat[0]):
            return False
        mtime["refs"] = refs_stat

        try:
            to_scan = [("refs", "refs", refs_dir)]
            while to_scan:
                ref_prefix, rel_os_prefix, abs_dir = to_scan.pop()
                with os.scandir(abs_dir) as entries:
                    for entry in entries:
                        if entry.is_symlink():
                            return False
                        ref_name = f"{ref_prefix}/{entry.name}"
                        if not _IsValidRefName(ref_name):
                            return False
                        rel_os = os.path.join(rel_os_prefix, entry.name)
                        if entry.is_dir(follow_symlinks=False):
                            if ref_name in phyref:
                                return False
                            # DirEntry.stat() leaves st_ino == 0 on Windows,
                            # whereas _StatPath() uses os.lstat() and populates
                            # st_ino. Stat via _StatPath() so _NeedUpdate() and
                            # _HasExternalRefChanges() compare matching keys.
                            d_stat = self._StatPath(entry.path)
                            if d_stat is None or not stat.S_ISDIR(d_stat[0]):
                                return False
                            mtime[rel_os] = d_stat
                            to_scan.append((ref_name, rel_os, entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            parsed = self._ParseLooseRefFile(entry.path)
                            if parsed is None:
                                return False
                            is_sym, val, f_stat = parsed
                            mtime[rel_os] = f_stat
                            if is_sym:
                                phyref.pop(ref_name, None)
                                symref[ref_name] = val
                            else:
                                symref.pop(ref_name, None)
                                phyref[ref_name] = val
                        else:
                            return False
        except OSError:
            return False

        # Guard against a concurrent `git pack-refs --prune` writing
        # packed-refs and unlinking loose refs mid-scan.
        if self._StatPath(packed_path) != packed_stat:
            return False

        self._phyref = phyref
        self._symref = symref
        self._mtime = mtime
        self._files_authoritative = True
        return True

    def _RefreshMtimes(self) -> None:
        """Record current modification times for ref storage paths."""
        self._mtime = {}
        self._TrackMtime(HEAD, track_missing=True)
        self._TrackMtime("config", track_missing=True)
        self._TrackMtime("packed-refs", track_missing=True)
        self._TrackMtime("refs", track_missing=True)
        self._TrackMtime("reftable", track_missing=True)
        self._TrackTreeMtimes("refs")
        self._TrackTreeMtimes("reftable")

    @staticmethod
    def _FormatStat(st: os.stat_result) -> _StatKey:
        # ctime is left out: tools that only touch metadata, such as backup
        # agents and file system crawlers, move it without changing a ref.
        return (st.st_mode, st.st_mtime_ns, st.st_size, st.st_ino)

    @classmethod
    def _StatPath(cls, path: str) -> Optional[_StatKey]:
        try:
            st = os.lstat(path)
        except OSError:
            return None
        mount_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
        is_reparse_dir = getattr(st, "st_reparse_tag", 0) == mount_tag
        if stat.S_ISLNK(st.st_mode) or is_reparse_dir:
            # Track the symlink target so mutations to symlinked refs or
            # packed-refs invalidate the fallback snapshot, while keeping
            # S_IFLNK in mode and negative size when dangling.
            link_mode = stat.S_IFLNK | stat.S_IMODE(st.st_mode)
            try:
                target_st = os.stat(path)
            except OSError:
                return (link_mode, st.st_mtime_ns, -1 - st.st_size, st.st_ino)
            return (
                link_mode,
                target_st.st_mtime_ns,
                target_st.st_size,
                target_st.st_ino,
            )
        return cls._FormatStat(st)

    @staticmethod
    def _IsNullRef(ref_id: str) -> bool:
        """Check if a ref_id is a null object ID."""
        return bool(ref_id) and all(ch == "0" for ch in ref_id)

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

        assert self._symref is not None and self._phyref is not None
        for line in p.stdout.splitlines():
            ref_id, name, symref = line.split("\0")
            if symref:
                self._symref[name] = symref
            elif ref_id and not self._IsNullRef(ref_id):
                self._phyref[name] = ref_id
        return include_root_refs

    def _ReadSymbolicRef(self, name: str) -> None:
        """Read a symbolic reference."""
        assert self._symref is not None and self._phyref is not None
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

    def _TrackMtime(self, name: str, track_missing: bool = False) -> None:
        """Track the stat fingerprint of a specific gitdir path."""
        st = self._StatPath(os.path.join(self._gitdir, name))
        if st is not None or track_missing:
            self._mtime[name] = st

    def _TrackTreeMtimes(self, root: str) -> None:
        """Recursively track modification times for a directory tree."""
        root_path = os.path.join(self._gitdir, root)
        try:
            if not platform_utils.isdir(root_path):
                self._TrackMtime(root)
                return
        except OSError:
            return

        visited: Set[Tuple[int, int]] = set()
        to_scan = [root]
        while to_scan:
            name = to_scan.pop()
            self._TrackMtime(name)
            path = os.path.join(self._gitdir, name)
            try:
                dir_st = os.stat(path)
            except OSError:
                continue
            if not stat.S_ISDIR(dir_st.st_mode):
                continue
            if dir_st.st_ino:
                dir_key = (dir_st.st_dev, dir_st.st_ino)
                if dir_key in visited:
                    continue
                visited.add(dir_key)

            try:
                children = platform_utils.listdir(path)
            except OSError:
                continue
            for child in children:
                child_name = os.path.join(name, child)
                child_path = os.path.join(self._gitdir, child_name)
                if platform_utils.isdir(child_path):
                    to_scan.append(child_name)
                else:
                    self._TrackMtime(child_name)
