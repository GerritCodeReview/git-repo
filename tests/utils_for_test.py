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
from pathlib import Path
import subprocess
import tempfile
from typing import Union

import git_command


def init_git_tree(path: Union[str, Path]) -> None:
    """Initialize `path` as a new git repo."""
    with contextlib.ExitStack() as stack:
        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git", "init"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init.
            templatedir = stack.enter_context(tempfile.mkdtemp(prefix="git-template"))
            (Path(templatedir) / "HEAD").write_text("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        cmd += [path]
        subprocess.run(cmd, check=True)


@contextlib.contextmanager
def TempGitTree():
    """Create a new empty git checkout for testing."""
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        init_git_tree(tempdir)
        yield tempdir
