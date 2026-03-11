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
import subprocess

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
                try:
                    if mtime != os.path.getmtime(
                        os.path.join(self._gitdir, name)
                    ):
                        return True
                except OSError:
                    return True
            return False

    def _LoadAll(self):
        with Trace(": load refs %s", self._gitdir):
            self._phyref = {}
            self._symref = {}
            self._mtime = {}

            # We track these for caching.
            for name in ("packed-refs", "HEAD", "refs"):
                try:
                    self._mtime[name] = os.path.getmtime(
                        os.path.join(self._gitdir, name)
                    )
                except OSError:
                    pass

            # Physical refs
            try:
                output = subprocess.check_output(
                    ["git", "--git-dir", self._gitdir, "show-ref", "--head"],
                    stderr=subprocess.DEVNULL,
                    encoding="utf-8",
                )
                for line in output.splitlines():
                    if " " in line:
                        sha, name = line.split(" ", 1)
                        self._phyref[name] = sha
            except subprocess.CalledProcessError:
                pass

            # Symbolic refs
            try:
                output = subprocess.check_output(
                    [
                        "git",
                        "--git-dir",
                        self._gitdir,
                        "for-each-ref",
                        "--format=%(refname) %(symref)",
                    ],
                    stderr=subprocess.DEVNULL,
                    encoding="utf-8",
                )
                for line in output.splitlines():
                    if " " in line:
                        name, sym = line.split(" ", 1)
                        if sym:
                            self._symref[name] = sym
            except subprocess.CalledProcessError:
                pass

            # Special case for HEAD symref
            try:
                output = subprocess.check_output(
                    ["git", "--git-dir", self._gitdir, "symbolic-ref", HEAD],
                    stderr=subprocess.DEVNULL,
                    encoding="utf-8",
                )
                self._symref[HEAD] = output.strip()
            except subprocess.CalledProcessError:
                pass
