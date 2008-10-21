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

import bz2
import stat
import tarfile
import zlib
import StringIO

from import_ext import ImportExternal
from error import ImportError

class ImportTar(ImportExternal):
  """Streams a (optionally compressed) tar file from the network
     directly into a Project's Git repository.
  """
  @classmethod
  def CanAccept(cls, url):
    """Can this importer read and unpack the data stored at url?
    """
    if url.endswith('.tar.gz') or url.endswith('.tgz'):
      return True
    if url.endswith('.tar.bz2'):
      return True
    if url.endswith('.tar'):
      return True
    return False

  def _UnpackFiles(self):
    url_fd, url = self._OpenUrl()
    try:
      if url.endswith('.tar.gz') or url.endswith('.tgz'):
        tar_fd = _Gzip(url_fd)
      elif url.endswith('.tar.bz2'):
        tar_fd = _Bzip2(url_fd)
      elif url.endswith('.tar'):
        tar_fd = _Raw(url_fd)
      else:
        raise ImportError('non-tar file extension: %s' % url)

      try:
        tar = tarfile.TarFile(name = url,
                              mode = 'r',
                              fileobj = tar_fd)
        try:
          for entry in tar:
            mode = entry.mode

            if (mode & 0170000) == 0:
              if entry.isdir():
                mode |= stat.S_IFDIR
              elif entry.isfile() or entry.islnk():  # hard links as files
                mode |= stat.S_IFREG
              elif entry.issym():
                mode |= stat.S_IFLNK

            if stat.S_ISLNK(mode):   # symlink
              data_fd = StringIO.StringIO(entry.linkname)
              data_sz = len(entry.linkname)
            elif stat.S_ISDIR(mode): # directory
              data_fd = StringIO.StringIO('')
              data_sz = 0
            else:
              data_fd = tar.extractfile(entry)
              data_sz = entry.size

            self._UnpackOneFile(mode, data_sz, entry.name, data_fd)
        finally:
          tar.close()
      finally:
        tar_fd.close()
    finally:
      url_fd.close()



class _DecompressStream(object):
  """file like object to decompress a tar stream
  """
  def __init__(self, fd):
    self._fd = fd
    self._pos = 0
    self._buf = None

  def tell(self):
    return self._pos

  def seek(self, offset):
    d = offset - self._pos
    if d > 0:
      self.read(d)
    elif d == 0:
      pass
    else:
      raise NotImplementedError, 'seek backwards'

  def close(self):
    self._fd = None

  def read(self, size = -1):
    if not self._fd:
      raise EOFError, 'Reached EOF'
    
    r = []
    try:
      if size >= 0:
        self._ReadChunk(r, size)
      else:
        while True:
          self._ReadChunk(r, 2048)
    except EOFError:
      pass

    if len(r) == 1:
      r = r[0]
    else:
      r = ''.join(r)
    self._pos += len(r)
    return r

  def _ReadChunk(self, r, size):
    b = self._buf
    try:
      while size > 0:
        if b is None or len(b) == 0:
          b = self._Decompress(self._fd.read(2048))
          continue

        use = min(size, len(b))
        r.append(b[:use])
        b = b[use:]
        size -= use
    finally:
      self._buf = b

  def _Decompress(self, b):
    raise NotImplementedError, '_Decompress'


class _Raw(_DecompressStream):
  """file like object for an uncompressed stream
  """
  def __init__(self, fd):
    _DecompressStream.__init__(self, fd)

  def _Decompress(self, b):
    return b


class _Bzip2(_DecompressStream):
  """file like object to decompress a .bz2 stream
  """
  def __init__(self, fd):
    _DecompressStream.__init__(self, fd)
    self._bz = bz2.BZ2Decompressor()

  def _Decompress(self, b):
    return self._bz.decompress(b)


_FHCRC, _FEXTRA, _FNAME, _FCOMMENT = 2, 4, 8, 16
class _Gzip(_DecompressStream):
  """file like object to decompress a .gz stream
  """
  def __init__(self, fd):
    _DecompressStream.__init__(self, fd)
    self._z = zlib.decompressobj(-zlib.MAX_WBITS)

    magic = fd.read(2)
    if magic != '\037\213':
      raise IOError, 'Not a gzipped file'

    method = ord(fd.read(1))
    if method != 8:
      raise IOError, 'Unknown compression method'

    flag = ord(fd.read(1))
    fd.read(6)

    if flag & _FEXTRA:
      xlen = ord(fd.read(1))
      xlen += 256 * ord(fd.read(1))
      fd.read(xlen)
    if flag & _FNAME:
      while fd.read(1) != '\0':
        pass
    if flag & _FCOMMENT:
      while fd.read(1) != '\0':
        pass
    if flag & _FHCRC:
      fd.read(2)

  def _Decompress(self, b):
    return self._z.decompress(b)
