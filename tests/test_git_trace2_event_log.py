# Copyright (C) 2020 The Android Open Source Project
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

"""Unittests for the git_trace2_event_log.py module."""

import contextlib
import io
import json
import os
import re
import socket
import tempfile
import threading
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

import git_trace2_event_log
import platform_utils


def server_logging_thread(
    socket_path: str,
    server_ready: threading.Condition,
    received_traces: List[str],
) -> None:
    """Helper function to receive logs over a Unix domain socket.

    Appends received messages on the provided socket and appends to
    received_traces.

    Args:
        socket_path: path to a Unix domain socket on which to listen for traces
        server_ready: a threading.Condition used to signal to the caller that
            this thread is ready to accept connections
        received_traces: a list to which received traces will be appended (after
            decoding to a utf-8 string).
    """
    platform_utils.remove(socket_path, missing_ok=True)
    data = b""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.bind(socket_path)
        sock.listen(0)
        with server_ready:
            server_ready.notify()
        with sock.accept()[0] as conn:
            while True:
                recved = conn.recv(4096)
                if not recved:
                    break
                data += recved
    received_traces.extend(data.decode("utf-8").splitlines())


PARENT_SID_KEY = "GIT_TRACE2_PARENT_SID"
PARENT_SID_VALUE = "parent_sid"
SELF_SID_REGEX = r"repo-\d+T\d+Z-.*"
FULL_SID_REGEX = rf"^{PARENT_SID_VALUE}/{SELF_SID_REGEX}"


@pytest.fixture
def event_log() -> git_trace2_event_log.EventLog:
    """Fixture for the EventLog module."""
    # By default we initialize with the expected case where
    # repo launches us (so GIT_TRACE2_PARENT_SID is set).
    env = {PARENT_SID_KEY: PARENT_SID_VALUE}
    return git_trace2_event_log.EventLog(env=env)


def verify_common_keys(
    log_entry: Dict[str, Any],
    expected_event_name: Optional[str] = None,
    full_sid: bool = True,
) -> None:
    """Helper function to verify common event log keys."""
    assert "event" in log_entry
    assert "sid" in log_entry
    assert "thread" in log_entry
    assert "time" in log_entry

    # Do basic data format validation.
    if expected_event_name:
        assert expected_event_name == log_entry["event"]
    if full_sid:
        assert re.match(FULL_SID_REGEX, log_entry["sid"])
    else:
        assert re.match(SELF_SID_REGEX, log_entry["sid"])
    assert re.match(r"^\d+-\d+-\d+T\d+:\d+:\d+\.\d+\+00:00$", log_entry["time"])


def read_log(log_path: str) -> List[Dict[str, Any]]:
    """Helper function to read log data into a list."""
    log_data = []
    with open(log_path, mode="rb") as f:
        for line in f:
            log_data.append(json.loads(line))
    return log_data


def remove_prefix(s: str, prefix: str) -> str:
    """Return a copy string after removing |prefix| from |s|, if present or
    the original string."""
    if s.startswith(prefix):
        return s[len(prefix) :]
    else:
        return s


def test_initial_state_with_parent_sid(
    event_log: git_trace2_event_log.EventLog,
) -> None:
    """Test initial state when 'GIT_TRACE2_PARENT_SID' is set by parent."""
    assert re.match(FULL_SID_REGEX, event_log.full_sid)


def test_initial_state_no_parent_sid() -> None:
    """Test initial state when 'GIT_TRACE2_PARENT_SID' is not set."""
    # Setup an empty environment dict (no parent sid).
    event_log = git_trace2_event_log.EventLog(env={})
    assert re.match(SELF_SID_REGEX, event_log.full_sid)


def test_version_event(event_log: git_trace2_event_log.EventLog) -> None:
    """Test 'version' event data is valid.

    Verify that the 'version' event is written even when no other
    events are added.

    Expected event log:
    <version event>
    """
    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    # A log with no added events should only have the version entry.
    assert len(log_data) == 1
    version_event = log_data[0]
    verify_common_keys(version_event, expected_event_name="version")
    # Check for 'version' event specific fields.
    assert "evt" in version_event
    assert "exe" in version_event
    # Verify "evt" version field is a string.
    assert isinstance(version_event["evt"], str)


def test_start_event(event_log: git_trace2_event_log.EventLog) -> None:
    """Test and validate 'start' event data is valid.

    Expected event log:
    <version event>
    <start event>
    """
    event_log.StartEvent([])
    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 2
    start_event = log_data[1]
    verify_common_keys(log_data[0], expected_event_name="version")
    verify_common_keys(start_event, expected_event_name="start")
    # Check for 'start' event specific fields.
    assert "argv" in start_event
    assert isinstance(start_event["argv"], list)


def test_exit_event_result_none(
    event_log: git_trace2_event_log.EventLog,
) -> None:
    """Test 'exit' event data is valid when result is None.

    We expect None result to be converted to 0 in the exit event data.

    Expected event log:
    <version event>
    <exit event>
    """
    event_log.ExitEvent(None)
    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 2
    exit_event = log_data[1]
    verify_common_keys(log_data[0], expected_event_name="version")
    verify_common_keys(exit_event, expected_event_name="exit")
    # Check for 'exit' event specific fields.
    assert "code" in exit_event
    # 'None' result should convert to 0 (successful) return code.
    assert exit_event["code"] == 0


def test_exit_event_result_integer(
    event_log: git_trace2_event_log.EventLog,
) -> None:
    """Test 'exit' event data is valid when result is an integer.

    Expected event log:
    <version event>
    <exit event>
    """
    event_log.ExitEvent(2)
    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 2
    exit_event = log_data[1]
    verify_common_keys(log_data[0], expected_event_name="version")
    verify_common_keys(exit_event, expected_event_name="exit")
    # Check for 'exit' event specific fields.
    assert "code" in exit_event
    assert exit_event["code"] == 2


def test_command_event(event_log: git_trace2_event_log.EventLog) -> None:
    """Test and validate 'command' event data is valid.

    Expected event log:
    <version event>
    <command event>
    """
    event_log.CommandEvent(name="repo", subcommands=["init", "this"])
    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 2
    command_event = log_data[1]
    verify_common_keys(log_data[0], expected_event_name="version")
    verify_common_keys(command_event, expected_event_name="cmd_name")
    # Check for 'command' event specific fields.
    assert "name" in command_event
    assert command_event["name"] == "repo-init-this"


def test_def_params_event_repo_config(
    event_log: git_trace2_event_log.EventLog,
) -> None:
    """Test 'def_params' event data outputs only repo config keys.

    Expected event log:
    <version event>
    <def_param event>
    <def_param event>
    """
    config = {
        "git.foo": "bar",
        "repo.partialclone": "true",
        "repo.partialclonefilter": "blob:none",
    }
    event_log.DefParamRepoEvents(config)

    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 3
    def_param_events = log_data[1:]
    verify_common_keys(log_data[0], expected_event_name="version")

    for event in def_param_events:
        verify_common_keys(event, expected_event_name="def_param")
        # Check for 'def_param' event specific fields.
        assert "param" in event
        assert "value" in event
        assert event["param"].startswith("repo.")


def test_def_params_event_no_repo_config(
    event_log: git_trace2_event_log.EventLog,
) -> None:
    """Test 'def_params' event data won't output non-repo config keys.

    Expected event log:
    <version event>
    """
    config = {
        "git.foo": "bar",
        "git.core.foo2": "baz",
    }
    event_log.DefParamRepoEvents(config)

    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 1
    verify_common_keys(log_data[0], expected_event_name="version")


def test_data_event_config(event_log: git_trace2_event_log.EventLog) -> None:
    """Test 'data' event data outputs all config keys.

    Expected event log:
    <version event>
    <data event>
    <data event>
    """
    config = {
        "git.foo": "bar",
        "repo.partialclone": "false",
        "repo.syncstate.superproject.hassuperprojecttag": "true",
        "repo.syncstate.superproject.sys.argv": ["--", "sync", "protobuf"],
    }
    prefix_value = "prefix"
    event_log.LogDataConfigEvents(config, prefix_value)

    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 5
    data_events = log_data[1:]
    verify_common_keys(log_data[0], expected_event_name="version")

    for event in data_events:
        verify_common_keys(event)
        # Check for 'data' event specific fields.
        assert "key" in event
        assert "value" in event
        key = event["key"]
        key = remove_prefix(key, f"{prefix_value}/")
        value = event["value"]
        assert event_log.GetDataEventName(value) == event["event"]
        assert key in config
        assert value == config[key]


def test_error_event(event_log: git_trace2_event_log.EventLog) -> None:
    """Test and validate 'error' event data is valid.

    Expected event log:
    <version event>
    <error event>
    """
    msg = "invalid option: --cahced"
    fmt = "invalid option: %s"
    event_log.ErrorEvent(msg, fmt)
    with tempfile.TemporaryDirectory(prefix="event_log_tests") as tempdir:
        log_path = event_log.Write(path=tempdir)
        log_data = read_log(log_path)

    assert len(log_data) == 2
    error_event = log_data[1]
    verify_common_keys(log_data[0], expected_event_name="version")
    verify_common_keys(error_event, expected_event_name="error")
    # Check for 'error' event specific fields.
    assert "msg" in error_event
    assert "fmt" in error_event
    assert error_event["msg"] == f"RepoErrorEvent:{msg}"
    assert error_event["fmt"] == f"RepoErrorEvent:{fmt}"


def test_write_with_filename(event_log: git_trace2_event_log.EventLog) -> None:
    """Test Write() with a path to a file exits with None."""
    assert event_log.Write(path="path/to/file") is None


def test_write_with_git_config(
    tmp_path,
    event_log: git_trace2_event_log.EventLog,
) -> None:
    """Test Write() uses the git config path when 'git config' call succeeds."""
    with mock.patch.object(
        event_log,
        "_GetEventTargetPath",
        return_value=str(tmp_path),
    ):
        assert os.path.dirname(event_log.Write()) == str(tmp_path)


def test_write_no_git_config(event_log: git_trace2_event_log.EventLog) -> None:
    """Test Write() with no git config variable present exits with None."""
    with mock.patch.object(event_log, "_GetEventTargetPath", return_value=None):
        assert event_log.Write() is None


def test_write_non_string(event_log: git_trace2_event_log.EventLog) -> None:
    """Test Write() with non-string type for |path| throws TypeError."""
    with pytest.raises(TypeError):
        event_log.Write(path=1234)


@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Requires AF_UNIX sockets"
)
def test_write_socket(event_log: git_trace2_event_log.EventLog) -> None:
    """Test Write() with Unix domain socket and validate received traces."""
    received_traces: List[str] = []
    with tempfile.TemporaryDirectory(prefix="test_server_sockets") as tempdir:
        socket_path = os.path.join(tempdir, "server.sock")
        server_ready = threading.Condition()
        # Start "server" listening on Unix domain socket at socket_path.
        server_thread = threading.Thread(
            target=server_logging_thread,
            args=(socket_path, server_ready, received_traces),
        )
        try:
            server_thread.start()

            with server_ready:
                server_ready.wait(timeout=120)

            event_log.StartEvent([])
            path = event_log.Write(path=f"af_unix:{socket_path}")
        finally:
            server_thread.join(timeout=5)

    assert path == f"af_unix:stream:{socket_path}"
    assert len(received_traces) == 2
    version_event = json.loads(received_traces[0])
    start_event = json.loads(received_traces[1])
    verify_common_keys(version_event, expected_event_name="version")
    verify_common_keys(start_event, expected_event_name="start")
    # Check for 'start' event specific fields.
    assert "argv" in start_event
    assert isinstance(start_event["argv"], list)


class TestEventLogVerbose:
    """TestCase for the EventLog module verbose logging."""

    def test_write_socket_error_no_verbose(self) -> None:
        """Test Write() suppression of socket errors when not verbose."""
        event_log = git_trace2_event_log.EventLog(env={})
        event_log.verbose = False
        with contextlib.redirect_stderr(
            io.StringIO()
        ) as mock_stderr, mock.patch("socket.socket", side_effect=OSError):
            event_log.Write(path="af_unix:stream:/tmp/test_sock")
            assert mock_stderr.getvalue() == ""

    def test_write_socket_error_verbose(self) -> None:
        """Test Write() printing of socket errors when verbose."""
        event_log = git_trace2_event_log.EventLog(env={})
        event_log.verbose = True
        with contextlib.redirect_stderr(
            io.StringIO()
        ) as mock_stderr, mock.patch(
            "socket.socket", side_effect=OSError("Mock error")
        ):
            event_log.Write(path="af_unix:stream:/tmp/test_sock")
            assert (
                "git trace2 logging failed: Mock error"
                in mock_stderr.getvalue()
            )

    def test_write_file_error_no_verbose(self) -> None:
        """Test Write() suppression of file errors when not verbose."""
        event_log = git_trace2_event_log.EventLog(env={})
        event_log.verbose = False
        with contextlib.redirect_stderr(
            io.StringIO()
        ) as mock_stderr, mock.patch(
            "tempfile.NamedTemporaryFile", side_effect=FileExistsError
        ):
            event_log.Write(path="/tmp")
            assert mock_stderr.getvalue() == ""

    def test_write_file_error_verbose(self) -> None:
        """Test Write() printing of file errors when verbose."""
        event_log = git_trace2_event_log.EventLog(env={})
        event_log.verbose = True
        with contextlib.redirect_stderr(
            io.StringIO()
        ) as mock_stderr, mock.patch(
            "tempfile.NamedTemporaryFile",
            side_effect=FileExistsError("Mock error"),
        ):
            event_log.Write(path="/tmp")
            assert (
                "git trace2 logging failed: FileExistsError"
                in mock_stderr.getvalue()
            )
