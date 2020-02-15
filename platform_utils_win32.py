# -*- coding:utf-8 -*-
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

from pyversion import is_python3
from ctypes import WinDLL, get_last_error, FormatError, WinError, addressof
from ctypes import c_buffer
from ctypes.wintypes import BOOL, BOOLEAN, LPCWSTR, DWORD, HANDLE
from ctypes.wintypes import WCHAR, USHORT, LPVOID, ULONG
if is_python3():
  from ctypes import c_ubyte, Structure, Union, byref
  from ctypes.wintypes import LPDWORD
else:
  # For legacy Python2 different imports are needed.
  from ctypes.wintypes import POINTER, c_ubyte, Structure, Union, byref
  LPDWORD = POINTER(DWORD)

kernel32 = WinDLL('kernel32', use_last_error=True)

UCHAR = c_ubyte

# Win32 error codes
ERROR_SUCCESS = 0
ERROR_NOT_SUPPORTED = 50
ERROR_PRIVILEGE_NOT_HELD = 1314

# Win32 API entry points
CreateSymbolicLinkW = kernel32.CreateSymbolicLinkW
CreateSymbolicLinkW.restype = BOOLEAN
CreateSymbolicLinkW.argtypes = (LPCWSTR,  # lpSymlinkFileName In
                                LPCWSTR,  # lpTargetFileName In
                                DWORD)    # dwFlags In

# Symbolic link creation flags
SYMBOLIC_LINK_FLAG_FILE = 0x00
SYMBOLIC_LINK_FLAG_DIRECTORY = 0x01
# symlink support for CreateSymbolicLink() starting with Windows 10 (1703, v10.0.14972)
SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE = 0x02

GetFileAttributesW = kernel32.GetFileAttributesW
GetFileAttributesW.restype = DWORD
GetFileAttributesW.argtypes = (LPCWSTR,)  # lpFileName In

INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_ATTRIBUTE_REPARSE_POINT = 0x00400

CreateFileW = kernel32.CreateFileW
CreateFileW.restype = HANDLE
CreateFileW.argtypes = (LPCWSTR,  # lpFileName In
                        DWORD,    # dwDesiredAccess In
                        DWORD,    # dwShareMode In
                        LPVOID,   # lpSecurityAttributes In_opt
                        DWORD,    # dwCreationDisposition In
                        DWORD,    # dwFlagsAndAttributes In
                        HANDLE)   # hTemplateFile In_opt

CloseHandle = kernel32.CloseHandle
CloseHandle.restype = BOOL
CloseHandle.argtypes = (HANDLE,)  # hObject In

INVALID_HANDLE_VALUE = HANDLE(-1).value
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

DeviceIoControl = kernel32.DeviceIoControl
DeviceIoControl.restype = BOOL
DeviceIoControl.argtypes = (HANDLE,   # hDevice In
                            DWORD,    # dwIoControlCode In
                            LPVOID,   # lpInBuffer In_opt
                            DWORD,    # nInBufferSize In
                            LPVOID,   # lpOutBuffer Out_opt
                            DWORD,    # nOutBufferSize In
                            LPDWORD,  # lpBytesReturned Out_opt
                            LPVOID)   # lpOverlapped Inout_opt

# Device I/O control flags and options
FSCTL_GET_REPARSE_POINT = 0x000900A8
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C
MAXIMUM_REPARSE_DATA_BUFFER_SIZE = 0x4000


class GENERIC_REPARSE_BUFFER(Structure):
  _fields_ = (('DataBuffer', UCHAR * 1),)


class SYMBOLIC_LINK_REPARSE_BUFFER(Structure):
  _fields_ = (('SubstituteNameOffset', USHORT),
              ('SubstituteNameLength', USHORT),
              ('PrintNameOffset', USHORT),
              ('PrintNameLength', USHORT),
              ('Flags', ULONG),
              ('PathBuffer', WCHAR * 1))

  @property
  def PrintName(self):
    arrayt = WCHAR * (self.PrintNameLength // 2)
    offset = type(self).PathBuffer.offset + self.PrintNameOffset
    return arrayt.from_address(addressof(self) + offset).value


class MOUNT_POINT_REPARSE_BUFFER(Structure):
  _fields_ = (('SubstituteNameOffset', USHORT),
              ('SubstituteNameLength', USHORT),
              ('PrintNameOffset', USHORT),
              ('PrintNameLength', USHORT),
              ('PathBuffer', WCHAR * 1))

  @property
  def PrintName(self):
    arrayt = WCHAR * (self.PrintNameLength // 2)
    offset = type(self).PathBuffer.offset + self.PrintNameOffset
    return arrayt.from_address(addressof(self) + offset).value


class REPARSE_DATA_BUFFER(Structure):
  class REPARSE_BUFFER(Union):
    _fields_ = (('SymbolicLinkReparseBuffer', SYMBOLIC_LINK_REPARSE_BUFFER),
                ('MountPointReparseBuffer', MOUNT_POINT_REPARSE_BUFFER),
                ('GenericReparseBuffer', GENERIC_REPARSE_BUFFER))
  _fields_ = (('ReparseTag', ULONG),
              ('ReparseDataLength', USHORT),
              ('Reserved', USHORT),
              ('ReparseBuffer', REPARSE_BUFFER))
  _anonymous_ = ('ReparseBuffer',)


def create_filesymlink(source, link_name):
  """Creates a Windows file symbolic link source pointing to link_name."""
  _create_symlink(source, link_name, SYMBOLIC_LINK_FLAG_FILE)


def create_dirsymlink(source, link_name):
  """Creates a Windows directory symbolic link source pointing to link_name.
  """
  _create_symlink(source, link_name, SYMBOLIC_LINK_FLAG_DIRECTORY)


def _create_symlink(source, link_name, dwFlags):
  if not CreateSymbolicLinkW(link_name, source,
                             dwFlags | SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE):
    # See https://github.com/golang/go/pull/24307/files#diff-b87bc12e4da2497308f9ef746086e4f0
    # "the unprivileged create flag is unsupported below Windows 10 (1703, v10.0.14972).
    # retry without it."
    if not CreateSymbolicLinkW(link_name, source, dwFlags):
      code = get_last_error()
      error_desc = FormatError(code).strip()
      if code == ERROR_PRIVILEGE_NOT_HELD:
        raise OSError(errno.EPERM, error_desc, link_name)
      _raise_winerror(
          code,
          'Error creating symbolic link \"%s\"'.format(link_name))


def islink(path):
  result = GetFileAttributesW(path)
  if result == INVALID_FILE_ATTRIBUTES:
    return False
  return bool(result & FILE_ATTRIBUTE_REPARSE_POINT)


def readlink(path):
  reparse_point_handle = CreateFileW(path,
                                     0,
                                     0,
                                     None,
                                     OPEN_EXISTING,
                                     FILE_FLAG_OPEN_REPARSE_POINT |
                                     FILE_FLAG_BACKUP_SEMANTICS,
                                     None)
  if reparse_point_handle == INVALID_HANDLE_VALUE:
    _raise_winerror(
        get_last_error(),
        'Error opening symbolic link \"%s\"'.format(path))
  target_buffer = c_buffer(MAXIMUM_REPARSE_DATA_BUFFER_SIZE)
  n_bytes_returned = DWORD()
  io_result = DeviceIoControl(reparse_point_handle,
                              FSCTL_GET_REPARSE_POINT,
                              None,
                              0,
                              target_buffer,
                              len(target_buffer),
                              byref(n_bytes_returned),
                              None)
  CloseHandle(reparse_point_handle)
  if not io_result:
    _raise_winerror(
        get_last_error(),
        'Error reading symbolic link \"%s\"'.format(path))
  rdb = REPARSE_DATA_BUFFER.from_buffer(target_buffer)
  if rdb.ReparseTag == IO_REPARSE_TAG_SYMLINK:
    return _preserve_encoding(path, rdb.SymbolicLinkReparseBuffer.PrintName)
  elif rdb.ReparseTag == IO_REPARSE_TAG_MOUNT_POINT:
    return _preserve_encoding(path, rdb.MountPointReparseBuffer.PrintName)
  # Unsupported reparse point type
  _raise_winerror(
      ERROR_NOT_SUPPORTED,
      'Error reading symbolic link \"%s\"'.format(path))


def _preserve_encoding(source, target):
  """Ensures target is the same string type (i.e. unicode or str) as source."""

  if is_python3():
    return target

  if isinstance(source, unicode):  # noqa: F821
    return unicode(target)  # noqa: F821
  return str(target)


def _raise_winerror(code, error_desc):
  win_error_desc = FormatError(code).strip()
  error_desc = "%s: %s".format(error_desc, win_error_desc)
  raise WinError(code, error_desc)
