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

"""The repo logging module."""

import multiprocessing
import sys

from color import Coloring

class LogColoring(Coloring):
    def __init__(self, config):
        super().__init__(config, "logs")
        self.error = self.printer("error", fg="red")
        self.warn = self.printer("warn", fg="yellow")


class ConfigMock:
    """Default coloring config to use when Logging.config is not set."""

    def __init__(self):
        self.default_values = {"color.ui": "auto"}

    def GetString(self, x):
        return self.default_values.get(x, "")


class Logging:
    """Repo Logging Module."""

    errors = multiprocessing.Manager().list()
    config = None
    _out = None

    @staticmethod
    def out():
        """Returns out stream for logging."""
        if not Logging._out:
            # When config is not set, default to "auto" config.
            Logging._out = LogColoring(Logging.config if Logging.config else ConfigMock())

        return Logging._out

    @staticmethod
    def error(msg):
        """Print and aggregate error-level logs."""
        Logging.out().error(f"error: {msg}")
        Logging.out().nl()
        Logging.errors.append(f"error: {msg}")

    @staticmethod
    def log_errors():
        """Print aggregated logs."""
        Logging.out().error("=" * 80)
        Logging.out().nl()
        Logging.out().error("\n".join(Logging.errors))

    @staticmethod
    def warn(msg):
        """Print warning level logs."""
        Logging.out().warn(f"warn: {msg}")
        print(f"warning: {msg}")
