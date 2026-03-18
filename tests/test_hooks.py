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
