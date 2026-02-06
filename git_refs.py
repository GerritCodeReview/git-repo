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

from git_command import GitCommand
import platform_utils
from repo_trace import Trace


HEAD = "HEAD"
R_CHANGES = "refs/changes/"
R_HEADS = "refs/heads/"
R_TAGS = "refs/tags/"
R_PUB = "refs/published/"
R_WORKTREE = "refs/worktree/"
R_WORKTREE_M = R_WORKTREE + "m/"
R_M = "refs/remotes/m/"


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

    def _EnsureLoaded(self):
        if self._phyref is None or self._NeedUpdate():
            self._LoadAll()

    def _NeedUpdate(self):
        with Trace(": scan refs %s", self._gitdir):
            for name, mtime in self._mtime.items():
                if name:
                    path = os.path.join(self._gitdir, name)
                else:
                    path = self._gitdir
                try:
                    if mtime != os.path.getmtime(path):
                        return True
                except OSError:
                    return True
            return False

    def _LoadAll(self):
        with Trace(": load refs %s", self._gitdir):
            self._phyref = {}
            self._symref = {}
            self._mtime = {}

            self._ReadRefs()
            self._ReadHead()

            scan = self._symref
            attempts = 0
            while scan and attempts < 5:
                scan_next = {}
                for name, dest in scan.items():
                    if dest in self._phyref:
                        self._phyref[name] = self._phyref[dest]
                    else:
                        scan_next[name] = dest
                scan = scan_next
                attempts += 1

            self._TrackMtime(HEAD)
            self._TrackMtime("config")
            self._TrackMtime("packed-refs")
            self._TrackTreeMtimes("refs")
            self._TrackTreeMtimes("reftable")

    @staticmethod
    def _IsNullRef(ref_id: str) -> bool:
        """Check if a ref_id is a null object ID."""
        return ref_id and all(ch == "0" for ch in ref_id)

    def _ReadRefs(self) -> None:
        """Read all references using git for-each-ref."""
        p = GitCommand(
            None,
            ["for-each-ref", "--format=%(objectname)\t%(refname)\t%(symref)"],
            capture_stdout=True,
            capture_stderr=True,
            bare=True,
            gitdir=self._gitdir,
        )
        if p.Wait() != 0:
            return

        for line in p.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue

            ref_id, name = fields[:2]
            symref = fields[2] if len(fields) > 2 else ""
            if symref:
                self._symref[name] = symref
            elif ref_id and not self._IsNullRef(ref_id):
                self._phyref[name] = ref_id

    def _ReadHead(self) -> None:
        """Read the HEAD reference."""
        p = GitCommand(
            None,
            ["symbolic-ref", "-q", HEAD],
            capture_stdout=True,
            capture_stderr=True,
            bare=True,
            gitdir=self._gitdir,
        )
        if p.Wait() == 0:
            ref = p.stdout.strip()
            if ref:
                self._symref[HEAD] = ref
                return

        p = GitCommand(
            None,
            ["rev-parse", "--verify", "-q", HEAD],
            capture_stdout=True,
            capture_stderr=True,
            bare=True,
            gitdir=self._gitdir,
        )
        if p.Wait() == 0:
            ref_id = p.stdout.strip()
            if ref_id:
                self._phyref[HEAD] = ref_id

    def _TrackMtime(self, name: str) -> None:
        """Track the modification time of a specific gitdir path."""
        if name:
            path = os.path.join(self._gitdir, name)
        else:
            path = self._gitdir
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
