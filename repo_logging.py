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
from typing import Any, List

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

    def __init__(self, name: str, config=None, **kwargs):
        super().__init__(name, **kwargs)
        self.config = config if config else ConfigMock()
        self.colorer = LogColoring(self.config)

    def error(self, msg: Any, *args, **kwargs):
        """Print and aggregate error-level logs."""
        colored_error = self.colorer.error(str(msg), *args)
        super().error(colored_error, **kwargs)

    def warning(self, msg: Any, *args, **kwargs):
        """Print warning-level logs with coloring."""
        colored_warning = self.colorer.warning(str(msg), *args)
        super().warning(colored_warning, **kwargs)

    def log_aggregated_errors(self, errors: List[Exception]):
        """Print all aggregated logs."""
        super().error(self.colorer.error(SEPARATOR))
        super().error(
            self.colorer.error("Repo command failed due to following errors:")
        )
        super().error("\n".join(map(str, errors)))
