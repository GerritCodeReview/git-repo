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
from pathlib import Path
import sys

import pytest

from git_trace2_event_log import EventLog
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
            self.worktree = "/some/path"
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

        executed_kwargs = {}

        def fake_execute(**kw):
            executed_kwargs.update(kw)

        hook._ExecuteHook = fake_execute

        res = hook.Run(repo_topdir="/topdir", sync_duration_seconds=12.345)
        assert res is True
        assert executed_kwargs.get("sync_duration_seconds") == 12.345

    finally:
        sys.stderr = old_stderr


@pytest.mark.parametrize("yes_val", (True, False))
def test_repo_upload_yes_arg(tmp_path, yes_val: bool) -> None:
    """Test that yes is passed in kwargs during hook execution."""

    class FakeProject:
        def __init__(self, worktree):
            self.worktree = worktree
            self.enabled_repo_hooks = ["pre-upload"]
            self.config = None

    hook_file = tmp_path / "pre-upload.py"

    hook_content = """
def main(project_list, **kwargs):
    project_list.append(kwargs.get("yes"))
"""
    hook_file.write_text(hook_content)

    hook = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path)),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        allow_all_hooks=True,
        yes=yes_val,
    )

    project_list = []
    res = hook.Run(project_list=project_list, worktree_list=[])

    assert res is True
    assert project_list == [yes_val]


def test_hook_tracing_and_event_log(tmp_path: Path) -> None:
    """Test that hook execution emits region_enter and region_leave events."""

    class FakeProject:
        def __init__(self, worktree: str) -> None:
            self.worktree = worktree
            self.enabled_repo_hooks = ["pre-upload"]
            self.config = None

    hook_file = tmp_path / "pre-upload.py"
    hook_file.write_text("def main(project_list, **kwargs):\n    pass\n")

    event_log = EventLog(env={})
    hook = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path)),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        allow_all_hooks=True,
        git_event_log=event_log,
    )

    res = hook.Run(project_list=[], worktree_list=[])
    assert res is True

    events = event_log._log
    region_enters = [
        e
        for e in events
        if e.get("event") == "region_enter" and e.get("category") == "repo:hook"
    ]
    region_leaves = [
        e
        for e in events
        if e.get("event") == "region_leave" and e.get("category") == "repo:hook"
    ]

    assert len(region_enters) == 1
    assert region_enters[0]["label"] == "pre-upload"
    assert region_enters[0]["nesting"] == 1

    assert len(region_leaves) == 1
    assert region_leaves[0]["label"] == "pre-upload"
    assert region_leaves[0]["nesting"] == 1
    assert isinstance(region_leaves[0]["t_rel"], float)
    assert region_leaves[0]["msg"] == "passed"

    passed_events = [
        e
        for e in events
        if e.get("event") == "data" and e.get("key") == "hook/pre-upload/passed"
    ]
    assert len(passed_events) == 1
    assert passed_events[0]["value"] == "True"


def test_hook_tracing_failure(tmp_path: Path) -> None:
    """Test that failed hook execution emits leave event with failed msg."""

    class FakeProject:
        def __init__(self, worktree: str) -> None:
            self.worktree = worktree
            self.enabled_repo_hooks = ["pre-upload"]
            self.config = None

    hook_file = tmp_path / "pre-upload.py"
    hook_file.write_text(
        "def main(project_list, **kwargs):\n    raise SystemExit(1)\n"
    )

    event_log = EventLog(env={})
    hook = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path)),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        allow_all_hooks=True,
        git_event_log=event_log,
    )

    res = hook.Run(project_list=[], worktree_list=[])
    assert res is False

    events = event_log._log
    region_leaves = [
        e
        for e in events
        if e.get("event") == "region_leave" and e.get("category") == "repo:hook"
    ]
    assert len(region_leaves) == 1
    assert region_leaves[0]["msg"] == "failed"

    passed_events = [
        e
        for e in events
        if e.get("event") == "data" and e.get("key") == "hook/pre-upload/passed"
    ]
    assert len(passed_events) == 1
    assert passed_events[0]["value"] == "False"


def test_hook_bypass_event_log(tmp_path: Path) -> None:
    """Test that bypassing hook logs a data event only when hook is enabled."""

    class FakeProject:
        def __init__(self, worktree: str, enabled: bool = True) -> None:
            self.worktree = worktree
            self.enabled_repo_hooks = ["pre-upload"] if enabled else []
            self.config = None

    hook_file = tmp_path / "pre-upload.py"
    hook_file.write_text("def main(project_list, **kwargs):\n    pass\n")

    # 1. Bypassed when hook is enabled -> logs data event
    event_log = EventLog(env={})
    hook = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path), enabled=True),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        bypass_hooks=True,
        git_event_log=event_log,
    )
    res = hook.Run(project_list=[], worktree_list=[])
    assert res is True

    events = event_log._log
    bypassed_events = [
        e
        for e in events
        if e.get("event") == "data"
        and e.get("key") == "hook/pre-upload/bypassed"
    ]
    assert len(bypassed_events) == 1
    assert bypassed_events[0]["value"] == "True"

    # 2. Bypassed when hook is not enabled -> does not log data event
    event_log_no_hook = EventLog(env={})
    hook_no_enabled = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path), enabled=False),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        bypass_hooks=True,
        git_event_log=event_log_no_hook,
    )
    res = hook_no_enabled.Run(project_list=[], worktree_list=[])
    assert res is True

    no_bypassed = [
        e
        for e in event_log_no_hook._log
        if e.get("event") == "data"
        and e.get("key") == "hook/pre-upload/bypassed"
    ]
    assert len(no_bypassed) == 0


def test_hook_tracing_not_approved(tmp_path: Path) -> None:
    """Test that denying hook approval records status='not_approved'."""

    class FakeProject:
        def __init__(self, worktree: str) -> None:
            self.worktree = worktree
            self.enabled_repo_hooks = ["pre-upload"]
            self.config = None

    hook_file = tmp_path / "pre-upload.py"
    hook_file.write_text("def main(project_list, **kwargs):\n    pass\n")

    event_log = EventLog(env={})
    hook = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path)),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        allow_all_hooks=False,
        abort_if_user_denies=False,
        git_event_log=event_log,
    )
    hook._CheckForHookApproval = lambda: False

    res = hook.Run(project_list=[], worktree_list=[])
    assert res is False

    events = event_log._log
    region_leaves = [
        e
        for e in events
        if e.get("event") == "region_leave" and e.get("category") == "repo:hook"
    ]
    assert len(region_leaves) == 1
    assert region_leaves[0]["msg"] == "not_approved"

    status_events = [
        e
        for e in events
        if e.get("event") == "data" and e.get("key") == "hook/pre-upload/status"
    ]
    assert len(status_events) == 1
    assert status_events[0]["value"] == "not_approved"


def test_hook_tracing_aborted(tmp_path: Path) -> None:
    """Test that KeyboardInterrupt during hook records status='aborted'."""

    class FakeProject:
        def __init__(self, worktree: str) -> None:
            self.worktree = worktree
            self.enabled_repo_hooks = ["pre-upload"]
            self.config = None

    hook_file = tmp_path / "pre-upload.py"
    hook_file.write_text("def main(project_list, **kwargs):\n    pass\n")

    event_log = EventLog(env={})
    hook = hooks.RepoHook(
        hook_type="pre-upload",
        hooks_project=FakeProject(str(tmp_path)),
        repo_topdir=str(tmp_path),
        manifest_url="https://gerrit",
        allow_all_hooks=True,
        git_event_log=event_log,
    )

    def raise_interrupt(**kwargs):
        raise KeyboardInterrupt()

    hook._ExecuteHook = raise_interrupt

    with pytest.raises(KeyboardInterrupt):
        hook.Run(project_list=[], worktree_list=[])

    events = event_log._log
    region_leaves = [
        e
        for e in events
        if e.get("event") == "region_leave" and e.get("category") == "repo:hook"
    ]
    assert len(region_leaves) == 1
    assert region_leaves[0]["msg"] == "aborted"

    status_events = [
        e
        for e in events
        if e.get("event") == "data" and e.get("key") == "hook/pre-upload/status"
    ]
    assert len(status_events) == 1
    assert status_events[0]["value"] == "aborted"
