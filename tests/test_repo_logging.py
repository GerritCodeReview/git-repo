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

from repo_logging import RepoLogger


class TestRepoLogger(unittest.TestCase):
    def test_error_logs_error(self):
        """Test if error fn outputs logs."""
        logger = RepoLogger(__name__)
        result = None

        def mock_handler(log):
            nonlocal result
            result = log.getMessage()

        mock_out = mock.MagicMock()
        mock_out.level = 0
        mock_out.handle = mock_handler
        logger.addHandler(mock_out)

        logger.error("We're no strangers to love")

        self.assertEqual(result, "We're no strangers to love")

    def test_warning_logs_error(self):
        """Test if warning fn outputs logs."""
        logger = RepoLogger(__name__)
        result = None

        def mock_handler(log):
            nonlocal result
            result = log.getMessage()

        mock_out = mock.MagicMock()
        mock_out.level = 0
        mock_out.handle = mock_handler
        logger.addHandler(mock_out)

        logger.warning("You know the rules and so do I (do I)")

        self.assertEqual(result, "You know the rules and so do I (do I)")

    def test_log_aggregated_errors_logs_aggregated_errors(self):
        """Test if log_aggregated_errors outputs aggregated errors."""
        logger = RepoLogger(__name__)
        result = []

        def mock_handler(log):
            nonlocal result
            result.append(log.getMessage())

        mock_out = mock.MagicMock()
        mock_out.level = 0
        mock_out.handle = mock_handler
        logger.addHandler(mock_out)

        logger.error("Never gonna give you up")
        logger.error("Never gonna let you down")
        logger.error("Never gonna run around and desert you")
        logger.log_aggregated_errors(
            [
                "Never gonna give you up",
                "Never gonna let you down",
                "Never gonna run around and desert you",
            ]
        )

        self.assertEqual(
            result,
            [
                "Never gonna give you up",
                "Never gonna let you down",
                "Never gonna run around and desert you",
                "=" * 80,
                "Repo command failed due to following errors:",
                (
                    "Never gonna give you up\n"
                    "Never gonna let you down\n"
                    "Never gonna run around and desert you"
                ),
            ],
        )
