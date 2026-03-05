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

"""Unittests for the status subcmd."""

import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from typing import List

import git_command
import manifest_xml
import subcmds


class StatusOrphans(unittest.TestCase):
    """Tests for status output."""

    def setUp(self) -> None:
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="status_tests")
        self.topdir = Path(self.tempdirobj.name)
        self.repodir = self.topdir / ".repo"
        self.manifest_dir = self.repodir / "manifests"
        self.manifest_file = self.repodir / manifest_xml.MANIFEST_FILE_NAME

        self.repodir.mkdir()
        self.manifest_dir.mkdir()

        gitdir = self.repodir / "manifests.git"
        gitdir.mkdir()
        (gitdir / "config").write_text(
            """[remote \"origin\"]
                    url = https://localhost:0/manifest
                    verbose = false
                """
        )

        self.initTempGitTree(self.manifest_dir)

    def tearDown(self) -> None:
        self.tempdirobj.cleanup()

    def initTempGitTree(self, git_dir: Path) -> None:
        """Create a new git checkout with an initial commit for testing."""
        cmd = ["git", "init", "-q"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            templatedir = Path(self.tempdirobj.name) / ".test-template"
            if not templatedir.exists():
                templatedir.mkdir()
                (templatedir / "HEAD").write_text("ref: refs/heads/main\n")
            cmd += ["--template", str(templatedir)]
        cmd += [str(git_dir)]
        subprocess.check_call(cmd)

        subprocess.check_call(
            [
                "git",
                "-C",
                str(git_dir),
                "config",
                "user.email",
                "status@test",
            ]
        )
        subprocess.check_call(
            ["git", "-C", str(git_dir), "config", "user.name", "Status Test"]
        )
        (git_dir / "README").write_text("init")
        subprocess.check_call(["git", "-C", str(git_dir), "add", "README"])
        subprocess.check_call(
            ["git", "-C", str(git_dir), "commit", "-q", "-m", "init"]
        )

    def _create_manifest_with_project(
        self, project_inner_xml: str = ""
    ) -> manifest_xml.XmlManifest:
        self.manifest_file.write_text(
            f"""
                <manifest>
                    <remote name="origin" fetch="http://localhost" />
                    <default remote="origin" revision="refs/heads/main" />
                    <project name="proj" path="src/proj">
                        {project_inner_xml}
                    </project>
                </manifest>
            """,
            encoding="utf-8",
        )

        (self.repodir / "projects" / "src" / "proj.git").mkdir(parents=True)
        (self.repodir / "project-objects" / "proj.git").mkdir(parents=True)

        worktree = self.topdir / "src" / "proj"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        self.initTempGitTree(worktree)

        return manifest_xml.XmlManifest(
            str(self.repodir), str(self.manifest_file)
        )

    def _run_status(
        self, manifest: manifest_xml.XmlManifest, argv: List[str]
    ) -> None:
        cmd = subcmds.status.Status()
        cmd.manifest = manifest
        cmd.client = mock.MagicMock(globalConfig=manifest.globalConfig)

        opts, args = cmd.OptionParser.parse_args(argv)
        cmd.CommonValidateOptions(opts, args)
        opts.jobs = 1

        cmd.Execute(opts, args)

    @mock.patch("sys.stdout", new_callable=io.StringIO)
    def test_orphans_basic(self, mock_stdout: io.StringIO) -> None:
        manifest = self._create_manifest_with_project()

        (self.topdir / "src" / "orphan_dir").mkdir(parents=True)
        (self.topdir / "orphan.txt").write_text("data")

        self._run_status(manifest, ["-o"])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertIn("Objects not within a project (orphans)", output)
        self.assertIn(" --\torphan.txt", output)
        self.assertIn("src/orphan_dir/", output)

    @mock.patch("sys.stdout", new_callable=io.StringIO)
    def test_orphans_with_copyfile_and_linkfile(
        self, mock_stdout: io.StringIO
    ) -> None:
        manifest = self._create_manifest_with_project(
            """
            <copyfile src="README" dest="generated/copied.txt" />
            <linkfile src="README" dest="links/README.link" />
            """
        )

        (self.topdir / "src" / "proj" / "README").write_text("source")

        copy_dest = self.topdir / "generated" / "copied.txt"
        copy_dest.parent.mkdir(parents=True, exist_ok=True)
        copy_dest.write_text("copied")

        link_dest = self.topdir / "links" / "README.link"
        link_dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            link_dest.symlink_to(self.topdir / "src" / "proj" / "README")
        except OSError:
            link_dest.write_text("linked")

        (self.topdir / "orphan.txt").write_text("data")

        self._run_status(manifest, ["-o"])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertIn("Objects not within a project (orphans)", output)
        self.assertIn(" --\torphan.txt", output)
        self.assertIn("Objects created by copyfile", output)
        self.assertIn(" --\tgenerated/copied.txt", output)
        self.assertIn("Objects created by linkfile", output)
        self.assertIn(" --\tlinks/README.link", output)
        self.assertNotIn(
            "Objects not within a project (orphans)\n --\tgenerated/copied.txt",
            output,
        )
        self.assertNotIn(
            "Objects not within a project (orphans)\n --\tlinks/README.link",
            output,
        )

    @mock.patch("sys.stdout", new_callable=io.StringIO)
    def test_empty_status_without_orphans(
        self, mock_stdout: io.StringIO
    ) -> None:
        manifest = self._create_manifest_with_project()

        self._run_status(manifest, [])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertNotIn("Objects not within a project (orphans)", output)
        self.assertIn("project src/proj/", output)
        self.assertIn("branch main", output)

    @mock.patch("sys.stdout", new_callable=io.StringIO)
    def test_status_without_orphans(self, mock_stdout: io.StringIO) -> None:
        manifest = self._create_manifest_with_project()

        (self.topdir / "src" / "proj" / "README").write_text("updated")

        self._run_status(manifest, [])

        output = mock_stdout.getvalue().replace(os.sep, "/")
        self.assertNotIn("Objects not within a project (orphans)", output)
        self.assertIn("project src/proj/", output)
        self.assertIn(" -m\tREADME", output)
