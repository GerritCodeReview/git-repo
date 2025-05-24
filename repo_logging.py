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

from color import Coloring
from error import RepoExitError


SEPARATOR = "=" * 80
MAX_PRINT_ERRORS = 5


class _ConfigMock:
    """Default coloring config to use when Logging.config is not set."""

    def __init__(self):
        self.default_values = {"color.ui": "auto"}

    def GetString(self, x):
        return self.default_values.get(x, None)


class _LogColoring(Coloring):
    """Coloring outstream for logging."""

    def __init__(self, config):
        super().__init__(config, "logs")
        self.error = self.nofmt_colorer("error", fg="red")
        self.warning = self.nofmt_colorer("warn", fg="yellow")
        self.levelMap = {
            "WARNING": self.warning,
            "ERROR": self.error,
        }


class _LogColoringFormatter(logging.Formatter):
    """Coloring formatter for logging."""

    def __init__(self, config=None, *args, **kwargs):
        self.config = config if config else _ConfigMock()
        self.colorer = _LogColoring(self.config)
        super().__init__(*args, **kwargs)

    def format(self, record):
        """Formats |record| with color."""
        msg = super().format(record)
        colorer = self.colorer.levelMap.get(record.levelname)
        return msg if not colorer else colorer(msg)


class RepoLogger(logging.Logger):
    """Repo Logging Module."""

    def __init__(self, name: str, config=None, **kwargs):
        super().__init__(name, **kwargs)
        handler = logging.StreamHandler()
        handler.setFormatter(_LogColoringFormatter(config))
        self.addHandler(handler)

    def log_aggregated_errors(self, err: RepoExitError):
        """Print all aggregated logs."""
        self.error(SEPARATOR)

        if not err.aggregate_errors:
            self.error("Repo command failed: %s", type(err).__name__)
            self.error("\t%s", str(err))
            return

        self.error(
            "Repo command failed due to the following `%s` errors:",
            type(err).__name__,
        )
        self.error(
            "\n".join(str(e) for e in err.aggregate_errors[:MAX_PRINT_ERRORS])
        )

        diff = len(err.aggregate_errors) - MAX_PRINT_ERRORS
        if diff > 0:
            self.error("+%d additional errors...", diff)
