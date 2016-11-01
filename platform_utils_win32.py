#
# Copyright (C) 2016 The Android Open Source Project
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

import errno

from ctypes import WinDLL, get_last_error, FormatError, WinError
from ctypes.wintypes import BOOL, LPCWSTR, DWORD

kernel32 = WinDLL('kernel32', use_last_error=True)

# Win32 error codes
ERROR_SUCCESS = 0
ERROR_PRIVILEGE_NOT_HELD = 1314

# Win32 API entry points
CreateSymbolicLinkW = kernel32.CreateSymbolicLinkW
CreateSymbolicLinkW.restype = BOOL
CreateSymbolicLinkW.argtypes = (LPCWSTR,  # lpSymlinkFileName In
                                LPCWSTR,  # lpTargetFileName In
                                DWORD)    # dwFlags In

# Symbolic link creation flags
SYMBOLIC_LINK_FLAG_FILE = 0x00
SYMBOLIC_LINK_FLAG_DIRECTORY = 0x01


def create_filesymlink(source, link_name):
  """Creates a Windows file symbolic link source pointing to link_name."""
  _create_symlink(source, link_name, SYMBOLIC_LINK_FLAG_FILE)


def create_dirsymlink(source, link_name):
  """Creates a Windows directory symbolic link source pointing to link_name.
  """
  _create_symlink(source, link_name, SYMBOLIC_LINK_FLAG_DIRECTORY)


def _create_symlink(source, link_name, dwFlags):
  # Note: Win32 documentation for CreateSymbolicLink is incorrect.
  # On success, the function returns "1".
  # On error, the function returns some random value (e.g. 1280).
  # The best bet seems to use "GetLastError" and check for error/success.
  CreateSymbolicLinkW(link_name, source, dwFlags)
  code = get_last_error()
  if code != ERROR_SUCCESS:
    error_desc = FormatError(code).strip()
    if code == ERROR_PRIVILEGE_NOT_HELD:
      raise OSError(errno.EPERM, error_desc, link_name)
    error_desc = 'Error creating symbolic link %s: %s'.format(
        link_name, error_desc)
    raise WinError(code, error_desc)
