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

"""Helpers to decide how repo talks to the terminal."""

import os
import sys
from typing import IO, Optional, Union


# Values of GIT_TERMINAL_PROMPT that git treats as false. git also treats an
# empty value as false.
_FALSE_VALUES = ("", "false", "no", "off", "0")


def _isatty(stream: Optional[IO]) -> bool:
    """Returns whether |stream| is a terminal, tolerating unusual streams."""
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        # The stream is None, has been replaced by an object without isatty(),
        # or has been closed.
        return False


def is_output_tty(stream: Union[IO, int, None] = None) -> bool:
    """Returns whether output written to |stream| shows up on a terminal.

    Use this to decide on output formatting: colors, escape sequences, and
    progress bars.

    Args:
        stream: A file object or a file descriptor. Defaults to sys.stdout.
    """
    if stream is None:
        stream = sys.stdout
    if isinstance(stream, int):
        return os.isatty(stream)
    return _isatty(stream)


def is_input_interactive() -> bool:
    """Returns whether repo may prompt the user and wait for an answer.

    Prompts are written to stdout and answered on stdin, so both have to be
    terminals.

    This also honors GIT_TERMINAL_PROMPT, which git documents as "git will not
    prompt on the terminal" when it is false. Tools that run repo in a
    pseudo-terminal, where isatty() is true but nobody can answer, can set it
    to turn off prompts in both git and repo.
    """
    value = os.environ.get("GIT_TERMINAL_PROMPT")
    if value is not None and value.strip().lower() in _FALSE_VALUES:
        return False
    return _isatty(sys.stdin) and _isatty(sys.stdout)
