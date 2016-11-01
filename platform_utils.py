#
# Copyright (C) 2008 The Android Open Source Project
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
  """ Return true if running with the native port of python for Windows,
  false if running on any other platform (including the Cygwin port).
  """
  # Note: The cygwin port of Python returns "CYGWIN_NT_xxx"
  return platform.system() == "Windows"


class FileDescriptorStreams(object):
  @classmethod
  def create(cls):
    if isWindows():
      return FileDescriptorStreamsThreads()
    else:
      return FileDescriptorStreamsNonBlocking()

  def __init__(self):
    self.streams = []

  def add(self, fd, dest, std_name):
    self.streams.append(self.create_stream(fd, dest, std_name))

  def remove(self, stream):
    self.streams.remove(stream)

  @property
  def is_done(self):
    return len(self.streams) == 0

  def select(self):
    raise NotImplementedError

  def create_stream(fd, dest, std_name):
    raise NotImplementedError


class FileDescriptorStreamsNonBlocking(FileDescriptorStreams):
  class Stream(object):
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

  def create_stream(self, fd, dest, std_name):
    return self.Stream(fd, dest, std_name)

  def select(self):
    ready_streams, _, _ = select.select(self.streams, [], [])
    return ready_streams


class FileDescriptorStreamsThreads(FileDescriptorStreams):
  def __init__(self):
    super(FileDescriptorStreamsThreads, self).__init__()
    self.queue = Queue(10)  # Limit incoming data from streams

  def create_stream(self, fd, dest, std_name):
    return self.Stream(fd, dest, std_name, self.queue)

  def select(self):
    item = self.queue.get()
    stream = item.stream
    stream.data = item.data
    return [stream]

  class QueueItem(object):
    def __init__(self, stream, data):
      self.stream = stream
      self.data = data

  class Stream(object):
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
      for line in iter(self.fd.readline, b''):
        self.queue.put(FileDescriptorStreamsThreads.QueueItem(self, line))
      self.queue.put(FileDescriptorStreamsThreads.QueueItem(self, None))
