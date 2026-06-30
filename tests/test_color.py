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

from unittest import mock

import pytest
import utils_for_test

import color
import git_config


@pytest.fixture
def coloring() -> color.Coloring:
    """Create a Coloring object for testing."""
    config_fixture = utils_for_test.FIXTURES_DIR / "test.gitconfig"
    config = git_config.GitConfig(config_fixture)
    color.SetDefaultColoring("always")
    return color.Coloring(config, "status")


def _make_coloring(default_state):
    """Helper to create a Coloring with a given default coloring state."""
    config_fixture = utils_for_test.FIXTURES_DIR / "test.gitconfig"
    config = git_config.GitConfig(config_fixture)
    color.SetDefaultColoring(default_state)
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


class TestSetDefaultColoring:
    """Tests for SetDefaultColoring."""

    def test_none_leaves_default_unchanged(self):
        color.DEFAULT = "auto"
        color.SetDefaultColoring(None)
        assert color.DEFAULT == "auto"

    @pytest.mark.parametrize("value", ("auto", "Auto", "AUTO"))
    def test_auto(self, value):
        color.SetDefaultColoring(value)
        assert color.DEFAULT == "auto"

    @pytest.mark.parametrize("value", ("true", "True", "TRUE"))
    def test_true_maps_to_auto(self, value):
        color.SetDefaultColoring(value)
        assert color.DEFAULT == "auto"

    @pytest.mark.parametrize("value", ("yes", "Yes", "YES"))
    def test_yes_maps_to_auto(self, value):
        color.SetDefaultColoring(value)
        assert color.DEFAULT == "auto"

    @pytest.mark.parametrize("value", ("always", "Always", "ALWAYS"))
    def test_always(self, value):
        color.SetDefaultColoring(value)
        assert color.DEFAULT == "always"

    @pytest.mark.parametrize("value", ("never", "no", "false"))
    def test_never(self, value):
        color.SetDefaultColoring(value)
        assert color.DEFAULT == "never"


class TestColoringInit:
    """Tests for Coloring.__init__ color mode logic."""

    def test_always_enables_color(self):
        """'always' should enable color regardless of terminal."""
        c = _make_coloring("always")
        assert c.is_on is True

    def test_never_disables_color(self):
        """'never' should disable color regardless of terminal."""
        c = _make_coloring("never")
        assert c.is_on is False

    def test_true_on_tty(self):
        """'true' should enable color when stdout is a TTY."""
        with mock.patch("os.isatty", return_value=True):
            c = _make_coloring("true")
        assert c.is_on is True

    def test_true_not_on_pipe(self):
        """'true' should disable color when stdout is not a TTY."""
        with mock.patch("os.isatty", return_value=False), mock.patch(
            "pager.active", False
        ):
            c = _make_coloring("true")
        assert c.is_on is False

    def test_yes_on_tty(self):
        """'yes' should enable color when stdout is a TTY."""
        with mock.patch("os.isatty", return_value=True):
            c = _make_coloring("yes")
        assert c.is_on is True

    def test_yes_not_on_pipe(self):
        """'yes' should disable color when stdout is not a TTY."""
        with mock.patch("os.isatty", return_value=False), mock.patch(
            "pager.active", False
        ):
            c = _make_coloring("yes")
        assert c.is_on is False

    def test_auto_on_tty(self):
        """'auto' should enable color when stdout is a TTY."""
        with mock.patch("os.isatty", return_value=True):
            c = _make_coloring("auto")
        assert c.is_on is True

    def test_auto_not_on_pipe(self):
        """'auto' should disable color when stdout is not a TTY."""
        with mock.patch("os.isatty", return_value=False), mock.patch(
            "pager.active", False
        ):
            c = _make_coloring("auto")
        assert c.is_on is False

    def test_auto_on_with_active_pager(self):
        """'auto' should enable color when pager is active."""
        with mock.patch("os.isatty", return_value=False), mock.patch(
            "pager.active", True
        ):
            c = _make_coloring("auto")
        assert c.is_on is True
