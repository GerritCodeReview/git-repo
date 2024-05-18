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

import os
import unittest

import color
import git_config


def fixture(*paths):
    """Return a path relative to test/fixtures."""
    return os.path.join(os.path.dirname(__file__), "fixtures", *paths)


class ColoringTests(unittest.TestCase):
    """tests of the Coloring class."""

    def setUp(self):
        """Create a GitConfig object using the test.gitconfig fixture."""
        config_fixture = fixture("test.gitconfig")
        self.config = git_config.GitConfig(config_fixture)
        color.SetDefaultColoring("true")
        self.color = color.Coloring(self.config, "status")

    def test_Color_Parse_all_params_none(self):
        """all params are None"""
        val = self.color._parse(None, None, None, None)
        self.assertEqual("", val)

    def test_Color_Parse_first_parameter_none(self):
        """check fg & bg & attr"""
        val = self.color._parse(None, "black", "red", "ul")
        self.assertEqual("\x1b[4;30;41m", val)

    def test_Color_Parse_one_entry(self):
        """check fg"""
        val = self.color._parse("one", None, None, None)
        self.assertEqual("\033[33m", val)

    def test_Color_Parse_two_entry(self):
        """check fg & bg"""
        val = self.color._parse("two", None, None, None)
        self.assertEqual("\033[35;46m", val)

    def test_Color_Parse_three_entry(self):
        """check fg & bg & attr"""
        val = self.color._parse("three", None, None, None)
        self.assertEqual("\033[4;30;41m", val)

    def test_Color_Parse_reset_entry(self):
        """check reset entry"""
        val = self.color._parse("reset", None, None, None)
        self.assertEqual("\033[m", val)

    def test_Color_Parse_empty_entry(self):
        """check empty entry"""
        val = self.color._parse("none", "blue", "white", "dim")
        self.assertEqual("\033[2;34;47m", val)
        val = self.color._parse("empty", "green", "white", "bold")
        self.assertEqual("\033[1;32;47m", val)
