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

"""Unittests for the list subcmd."""

from typing import List, Optional
from unittest import mock

import pytest

import subcmds


@pytest.mark.parametrize(
    ("extra_args", "expected_groups", "expected_missing_ok"),
    [
        (["--groups", "special"], "special", None),
        (["--all"], None, True),
    ],
    ids=("groups", "all"),
)
def test_list_regex_passes_groups_and_all(
    extra_args: List[str],
    expected_groups: Optional[str],
    expected_missing_ok: Optional[bool],
) -> None:
    """Pass --groups and --all through in regex mode."""
    cmd = subcmds.list.List()

    opts, args = cmd.OptionParser.parse_args(
        ["--regex", *extra_args, "project"]
    )

    with mock.patch.object(
        cmd,
        "FindProjects",
        return_value=[],
    ) as find_projects:
        cmd.Execute(opts, args)

    find_projects.assert_called_once_with(
        ["project"],
        groups=expected_groups,
        missing_ok=expected_missing_ok,
        all_manifests=True,
    )
