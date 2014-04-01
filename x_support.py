#
# Copyright (C) 2015 The Android Open Source Project
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

# Module for detecting if external executables support the features we need,
# or can optionally disable.

import subprocess

# (<executable name>, (<parameter name>, <boolean supported>))
# e.g. {'curl': {'--proto-redir': True}}
_x_supports = {}


def in_output(cmd, check):
  """Checks if a string is in the output of a subprocess call
  """
  sp = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True)
  comm = sp.communicate()
  return check in comm[0] or check in comm[1]

# helper method to check output of `--help`
_check_help = lambda x, opt: in_output([x, '--help'], opt)


def x_supports(x, opt, check_method=_check_help):
  """Check if an executable supports a specified argument.

  Args:
    x (str): name of the executable to be checked.
    opt (str): name of the option to check if supported.
    check_method: callable which `x` and `opt` are passed to to
                  check for support. defaults to `_check_help`.
  Returns:
    Boolean whether the option is supported
  """
  global _x_supports
  x_support = _x_supports.get(x, {})
  if opt not in x_support:
    x_support[opt] = check_method(x, opt)
    _x_supports[x] = x_support
  return x_support.get(opt, False)

# helper method specific to curl
curl_supports = lambda opt: x_supports('curl', opt)