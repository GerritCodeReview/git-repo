#!/usr/bin/env python
#
# Copyright (C) 2013 The Android Open Source Project
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

from __future__ import print_function
import sys

def is_python3():
  return sys.version_info[0] == 3

def check_python_version(min_version):
  ver = sys.version_info
  if ver[0] == 3:
    print('error: Python 3 support is not fully implemented in repo yet.\n'
          'Please use Python 2.6 - 2.7 instead.',
          file=sys.stderr)
    sys.exit(1)
  if (ver[0], ver[1]) < min_version:
    print('error: Python version %s unsupported.\n'
          'Please use Python 2.6 - 2.7 instead.'
          % sys.version.split(' ')[0], file=sys.stderr)
    sys.exit(1)
