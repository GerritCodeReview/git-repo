# Copyright (C) 2021 The Android Open Source Project
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

"""Helper tool for generating manual page for all repo commands.

Most code lives in this module so it can be unittested.
"""

import argparse
import functools
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import List


THIS_FILE = Path(__file__).resolve()
TOPDIR = THIS_FILE.parent.parent
MANDIR = TOPDIR.joinpath("man")

# Load repo local modules.
sys.path.insert(0, str(TOPDIR))
from git_command import RepoSourceVersion
import subcmds


def worker(cmd, **kwargs):
    subprocess.run(cmd, **kwargs)


def get_parser() -> argparse.ArgumentParser:
    """Get argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-n",
        "--check",
        "--dry-run",
        action="store_const",
        const=True,
        help="Check if changes are necessary; don't actually change files",
    )
    return parser


def main(argv: List[str]) -> int:
    parser = get_parser()
    opts = parser.parse_args(argv)

    if not shutil.which("help2man"):
        sys.exit("Please install help2man to continue.")

    # Let repo know we're generating man pages so it can avoid some dynamic
    # behavior (like probing active number of CPUs).  We use a weird name &
    # value to make it less likely for users to set this var themselves.
    os.environ["_REPO_GENERATE_MANPAGES_"] = " indeed! "

    # "repo branch" is an alias for "repo branches".
    del subcmds.all_commands["branch"]
    (MANDIR / "repo-branch.1").write_text(".so man1/repo-branches.1")

    version = RepoSourceVersion()
    cmdlist = [
        [
            "help2man",
            "-N",
            "-n",
            f"repo {cmd} - manual page for repo {cmd}",
            "-S",
            f"repo {cmd}",
            "-m",
            "Repo Manual",
            f"--version-string={version}",
            "-o",
            MANDIR.joinpath(f"repo-{cmd}.1.tmp"),
            "./repo",
            "-h",
            f"help {cmd}",
        ]
        for cmd in subcmds.all_commands
    ]
    cmdlist.append(
        [
            "help2man",
            "-N",
            "-n",
            "repository management tool built on top of git",
            "-S",
            "repo",
            "-m",
            "Repo Manual",
            f"--version-string={version}",
            "-o",
            MANDIR.joinpath("repo.1.tmp"),
            "./repo",
            "-h",
            "--help-all",
        ]
    )

    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        repo_dir = tempdir / ".repo"
        repo_dir.mkdir()
        (repo_dir / "repo").symlink_to(TOPDIR)

        # Create a repo wrapper using the active Python executable.  We can't
        # pass this directly to help2man as it's too simple, so insert it via
        # shebang.
        data = (TOPDIR / "repo").read_text(encoding="utf-8")
        tempbin = tempdir / "repo"
        tempbin.write_text(f"#!{sys.executable}\n" + data, encoding="utf-8")
        tempbin.chmod(0o755)

        # Run all cmd in parallel, and wait for them to finish.
        with multiprocessing.Pool() as pool:
            pool.map(
                functools.partial(worker, cwd=tempdir, check=True), cmdlist
            )

    ret = 0
    for tmp_path in MANDIR.glob("*.1.tmp"):
        path = tmp_path.parent / tmp_path.stem
        old_data = path.read_text() if path.exists() else ""

        data = tmp_path.read_text()
        tmp_path.unlink()

        data = replace_regex(data)

        # If the only thing that changed was the date, don't refresh.  This
        # avoids a lot of noise when only one file actually updates.
        old_data = re.sub(
            r'^(\.TH REPO "1" ")([^"]+)', r"\1", old_data, flags=re.M
        )
        new_data = re.sub(r'^(\.TH REPO "1" ")([^"]+)', r"\1", data, flags=re.M)
        if old_data != new_data:
            if opts.check:
                ret = 1
                print(
                    f"{THIS_FILE.name}: {path.name}: "
                    "man page needs regenerating",
                    file=sys.stderr,
                )
            else:
                path.write_text(data)

    return ret


def replace_regex(data):
    """Replace semantically null regexes in the data.

    Args:
        data: manpage text.

    Returns:
        Updated manpage text.
    """
    regex = (
        (r"(It was generated by help2man) [0-9.]+", r"\g<1>."),
        (r"^\033\[[0-9;]*m([^\033]*)\033\[m", r"\g<1>"),
        (r"^\.IP\n(.*:)\n", r".SS \g<1>\n"),
        (r"^\.PP\nDescription", r".SH DETAILS"),
    )
    for pattern, replacement in regex:
        data = re.sub(pattern, replacement, data, flags=re.M)
    return data
