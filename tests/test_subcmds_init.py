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

"""Unittests for the subcmds/init.py module."""

from typing import List

import pytest

from subcmds import init


@pytest.mark.parametrize(
    "argv",
    ([],),
)
def test_cli_parser_good(argv: List[str]) -> None:
    """Check valid command line options."""
    cmd = init.Init()
    opts, args = cmd.OptionParser.parse_args(argv)
    cmd.ValidateOptions(opts, args)


@pytest.mark.parametrize(
    "argv",
    (
        # Too many arguments.
        ["url", "asdf"],
        # Conflicting options.
        ["--mirror", "--archive"],
    ),
)
def test_cli_parser_bad(argv: List[str]) -> None:
    """Check invalid command line options."""
    cmd = init.Init()
    opts, args = cmd.OptionParser.parse_args(argv)
    with pytest.raises(SystemExit):
        cmd.ValidateOptions(opts, args)
