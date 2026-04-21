# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the hooks.py module."""

from io import StringIO
import sys

import pytest

import hooks


@pytest.mark.parametrize(
    "data",
    (
        "",
        "#\n# foo\n",
        "# Bad shebang in script\n#!/foo\n",
    ),
)
def test_no_shebang(data: str) -> None:
    """Lines w/out shebangs should be rejected."""
    assert hooks.RepoHook._ExtractInterpFromShebang(data) is None


@pytest.mark.parametrize(
    "shebang, interp",
    (
        ("#!/foo", "/foo"),
        ("#! /foo", "/foo"),
        ("#!/bin/foo ", "/bin/foo"),
        ("#! /usr/foo ", "/usr/foo"),
        ("#! /usr/foo -args", "/usr/foo"),
    ),
)
def test_direct_interp(shebang: str, interp: str) -> None:
    """Lines whose shebang points directly to the interpreter."""
    assert hooks.RepoHook._ExtractInterpFromShebang(shebang) == interp


@pytest.mark.parametrize(
    "shebang, interp",
    (
        ("#!/usr/bin/env foo", "foo"),
        ("#!/bin/env foo", "foo"),
        ("#! /bin/env /bin/foo ", "/bin/foo"),
    ),
)
def test_env_interp(shebang: str, interp: str) -> None:
    """Lines whose shebang launches through `env`."""
    assert hooks.RepoHook._ExtractInterpFromShebang(shebang) == interp


def test_post_sync_argument_validation() -> None:
    """Test that post-sync hook requires exact API arguments."""

    class FakeProject:

        def __init__(self):
            self.worktree = None
            self.enabled_repo_hooks = ["post-sync"]

    hook = hooks.RepoHook(
        hook_type="post-sync",
        hooks_project=FakeProject(),
        repo_topdir="/topdir",
        manifest_url="https://gerrit",
        allow_all_hooks=True,
    )

    old_stderr = sys.stderr
    sys.stderr = StringIO()

    try:
        # Call with missing arg `sync_duration_seconds`
        res = hook.Run(repo_topdir="/topdir")
        assert res is False
        assert "hook 'post-sync' called incorrectly" in sys.stderr.getvalue()

        # Mock _CheckHook and _ExecuteHook to test success path
        hook._CheckHook = lambda: None
        hook._ExecuteHook = lambda **kw: None

        res = hook.Run(repo_topdir="/topdir", sync_duration_seconds=12.345)
        assert res is True

    finally:
        sys.stderr = old_stderr
