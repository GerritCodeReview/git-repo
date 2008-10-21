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
import random
import stat
import sys
import urllib2
import StringIO

from error import GitError, ImportError
from git_command import GitCommand

class ImportExternal(object):
  """Imports a single revision from a non-git data source.
     Suitable for use to import a tar or zip based snapshot.
  """
  def __init__(self):
    self._marks = 0
    self._files = {}
    self._tempref = 'refs/repo-external/import'

    self._urls = []
    self._remap = []
    self.parent = None
    self._user_name = 'Upstream'
    self._user_email = 'upstream-import@none'
    self._user_when = 1000000

    self.commit = None

  def Clone(self):
    r = self.__class__()

    r.project = self.project
    for u in self._urls:
      r._urls.append(u)
    for p in self._remap:
      r._remap.append(_PathMap(r, p._old, p._new))

    return r

  def SetProject(self, project):
    self.project = project

  def SetVersion(self, version):
    self.version = version

  def AddUrl(self, url):
    self._urls.append(url)

  def SetParent(self, commit_hash):
    self.parent = commit_hash

  def SetCommit(self, commit_hash):
    self.commit = commit_hash

  def RemapPath(self, old, new, replace_version=True):
    self._remap.append(_PathMap(self, old, new))

  @property
  def TagName(self):
    v = ''
    for c in self.version:
      if c >= '0' and c <= '9':
        v += c
      elif c >= 'A' and c <= 'Z':
        v += c
      elif c >= 'a' and c <= 'z':
        v += c
      elif c in ('-', '_', '.', '/', '+', '@'):
        v += c
    return 'upstream/%s' % v

  @property
  def PackageName(self):
    n = self.project.name
    if n.startswith('platform/'):
      # This was not my finest moment...
      #
      n = n[len('platform/'):]
    return n

  def Import(self):
    self._need_graft = False
    if self.parent:
      try:
        self.project.bare_git.cat_file('-e', self.parent)
      except GitError:
        self._need_graft = True

    gfi = GitCommand(self.project,
                     ['fast-import', '--force', '--quiet'],
                     bare = True,
                     provide_stdin = True)
    try:
      self._out = gfi.stdin

      try:
        self._UnpackFiles()
        self._MakeCommit()
        self._out.flush()
      finally:
        rc = gfi.Wait()
      if rc != 0:
        raise ImportError('fast-import failed')

      if self._need_graft:
        id = self._GraftCommit()
      else:
        id = self.project.bare_git.rev_parse('%s^0' % self._tempref)

      if self.commit and self.commit != id:
        raise ImportError('checksum mismatch: %s expected,'
                          ' %s imported' % (self.commit, id))

      self._MakeTag(id)
      return id
    finally:
      try:
        self.project.bare_git.DeleteRef(self._tempref)
      except GitError:
        pass

  def _PickUrl(self, failed):
    u = map(lambda x: x.replace('%version%', self.version), self._urls)
    for f in failed:
      if f in u:
        u.remove(f)
    if len(u) == 0:
      return None
    return random.choice(u)

  def _OpenUrl(self):
    failed = {}
    while True:
      url = self._PickUrl(failed.keys())
      if url is None:
        why = 'Cannot download %s' % self.project.name

        if failed:
          why += ': one or more mirrors are down\n'
          bad_urls = list(failed.keys())
          bad_urls.sort()
          for url in bad_urls:
            why += '  %s: %s\n' % (url, failed[url])
        else:
          why += ': no mirror URLs'
        raise ImportError(why)

      print >>sys.stderr, "Getting %s ..." % url
      try:
        return urllib2.urlopen(url), url
      except urllib2.HTTPError, e:
        failed[url] = e.code
      except urllib2.URLError, e:
        failed[url] = e.reason[1]
      except OSError, e:
        failed[url] = e.strerror

  def _UnpackFiles(self):
    raise NotImplementedError

  def _NextMark(self):
    self._marks += 1
    return self._marks

  def _UnpackOneFile(self, mode, size, name, fd):
    if stat.S_ISDIR(mode):    # directory
      return
    else:
      mode = self._CleanMode(mode, name)

    old_name = name
    name = self._CleanName(name)

    if stat.S_ISLNK(mode) and self._remap:
      # The link is relative to the old_name, and may need to
      # be rewritten according to our remap rules if it goes
      # up high enough in the tree structure.
      #
      dest = self._RewriteLink(fd.read(size), old_name, name)
      fd = StringIO.StringIO(dest)
      size = len(dest)

    fi = _File(mode, name, self._NextMark())

    self._out.write('blob\n')
    self._out.write('mark :%d\n' % fi.mark)
    self._out.write('data %d\n' % size)
    while size > 0:
      n = min(2048, size)
      self._out.write(fd.read(n))
      size -= n
    self._out.write('\n')
    self._files[fi.name] = fi

  def _SetFileMode(self, name, mode):
    if not stat.S_ISDIR(mode):
      mode = self._CleanMode(mode, name)
      name = self._CleanName(name)
      try:
        fi = self._files[name]
      except KeyError:
        raise ImportError('file %s was not unpacked' % name)
      fi.mode = mode

  def _RewriteLink(self, dest, relto_old, relto_new):
    # Drop the last components of the symlink itself
    # as the dest is relative to the directory its in.
    #
    relto_old = _TrimPath(relto_old)
    relto_new = _TrimPath(relto_new)

    # Resolve the link to be absolute from the top of
    # the archive, so we can remap its destination.
    #
    while dest.find('/./') >= 0 or dest.find('//') >= 0:
      dest = dest.replace('/./', '/')
      dest = dest.replace('//', '/')

    if dest.startswith('../') or dest.find('/../') > 0:
      dest = _FoldPath('%s/%s' % (relto_old, dest))

    for pm in self._remap:
      if pm.Matches(dest):
        dest = pm.Apply(dest)
        break

    dest, relto_new = _StripCommonPrefix(dest, relto_new)
    while relto_new:
      i = relto_new.find('/')
      if i > 0:
        relto_new = relto_new[i + 1:]
      else:
        relto_new = ''
      dest = '../' + dest
    return dest

  def _CleanMode(self, mode, name):
    if stat.S_ISREG(mode):  # regular file
      if (mode & 0111) == 0:
        return 0644
      else:
        return 0755
    elif stat.S_ISLNK(mode):  # symlink
      return stat.S_IFLNK
    else:
      raise ImportError('invalid mode %o in %s' % (mode, name))

  def _CleanName(self, name):
    old_name = name
    for pm in self._remap:
      if pm.Matches(name):
        name = pm.Apply(name)
        break
    while name.startswith('/'):
      name = name[1:]
    if not name:
      raise ImportError('path %s is empty after remap' % old_name)
    if name.find('/./') >= 0 or name.find('/../') >= 0:
      raise ImportError('path %s contains relative parts' % name)
    return name

  def _MakeCommit(self):
    msg = '%s %s\n' % (self.PackageName, self.version)

    self._out.write('commit %s\n' % self._tempref)
    self._out.write('committer %s <%s> %d +0000\n' % (
                    self._user_name,
                    self._user_email,
                    self._user_when))
    self._out.write('data %d\n' % len(msg))
    self._out.write(msg)
    self._out.write('\n')
    if self.parent and not self._need_graft:
      self._out.write('from %s^0\n' % self.parent)
      self._out.write('deleteall\n')

    for f in self._files.values():
      self._out.write('M %o :%d %s\n' % (f.mode, f.mark, f.name))
    self._out.write('\n')

  def _GraftCommit(self):
    raw = self.project.bare_git.cat_file('commit', self._tempref)
    raw = raw.split("\n")
    while raw[1].startswith('parent '):
      del raw[1]
    raw.insert(1, 'parent %s' % self.parent)
    id = self._WriteObject('commit', "\n".join(raw))

    graft_file = os.path.join(self.project.gitdir, 'info/grafts')
    if os.path.exists(graft_file):
      graft_list = open(graft_file, 'rb').read().split("\n")
      if graft_list and graft_list[-1] == '':
        del graft_list[-1]
    else:
      graft_list = []

    exists = False
    for line in graft_list:
      if line == id:
        exists = True
        break

    if not exists:
      graft_list.append(id)
      graft_list.append('')
      fd = open(graft_file, 'wb')
      fd.write("\n".join(graft_list))
      fd.close()

    return id

  def _MakeTag(self, id):
    name = self.TagName

    raw = []
    raw.append('object %s' % id)
    raw.append('type commit')
    raw.append('tag %s' % name)
    raw.append('tagger %s <%s> %d +0000' % (
      self._user_name,
      self._user_email,
      self._user_when))
    raw.append('')
    raw.append('%s %s\n' % (self.PackageName, self.version))

    tagid = self._WriteObject('tag', "\n".join(raw))
    self.project.bare_git.UpdateRef('refs/tags/%s' % name, tagid)

  def _WriteObject(self, type, data):
    wo = GitCommand(self.project,
                    ['hash-object', '-t', type, '-w', '--stdin'],
                    bare = True,
                    provide_stdin = True,
                    capture_stdout = True,
                    capture_stderr = True)
    wo.stdin.write(data)
    if wo.Wait() != 0:
      raise GitError('cannot create %s from (%s)' % (type, data))
    return wo.stdout[:-1]


def _TrimPath(path):
  i = path.rfind('/')
  if i > 0:
    path = path[0:i]
  return ''

def _StripCommonPrefix(a, b):
  while True:
    ai = a.find('/')
    bi = b.find('/')
    if ai > 0 and bi > 0 and a[0:ai] == b[0:bi]:
      a = a[ai + 1:]
      b = b[bi + 1:]
    else:
      break
  return a, b

def _FoldPath(path):
  while True:
    if path.startswith('../'):
      return path

    i = path.find('/../')
    if i <= 0:
      if path.startswith('/'):
        return path[1:]
      return path

    lhs = path[0:i]
    rhs = path[i + 4:]

    i = lhs.rfind('/')
    if i > 0:
      path = lhs[0:i + 1] + rhs
    else:
      path = rhs

class _File(object):
  def __init__(self, mode, name, mark):
    self.mode = mode
    self.name = name
    self.mark = mark


class _PathMap(object):
  def __init__(self, imp, old, new):
    self._imp = imp
    self._old = old
    self._new = new

  def _r(self, p):
    return p.replace('%version%', self._imp.version)

  @property
  def old(self):
    return self._r(self._old)

  @property
  def new(self):
    return self._r(self._new)

  def Matches(self, name):
    return name.startswith(self.old)

  def Apply(self, name):
    return self.new + name[len(self.old):]
