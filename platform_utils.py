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

  def _create_stream(fd, dest, std_name):
    """ Creates a new stream wrapping an existing file descriptor.
    """
    raise NotImplementedError


class _FileDescriptorStreamsNonBlocking(FileDescriptorStreams):
  """ Implementation of FileDescriptorStreams for platforms that support
  non blocking I/O.
  """
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
    return self.Stream(fd, dest, std_name)

  def select(self):
    ready_streams, _, _ = select.select(self.streams, [], [])
    return ready_streams


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
      self.queue.put(_FileDescriptorStreamsThreads.QueueItem(self, None))


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
    if os.path.isdir(target):
      platform_utils_win32.create_dirsymlink(source, link_name)
    else:
      platform_utils_win32.create_filesymlink(source, link_name)
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


def rmtree(path):
  if isWindows():
    shutil.rmtree(path, onerror=handle_rmtree_error)
  else:
    shutil.rmtree(path)


def handle_rmtree_error(function, path, excinfo):
  # Allow deleting read-only files
  os.chmod(path, stat.S_IWRITE)
  function(path)


def rename(src, dst):
  if isWindows():
    # On Windows, rename fails if destination exists, see
    # https://docs.python.org/2/library/os.html#os.rename
    try:
      os.rename(src, dst)
    except OSError as e:
      if e.errno == errno.EEXIST:
        os.remove(dst)
        os.rename(src, dst)
      else:
        raise
  else:
    os.rename(src, dst)


def remove(path):
  """Remove (delete) the file path. This is a replacement for os.remove, but
  allows deleting read-only files on Windows.
  """
  if isWindows():
    try:
      os.remove(path)
    except OSError as e:
      if e.errno == errno.EACCES:
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)
      else:
        raise
  else:
    os.remove(path)


def islink(path):
  """Test whether a path is a symbolic link.

  Availability: Windows, Unix.
  """
  if isWindows():
    import platform_utils_win32
    return platform_utils_win32.islink(path)
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
    return platform_utils_win32.readlink(path)
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
