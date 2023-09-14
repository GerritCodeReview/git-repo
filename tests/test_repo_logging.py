# Copyright (C) 2023 The Android Open Source Project
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

"""Unit test for repo_logging module."""
import unittest
from unittest import mock

from error import RepoExitError
from repo_logging import RepoLogger


class TestRepoLogger(unittest.TestCase):
    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_logs_aggregated_errors(self, mock_error):
        """Test if log_aggregated_errors logs a list of aggregated errors."""
        logger = RepoLogger(__name__)
        logger.log_aggregated_errors(
            RepoExitError(
                aggregate_errors=[
                    Exception("foo"),
                    Exception("bar"),
                    Exception("baz"),
                    Exception("hello"),
                    Exception("world"),
                    Exception("test"),
                ]
            )
        )

        mock_error.assert_has_calls(
            [
                mock.call("=" * 80),
                mock.call(
                    "Repo command failed due to the following `%s` errors:",
                    "RepoExitError",
                ),
                mock.call("foo\nbar\nbaz\nhello\nworld"),
                mock.call("+%d additional errors...", 1),
            ]
        )

    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_logs_single_error(self, mock_error):
        """Test if log_aggregated_errors logs empty aggregated_errors."""
        logger = RepoLogger(__name__)
        logger.log_aggregated_errors(RepoExitError())

        mock_error.assert_has_calls(
            [
                mock.call("=" * 80),
                mock.call("Repo command failed: %s", "RepoExitError"),
            ]
        )
