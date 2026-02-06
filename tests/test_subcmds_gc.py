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

"""Unittests for the subcmds/gc.py module."""

import unittest
from unittest import mock

from subcmds import gc


class GcCommand(unittest.TestCase):
    """Tests for gc command."""

    def setUp(self):
        self.cmd = gc.Gc()
        self.opt, self.args = self.cmd.OptionParser.parse_args([])
        self.opt.this_manifest_only = False
        self.opt.repack = False

        self.mock_get_projects = mock.patch.object(
            self.cmd, "GetProjects"
        ).start()

        self.mock_delete = mock.patch.object(
            self.cmd, "delete_unused_projects", return_value=0
        ).start()

        self.mock_repack = mock.patch.object(
            self.cmd, "repack_projects", return_value=0
        ).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_gc_no_args(self):
        """Test gc without specific projects."""
        self.mock_get_projects.return_value = ["all_projects"]

        self.cmd.Execute(self.opt, [])

        self.mock_get_projects.assert_called_once_with([], all_manifests=True)
        self.mock_delete.assert_called_once_with(["all_projects"], self.opt)
        self.mock_repack.assert_not_called()

    def test_gc_with_args(self):
        """Test gc with specific projects uses all_projects for delete."""
        self.mock_get_projects.side_effect = [["projA"], ["all_projects"]]
        self.opt.repack = True

        self.cmd.Execute(self.opt, ["projA"])

        self.mock_get_projects.assert_has_calls(
            [
                mock.call(["projA"], all_manifests=True),
                mock.call([], all_manifests=True),
            ]
        )

        self.mock_delete.assert_called_once_with(["all_projects"], self.opt)
        self.mock_repack.assert_called_once_with(["projA"], self.opt)

    def test_gc_exit_on_delete_failure(self):
        """Test gc exits if delete_unused_projects fails."""
        self.mock_get_projects.return_value = ["all_projects"]
        self.mock_delete.return_value = 1
        self.opt.repack = True

        ret = self.cmd.Execute(self.opt, [])
        self.assertEqual(ret, 1)
        self.mock_repack.assert_not_called()
