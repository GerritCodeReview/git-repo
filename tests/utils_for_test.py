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

"""Various utility code used by tests.

If you want to write a per-test fixture, see conftest.py instead.
"""

import contextlib
import functools
from pathlib import Path
import subprocess
import tempfile
from typing import List, Optional, Tuple, Union

import git_command
import manifest_xml


THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent
FIXTURES_DIR = THIS_DIR / "fixtures"


def init_git_tree(
    path: Union[str, Path],
    ref_format: Optional[str] = None,
) -> None:
    """Initialize `path` as a new git repo."""
    with contextlib.ExitStack() as stack:
        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git"]
        if ref_format:
            cmd += ["-c", f"init.defaultRefFormat={ref_format}"]
        cmd += ["init"]

        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init.
            templatedir = stack.enter_context(
                tempfile.mkdtemp(prefix="git-template")
            )
            (Path(templatedir) / "HEAD").write_text("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        cmd += [path]
        subprocess.run(cmd, check=True)


class RepoClientCheckout:
    """Shared helper for constructing a test repo client checkout."""

    def __init__(self, topdir: Path):
        self.topdir = Path(topdir)
        self.repodir = self.topdir / ".repo"
        self.manifest_dir = self.repodir / "manifests"
        self.manifest_file = self.repodir / manifest_xml.MANIFEST_FILE_NAME
        self.local_manifest_dir = (
            self.repodir / manifest_xml.LOCAL_MANIFESTS_DIR_NAME
        )

        self.repodir.mkdir(parents=True, exist_ok=True)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

    def init_manifest_git(
        self, remote_url: str = "https://localhost:0/manifest"
    ) -> None:
        """Create `.repo/manifests.git/config` with a fake origin remote."""
        gitdir = self.repodir / "manifests.git"
        gitdir.mkdir(parents=True, exist_ok=True)
        (gitdir / "config").write_text(
            f"""[remote "origin"]
    url = {remote_url}
    verbose = false
""",
            encoding="utf-8",
        )

    def write_manifest(self, xml: str) -> None:
        """Write XML data to `.repo/manifest.xml`."""
        self.manifest_file.write_text(xml, encoding="utf-8")

    def xml_manifest(self) -> manifest_xml.XmlManifest:
        """Parse and return the manifest from this test checkout."""
        return manifest_xml.XmlManifest(
            str(self.repodir), str(self.manifest_file)
        )

    def create_project(
        self,
        *,
        name: str,
        path: str,
        init_worktree: bool = True,
    ) -> Path:
        """Create manifest project dirs and optionally init a git worktree."""
        (self.repodir / "projects" / f"{path}.git").mkdir(
            parents=True, exist_ok=True
        )
        (self.repodir / "project-objects" / f"{name}.git").mkdir(
            parents=True, exist_ok=True
        )
        worktree = self.topdir / path
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if init_worktree:
            init_git_tree(worktree)
        return worktree

    def create_projects(self, projects: List[Tuple[str, str]]) -> List[Path]:
        """Bulk-create multiple projects."""
        return [
            self.create_project(name=name, path=path) for name, path in projects
        ]


@contextlib.contextmanager
def TempGitTree():
    """Create a new empty git checkout for testing."""
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        init_git_tree(tempdir)
        yield tempdir


@functools.lru_cache(maxsize=None)
def supports_reftable() -> bool:
    """Check if git supports reftable."""
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        proc = subprocess.run(
            ["git", "-c", "init.defaultRefFormat=reftable", "init"],
            cwd=tempdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    return proc.returncode == 0


@functools.lru_cache(maxsize=None)
def supports_refs_migrate() -> bool:
    """Check if git supports refs migrate."""
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        subprocess.check_call(
            ["git", "-c", "init.defaultRefFormat=files", "init"],
            cwd=tempdir,
        )
        proc = subprocess.run(
            [
                "git",
                "refs",
                "migrate",
                "--ref-format=reftable",
                "--dry-run",
            ],
            cwd=tempdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    return proc.returncode == 0
