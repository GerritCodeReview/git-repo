# Copyright 2022 The Android Open Source Project
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

"""Common fixtures for pytests."""

import pytest

import repo_trace


@pytest.fixture(autouse=True)
def disable_repo_trace(tmp_path):
  """Set an environment marker to relax certain strict checks for test code."""
  repo_trace._TRACE_FILE = str(tmp_path / 'TRACE_FILE_from_test')
