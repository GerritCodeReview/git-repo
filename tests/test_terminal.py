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

"""Unittests for the terminal.py module."""

import io
import sys
from unittest import mock

import pytest

import terminal


class FakeStream:
    """A stream whose isatty() returns a fixed value."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.mark.parametrize("tty", (True, False))
def test_is_output_tty_stream(tty: bool) -> None:
    """Check is_output_tty() asks the given stream."""
    assert terminal.is_output_tty(FakeStream(tty)) is tty


@pytest.mark.parametrize("tty", (True, False))
def test_is_output_tty_defaults_to_stdout(
    monkeypatch: pytest.MonkeyPatch, tty: bool
) -> None:
    """Check is_output_tty() checks sys.stdout by default."""
    monkeypatch.setattr(sys, "stdout", FakeStream(tty))
    assert terminal.is_output_tty() is tty


@pytest.mark.parametrize("tty", (True, False))
def test_is_output_tty_fd(tty: bool) -> None:
    """Check is_output_tty() accepts a file descriptor."""
    with mock.patch("os.isatty", return_value=tty) as isatty:
        assert terminal.is_output_tty(2) is tty
    isatty.assert_called_once_with(2)


def test_is_output_tty_unusual_streams() -> None:
    """Check is_output_tty() treats broken streams as not a terminal."""
    closed = io.StringIO()
    closed.close()
    assert terminal.is_output_tty(closed) is False
    assert terminal.is_output_tty(object()) is False


@pytest.mark.parametrize(
    "stdin_tty, stdout_tty, expected",
    (
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ),
)
def test_is_input_interactive_needs_terminals(
    monkeypatch: pytest.MonkeyPatch,
    stdin_tty: bool,
    stdout_tty: bool,
    expected: bool,
) -> None:
    """Check is_input_interactive() needs stdin and stdout to be terminals."""
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    monkeypatch.setattr(sys, "stdin", FakeStream(stdin_tty))
    monkeypatch.setattr(sys, "stdout", FakeStream(stdout_tty))
    assert terminal.is_input_interactive() is expected


def test_is_input_interactive_no_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check is_input_interactive() handles a missing stdin."""
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", FakeStream(True))
    assert terminal.is_input_interactive() is False


@pytest.mark.parametrize(
    "value, expected",
    (
        ("0", False),
        ("false", False),
        ("False", False),
        ("no", False),
        ("OFF", False),
        ("", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
    ),
)
def test_is_input_interactive_git_terminal_prompt(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    """Check GIT_TERMINAL_PROMPT=false turns off prompts on a terminal."""
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", value)
    monkeypatch.setattr(sys, "stdin", FakeStream(True))
    monkeypatch.setattr(sys, "stdout", FakeStream(True))
    assert terminal.is_input_interactive() is expected
