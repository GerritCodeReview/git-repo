# Copyright (C) 2024 The Android Open Source Project
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

"""Unittests for the color.py module."""

import pytest
import utils_for_test

import color
import git_config


@pytest.fixture
def coloring() -> color.Coloring:
    """Create a Coloring object for testing."""
    config_fixture = utils_for_test.FIXTURES_DIR / "test.gitconfig"
    config = git_config.GitConfig(config_fixture)
    color.SetDefaultColoring("true")
    return color.Coloring(config, "status")


def test_Color_Parse_all_params_none(coloring: color.Coloring) -> None:
    """all params are None"""
    val = coloring._parse(None, None, None, None)
    assert val == ""


def test_Color_Parse_first_parameter_none(coloring: color.Coloring) -> None:
    """check fg & bg & attr"""
    val = coloring._parse(None, "black", "red", "ul")
    assert val == "\x1b[4;30;41m"


def test_Color_Parse_one_entry(coloring: color.Coloring) -> None:
    """check fg"""
    val = coloring._parse("one", None, None, None)
    assert val == "\033[33m"


def test_Color_Parse_two_entry(coloring: color.Coloring) -> None:
    """check fg & bg"""
    val = coloring._parse("two", None, None, None)
    assert val == "\033[35;46m"


def test_Color_Parse_three_entry(coloring: color.Coloring) -> None:
    """check fg & bg & attr"""
    val = coloring._parse("three", None, None, None)
    assert val == "\033[4;30;41m"


def test_Color_Parse_reset_entry(coloring: color.Coloring) -> None:
    """check reset entry"""
    val = coloring._parse("reset", None, None, None)
    assert val == "\033[m"


def test_Color_Parse_empty_entry(coloring: color.Coloring) -> None:
    """check empty entry"""
    val = coloring._parse("none", "blue", "white", "dim")
    assert val == "\033[2;34;47m"
    val = coloring._parse("empty", "green", "white", "bold")
    assert val == "\033[1;32;47m"
