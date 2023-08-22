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

"""Logic for printing user-friendly logs in repo."""

import logging
import multiprocessing

from color import Coloring


SEPARATOR = "=" * 80


class LogColoring(Coloring):
    """Coloring outstream for logging."""

    def __init__(self, config):
        super().__init__(config, "logs")
        self.error = self.colorer("error", fg="red")
        self.warning = self.colorer("warn", fg="yellow")


class ConfigMock:
    """Default coloring config to use when Logging.config is not set."""

    def __init__(self):
        self.default_values = {"color.ui": "auto"}

    def GetString(self, x):
        return self.default_values.get(x, None)


class RepoLogger(logging.Logger):
    """Repo Logging Module."""

    # Aggregates error-level logs. This is used to generate an error summary
    # section at the end of a command execution.
    errors = multiprocessing.Manager().list()

    def __init__(self, name, config=None, **kwargs):
        super().__init__(name, **kwargs)
        self.config = config if config else ConfigMock()
        self.colorer = LogColoring(self.config)

    def error(self, msg, *args, **kwargs):
        """Print and aggregate error-level logs."""
        colored_error = self.colorer.error(msg, *args)
        RepoLogger.errors.append(colored_error)

        super().error(colored_error, **kwargs)

    def warning(self, msg, *args, **kwargs):
        """Print warning-level logs with coloring."""
        colored_warning = self.colorer.warning(msg, *args)
        super().warning(colored_warning, **kwargs)

    def log_aggregated_errors(self):
        """Print all aggregated logs."""
        super().error(self.colorer.error(SEPARATOR))
        super().error(
            self.colorer.error("Repo command failed due to following errors:")
        )
        super().error("\n".join(RepoLogger.errors))
