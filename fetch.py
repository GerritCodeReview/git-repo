# Copyright (C) 2021 The Android Open Source Project
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

"""This module contains functions used to fetch files from various sources."""

import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import urlopen


def fetch_file(url, verbose=False):
  """Fetch a file from the specified source using the appropriate protocol.

  Returns:
    The contents of the file as bytes.
  """
  scheme = urlparse(url).scheme
  if scheme == 'gs':
    cmd = ['gsutil', 'cat', url]
    try:
      result = subprocess.run(
          cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
          check=True)
      if result.stderr and verbose:
        print('warning: non-fatal error running "gsutil": %s' % result.stderr,
              file=sys.stderr)
      return result.stdout
    except subprocess.CalledProcessError as e:
      print('fatal: error running "gsutil": %s' % e.stderr,
            file=sys.stderr)
    sys.exit(1)
  with urlopen(url) as f:
    return f.read()
