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
import os
import platform
import select
import shutil
import stat

from pyversion import is_python3
if is_python3():
  from queue import Queue
else:
  from Queue import Queue

from threading import Thread


def isWindows():
  """ Returns True when running with the native port of Python for Windows,
  False when running on any other platform (including the Cygwin port of
  Python).
  """
  # Note: The cygwin port of Python returns "CYGWIN_NT_xxx"
  return platform.system() == "Windows"


class FileDescriptorStreams(object):
  """ Platform agnostic abstraction enabling non-blocking I/O over a
  collection of file descriptors. This abstraction is required because
  fctnl(os.O_NONBLOCK) is not supported on Windows.
  """
  @classmethod
  def create(cls):
    """ Factory method: instantiates the concrete class according to the
    current platform.
    """
    if isWindows():
      return _FileDescriptorStreamsThreads()
    else:
      return _FileDescriptorStreamsNonBlocking()

  def __init__(self):
    self.streams = []

  def add(self, fd, dest, std_name):
    """ Wraps an existing file descriptor as a stream.
    """
    self.streams.append(self._create_stream(fd, dest, std_name))

  def remove(self, stream):
    """ Removes a stream, when done with it.
    """
    self.streams.remove(stream)

  @property
  def is_done(self):
    """ Returns True when all streams have been processed.
    """
    return len(self.streams) == 0

  def select(self):
    """ Returns the set of streams that have data available to read.
    The returned streams each expose a read() and a close() method.
    When done with a stream, call the remove(stream) method.
    """
    raise NotImplementedError

  def _create_stream(self, fd, dest, std_name):
    """ Creates a new stream wrapping an existing file descriptor.
    """
    raise NotImplementedError


class _FileDescriptorStreamsNonBlocking(FileDescriptorStreams):
  """ Implementation of FileDescriptorStreams for platforms that support
  non blocking I/O.
  """
  def __init__(self):
    super(_FileDescriptorStreamsNonBlocking, self).__init__()
    self._poll = select.poll()
    self._fd_to_stream = {}

  class Stream(object):
    """ Encapsulates a file descriptor """

    def __init__(self, fd, dest, std_name):
      self.fd = fd
      self.dest = dest
      self.std_name = std_name
      self.set_non_blocking()

    def set_non_blocking(self):
      import fcntl
      flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
      fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def fileno(self):
      return self.fd.fileno()

    def read(self):
      return self.fd.read(4096)

    def close(self):
      self.fd.close()

  def _create_stream(self, fd, dest, std_name):
    stream = self.Stream(fd, dest, std_name)
    self._fd_to_stream[stream.fileno()] = stream
    self._poll.register(stream, select.POLLIN)
    return stream

  def remove(self, stream):
    self._poll.unregister(stream)
    del self._fd_to_stream[stream.fileno()]
    super(_FileDescriptorStreamsNonBlocking, self).remove(stream)

  def select(self):
    return [self._fd_to_stream[fd] for fd, _ in self._poll.poll()]


class _FileDescriptorStreamsThreads(FileDescriptorStreams):
  """ Implementation of FileDescriptorStreams for platforms that don't support
  non blocking I/O. This implementation requires creating threads issuing
  blocking read operations on file descriptors.
  """

  def __init__(self):
    super(_FileDescriptorStreamsThreads, self).__init__()
    # The queue is shared accross all threads so we can simulate the
    # behavior of the select() function
    self.queue = Queue(10)  # Limit incoming data from streams

  def _create_stream(self, fd, dest, std_name):
    return self.Stream(fd, dest, std_name, self.queue)

  def select(self):
    # Return only one stream at a time, as it is the most straighforward
    # thing to do and it is compatible with the select() function.
    item = self.queue.get()
    stream = item.stream
    stream.data = item.data
    return [stream]

  class QueueItem(object):
    """ Item put in the shared queue """

    def __init__(self, stream, data):
      self.stream = stream
      self.data = data

  class Stream(object):
    """ Encapsulates a file descriptor """

    def __init__(self, fd, dest, std_name, queue):
      self.fd = fd
      self.dest = dest
      self.std_name = std_name
      self.queue = queue
      self.data = None
      self.thread = Thread(target=self.read_to_queue)
      self.thread.daemon = True
      self.thread.start()

    def close(self):
      self.fd.close()

    def read(self):
      data = self.data
      self.data = None
      return data

    def read_to_queue(self):
      """ The thread function: reads everything from the file descriptor into
      the shared queue and terminates when reaching EOF.
      """
      for line in iter(self.fd.readline, b''):
        self.queue.put(_FileDescriptorStreamsThreads.QueueItem(self, line))
      self.fd.close()
      self.queue.put(_FileDescriptorStreamsThreads.QueueItem(self, b''))


def symlink(source, link_name):
  """Creates a symbolic link pointing to source named link_name.
  Note: On Windows, source must exist on disk, as the implementation needs
  to know whether to create a "File" or a "Directory" symbolic link.
  """
  if isWindows():
    import platform_utils_win32
    source = _validate_winpath(source)
    link_name = _validate_winpath(link_name)
    target = os.path.join(os.path.dirname(link_name), source)
    if isdir(target):
      platform_utils_win32.create_dirsymlink(_makelongpath(source), link_name)
    else:
      platform_utils_win32.create_filesymlink(_makelongpath(source), link_name)
  else:
    return os.symlink(source, link_name)


def _validate_winpath(path):
  path = os.path.normpath(path)
  if _winpath_is_valid(path):
    return path
  raise ValueError("Path \"%s\" must be a relative path or an absolute "
                   "path starting with a drive letter".format(path))


def _winpath_is_valid(path):
  """Windows only: returns True if path is relative (e.g. ".\\foo") or is
  absolute including a drive letter (e.g. "c:\\foo"). Returns False if path
  is ambiguous (e.g. "x:foo" or "\\foo").
  """
  assert isWindows()
  path = os.path.normpath(path)
  drive, tail = os.path.splitdrive(path)
  if tail:
    if not drive:
      return tail[0] != os.sep  # "\\foo" is invalid
    else:
      return tail[0] == os.sep  # "x:foo" is invalid
  else:
    return not drive  # "x:" is invalid


def _makelongpath(path):
  """Return the input path normalized to support the Windows long path syntax
  ("\\\\?\\" prefix) if needed, i.e. if the input path is longer than the
  MAX_PATH limit.
  """
  if isWindows():
    # Note: MAX_PATH is 260, but, for directories, the maximum value is actually 246.
    if len(path) < 246:
      return path
    if path.startswith(u"\\\\?\\"):
      return path
    if not os.path.isabs(path):
      return path
    # Append prefix and ensure unicode so that the special longpath syntax
    # is supported by underlying Win32 API calls
    return u"\\\\?\\" + os.path.normpath(path)
  else:
    return path


def rmtree(path, ignore_errors=False):
  """shutil.rmtree(path) wrapper with support for long paths on Windows.

  Availability: Unix, Windows."""
  onerror = None
  if isWindows():
    path = _makelongpath(path)
    onerror = handle_rmtree_error
  shutil.rmtree(path, ignore_errors=ignore_errors, onerror=onerror)


def handle_rmtree_error(function, path, excinfo):
  # Allow deleting read-only files
  os.chmod(path, stat.S_IWRITE)
  function(path)


def rename(src, dst):
  """os.rename(src, dst) wrapper with support for long paths on Windows.

  Availability: Unix, Windows."""
  if isWindows():
    # On Windows, rename fails if destination exists, see
    # https://docs.python.org/2/library/os.html#os.rename
    try:
      os.rename(_makelongpath(src), _makelongpath(dst))
    except OSError as e:
      if e.errno == errno.EEXIST:
        os.remove(_makelongpath(dst))
        os.rename(_makelongpath(src), _makelongpath(dst))
      else:
        raise
  else:
    os.rename(src, dst)


def remove(path):
  """Remove (delete) the file path. This is a replacement for os.remove that
  allows deleting read-only files on Windows, with support for long paths and
  for deleting directory symbolic links.

  Availability: Unix, Windows."""
  if isWindows():
    longpath = _makelongpath(path)
    try:
      os.remove(longpath)
    except OSError as e:
      if e.errno == errno.EACCES:
        os.chmod(longpath, stat.S_IWRITE)
        # Directory symbolic links must be deleted with 'rmdir'.
        if islink(longpath) and isdir(longpath):
          os.rmdir(longpath)
        else:
          os.remove(longpath)
      else:
        raise
  else:
    os.remove(path)


def walk(top, topdown=True, onerror=None, followlinks=False):
  """os.walk(path) wrapper with support for long paths on Windows.

  Availability: Windows, Unix.
  """
  if isWindows():
    return _walk_windows_impl(top, topdown, onerror, followlinks)
  else:
    return os.walk(top, topdown, onerror, followlinks)


def _walk_windows_impl(top, topdown, onerror, followlinks):
  try:
    names = listdir(top)
  except Exception as err:
    if onerror is not None:
      onerror(err)
    return

  dirs, nondirs = [], []
  for name in names:
    if isdir(os.path.join(top, name)):
      dirs.append(name)
    else:
      nondirs.append(name)

  if topdown:
    yield top, dirs, nondirs
  for name in dirs:
    new_path = os.path.join(top, name)
    if followlinks or not islink(new_path):
      for x in _walk_windows_impl(new_path, topdown, onerror, followlinks):
        yield x
  if not topdown:
    yield top, dirs, nondirs


def listdir(path):
  """os.listdir(path) wrapper with support for long paths on Windows.

  Availability: Windows, Unix.
  """
  return os.listdir(_makelongpath(path))


def rmdir(path):
  """os.rmdir(path) wrapper with support for long paths on Windows.

  Availability: Windows, Unix.
  """
  os.rmdir(_makelongpath(path))


def isdir(path):
  """os.path.isdir(path) wrapper with support for long paths on Windows.

  Availability: Windows, Unix.
  """
  return os.path.isdir(_makelongpath(path))


def islink(path):
  """os.path.islink(path) wrapper with support for long paths on Windows.

  Availability: Windows, Unix.
  """
  if isWindows():
    import platform_utils_win32
    return platform_utils_win32.islink(_makelongpath(path))
  else:
    return os.path.islink(path)


def readlink(path):
  """Return a string representing the path to which the symbolic link
  points. The result may be either an absolute or relative pathname;
  if it is relative, it may be converted to an absolute pathname using
  os.path.join(os.path.dirname(path), result).

  Availability: Windows, Unix.
  """
  if isWindows():
    import platform_utils_win32
    return platform_utils_win32.readlink(_makelongpath(path))
  else:
    return os.readlink(path)


def realpath(path):
  """Return the canonical path of the specified filename, eliminating
  any symbolic links encountered in the path.

  Availability: Windows, Unix.
  """
  if isWindows():
    current_path = os.path.abspath(path)
    path_tail = []
    for c in range(0, 100):  # Avoid cycles
      if islink(current_path):
        target = readlink(current_path)
        current_path = os.path.join(os.path.dirname(current_path), target)
      else:
        basename = os.path.basename(current_path)
        if basename == '':
          path_tail.append(current_path)
          break
        path_tail.append(basename)
        current_path = os.path.dirname(current_path)
    path_tail.reverse()
    result = os.path.normpath(os.path.join(*path_tail))
    return result
  else:
    return os.path.realpath(path)
