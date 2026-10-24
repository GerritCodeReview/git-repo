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
        self._symref[name] = target
        resolved = target
        for _ in range(_SYMREF_MAXDEPTH):
            if resolved in self._phyref:
                self._phyref[name] = self._phyref[resolved]
                break
            next_ref = self._symref.get(resolved)
            if not next_ref:
                self._phyref.pop(name, None)
                break
            resolved = next_ref
        else:
            self._phyref.pop(name, None)
        self._RefreshMtimes()

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
            self._phyref = {}
            self._symref = {}
            self._mtime = {}

            root_refs_loaded = self._ReadRefs()
            if not root_refs_loaded or (
                HEAD not in self._phyref and HEAD not in self._symref
            ):
                # --include-root-refs does not report an unborn HEAD.
                self._ReadSymbolicRef(HEAD)

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

            self._RefreshMtimes()

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
