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

import os
import platform
import select

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
  class _Stream(object):
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
