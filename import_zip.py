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

import stat
import struct
import zlib
import cStringIO

from import_ext import ImportExternal
from error import ImportError

class ImportZip(ImportExternal):
  """Streams a zip file from the network directly into a Project's
     Git repository.
  """
  @classmethod
  def CanAccept(cls, url):
    """Can this importer read and unpack the data stored at url?
    """
    if url.endswith('.zip') or url.endswith('.jar'):
      return True
    return False

  def _UnpackFiles(self):
    url_fd, url = self._OpenUrl()
    try:
      if not self.__class__.CanAccept(url):
        raise ImportError('non-zip file extension: %s' % url)

      zip = _ZipFile(url_fd)
      for entry in zip.FileRecords():
        data = zip.Open(entry).read()
        sz = len(data)

        if data and _SafeCRLF(data):
          data = data.replace('\r\n', '\n')
          sz = len(data)

        fd = cStringIO.StringIO(data)
        self._UnpackOneFile(entry.mode, sz, entry.name, fd)
        zip.Close(entry)

      for entry in zip.CentralDirectory():
        self._SetFileMode(entry.name, entry.mode)

      zip.CheckTail()
    finally:
      url_fd.close()


def _SafeCRLF(data):
  """Is it reasonably safe to perform a CRLF->LF conversion?

     If the stream contains a NUL byte it is likely binary,
     and thus a CRLF->LF conversion may damage the stream.

     If the only NUL is in the last position of the stream,
     but it otherwise can do a CRLF<->LF conversion we do
     the CRLF conversion anyway.  At least one source ZIP
     file has this structure in its source code.

     If every occurrance of a CR and LF is paired up as a
     CRLF pair then the conversion is safely bi-directional.
     s/\r\n/\n/g == s/\n/\r\\n/g can convert between them.
  """
  nul = data.find('\0')
  if 0 <= nul and nul < (len(data) - 1):
    return False

  n_lf = 0
  last = 0
  while True:
    lf = data.find('\n', last)
    if lf < 0:
      break
    if lf == 0 or data[lf - 1] != '\r':
      return False
    last = lf + 1
    n_lf += 1
  return n_lf > 0

class _ZipFile(object):
  """Streaming iterator to parse a zip file on the fly.
  """
  def __init__(self, fd):
    self._fd = _UngetStream(fd)

  def FileRecords(self):
    return _FileIter(self._fd)

  def CentralDirectory(self):
    return _CentIter(self._fd)

  def CheckTail(self):
    type_buf = self._fd.read(4)
    type = struct.unpack('<I', type_buf)[0]
    if type != 0x06054b50:  # end of central directory
      raise ImportError('zip record %x unsupported' % type)

  def Open(self, entry):
    if entry.is_compressed:
      return _InflateStream(self._fd)
    else:
      if entry.has_trailer:
        raise ImportError('unable to extract streamed zip')
      return _FixedLengthStream(self._fd, entry.uncompressed_size)

  def Close(self, entry):
    if entry.has_trailer:
      type = struct.unpack('<I', self._fd.read(4))[0]
      if type == 0x08074b50:
        # Not a formal type marker, but commonly seen in zips
        # as the data descriptor signature.
        #
        struct.unpack('<3I', self._fd.read(12))
      else:
        # No signature for the data descriptor, so read the
        # remaining fields out of the stream
        #
        self._fd.read(8)


class _FileIter(object):
  def __init__(self, fd):
    self._fd = fd

  def __iter__(self):
    return self

  def next(self):
    fd = self._fd

    type_buf = fd.read(4)
    type = struct.unpack('<I', type_buf)[0]

    if type != 0x04034b50:    # local file header
      fd.unread(type_buf)
      raise StopIteration()

    rec = _FileHeader(fd.read(26))
    rec.name = fd.read(rec.name_len)
    fd.read(rec.extra_len)

    if rec.name.endswith('/'):
      rec.name = rec.name[:-1]
      rec.mode = stat.S_IFDIR | 0777
    return rec


class _FileHeader(object):
  """Information about a single file in the archive.
     0  version needed to extract       2 bytes
     1  general purpose bit flag        2 bytes
     2  compression method              2 bytes
     3  last mod file time              2 bytes
     4  last mod file date              2 bytes
     5  crc-32                          4 bytes
     6  compressed size                 4 bytes
     7  uncompressed size               4 bytes
     8  file name length                2 bytes
     9  extra field length              2 bytes
  """
  def __init__(self, raw_bin):
    rec = struct.unpack('<5H3I2H', raw_bin)
    
    if rec[2] == 8:
      self.is_compressed = True
    elif rec[2] == 0:
      self.is_compressed = False
    else:
      raise ImportError('unrecognized compression format')

    if rec[1] & (1 << 3):
      self.has_trailer = True
    else:
      self.has_trailer = False

    self.compressed_size  = rec[6]
    self.uncompressed_size = rec[7]
    self.name_len = rec[8]
    self.extra_len = rec[9]
    self.mode = stat.S_IFREG | 0644


class _CentIter(object):
  def __init__(self, fd):
    self._fd = fd

  def __iter__(self):
    return self

  def next(self):
    fd = self._fd

    type_buf = fd.read(4)
    type = struct.unpack('<I', type_buf)[0]

    if type != 0x02014b50:  # central directory
      fd.unread(type_buf)
      raise StopIteration()

    rec = _CentHeader(fd.read(42))
    rec.name = fd.read(rec.name_len)
    fd.read(rec.extra_len)
    fd.read(rec.comment_len)

    if rec.name.endswith('/'):
      rec.name = rec.name[:-1]
      rec.mode = stat.S_IFDIR | 0777
    return rec


class _CentHeader(object):
  """Information about a single file in the archive.
     0  version made by                 2 bytes
     1  version needed to extract       2 bytes
     2  general purpose bit flag        2 bytes
     3  compression method              2 bytes
     4  last mod file time              2 bytes
     5  last mod file date              2 bytes
     6  crc-32                          4 bytes
     7  compressed size                 4 bytes
     8  uncompressed size               4 bytes
     9  file name length                2 bytes
    10  extra field length              2 bytes
    11  file comment length             2 bytes
    12  disk number start               2 bytes
    13  internal file attributes        2 bytes
    14  external file attributes        4 bytes
    15  relative offset of local header 4 bytes
  """
  def __init__(self, raw_bin):
    rec = struct.unpack('<6H3I5H2I', raw_bin)
    self.name_len = rec[9]
    self.extra_len = rec[10]
    self.comment_len = rec[11]

    if (rec[0] & 0xff00) == 0x0300:  # UNIX
      self.mode = rec[14] >> 16
    else:
      self.mode = stat.S_IFREG | 0644


class _UngetStream(object):
  """File like object to read and rewind a stream.
  """
  def __init__(self, fd):
    self._fd = fd
    self._buf = None

  def read(self, size = -1):
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
      return r[0]
    return ''.join(r)

  def unread(self, buf):
    b = self._buf
    if b is None or len(b) == 0:
      self._buf = buf
    else:
      self._buf = buf + b

  def _ReadChunk(self, r, size):
    b = self._buf
    try:
      while size > 0:
        if b is None or len(b) == 0:
          b = self._Inflate(self._fd.read(2048))
          if not b:
            raise EOFError()
          continue

        use = min(size, len(b))
        r.append(b[:use])
        b = b[use:]
        size -= use
    finally:
      self._buf = b

  def _Inflate(self, b):
    return b


class _FixedLengthStream(_UngetStream):
  """File like object to read a fixed length stream.
  """
  def __init__(self, fd, have):
    _UngetStream.__init__(self, fd)
    self._have = have

  def _Inflate(self, b):
    n = self._have
    if n == 0:
      self._fd.unread(b)
      return None

    if len(b) > n:
      self._fd.unread(b[n:])
      b = b[:n]
    self._have -= len(b)
    return b


class _InflateStream(_UngetStream):
  """Inflates the stream as it reads input.
  """
  def __init__(self, fd):
    _UngetStream.__init__(self, fd)
    self._z = zlib.decompressobj(-zlib.MAX_WBITS)

  def _Inflate(self, b):
    z = self._z
    if not z:
      self._fd.unread(b)
      return None

    b = z.decompress(b)
    if z.unconsumed_tail != '':
      self._fd.unread(z.unconsumed_tail)
    elif z.unused_data != '':
      self._fd.unread(z.unused_data)
      self._z = None
    return b
