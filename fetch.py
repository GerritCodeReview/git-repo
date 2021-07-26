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

import subprocess
import sys

def fetch_standalone_manifest(manifest_uri):
    """Fetch a manifest from the specified source using the appropriate
        protocol.

        Returns: (str) the contents of the manifest.
    """
    if manifest_uri.startswith('gs://'):
        cmd = ['gsutil', 'cat', manifest_uri]
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True,
                universal_newlines=True)
            return res.stdout
        except subprocess.CalledProcessError as exc:
            print('fatal: error running "gsutil": %s' % exc.output,
                  file=sys.stderr)
            sys.exit(1)
    raise ValueError('unsupported uri')