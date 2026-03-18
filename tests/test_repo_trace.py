# Copyright (C) 2022 The Android Open Source Project
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

"""Unittests for the repo_trace.py module."""

import os

import pytest

import repo_trace


def test_trace_max_size_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check Trace behavior."""
    content = "git chicken"

    with repo_trace.Trace(content, first_trace=True):
        pass
    first_trace_size = os.path.getsize(repo_trace._TRACE_FILE)

    with repo_trace.Trace(content):
        pass
    assert os.path.getsize(repo_trace._TRACE_FILE) > first_trace_size

    # Check we clear everything if the last chunk is larger than _MAX_SIZE.
    monkeypatch.setattr(repo_trace, "_MAX_SIZE", 0)
    with repo_trace.Trace(content, first_trace=True):
        pass
    assert os.path.getsize(repo_trace._TRACE_FILE) == first_trace_size

    # Check we only clear the chunks we need to.
    new_max = (first_trace_size + 1) / (1024 * 1024)
    monkeypatch.setattr(repo_trace, "_MAX_SIZE", new_max)
    with repo_trace.Trace(content, first_trace=True):
        pass
    assert os.path.getsize(repo_trace._TRACE_FILE) == first_trace_size * 2

    with repo_trace.Trace(content, first_trace=True):
        pass
    assert os.path.getsize(repo_trace._TRACE_FILE) == first_trace_size * 2
