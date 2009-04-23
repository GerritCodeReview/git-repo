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

import cPickle
import os
import re
import subprocess
import sys
import time
from signal import SIGTERM
from urllib2 import urlopen, HTTPError
from error import GitError, UploadError
from trace import Trace
from git_command import GitCommand, _ssh_sock

R_HEADS = 'refs/heads/'
R_TAGS  = 'refs/tags/'
ID_RE = re.compile('^[0-9a-f]{40}$')

REVIEW_CACHE = dict()

def IsId(rev):
  return ID_RE.match(rev)

def _key(name):
  parts = name.split('.')
  if len(parts) < 2:
    return name.lower()
  parts[ 0] = parts[ 0].lower()
  parts[-1] = parts[-1].lower()
  return '.'.join(parts)

class GitConfig(object):
  _ForUser = None

  @classmethod
  def ForUser(cls):
    if cls._ForUser is None:
      cls._ForUser = cls(file = os.path.expanduser('~/.gitconfig'))
    return cls._ForUser

  @classmethod
  def ForRepository(cls, gitdir, defaults=None):
    return cls(file = os.path.join(gitdir, 'config'),
               defaults = defaults)

  def __init__(self, file, defaults=None):
    self.file = file
    self.defaults = defaults
    self._cache_dict = None
    self._section_dict = None
    self._remotes = {}
    self._branches = {}
    self._pickle = os.path.join(
      os.path.dirname(self.file),
      '.repopickle_' + os.path.basename(self.file))

  def Has(self, name, include_defaults = True):
    """Return true if this configuration file has the key.
    """
    if _key(name) in self._cache:
      return True
    if include_defaults and self.defaults:
      return self.defaults.Has(name, include_defaults = True)
    return False

  def GetBoolean(self, name):
    """Returns a boolean from the configuration file.
       None : The value was not defined, or is not a boolean.
       True : The value was set to true or yes.
       False: The value was set to false or no.
    """
    v = self.GetString(name)
    if v is None:
      return None
    v = v.lower()
    if v in ('true', 'yes'):
      return True
    if v in ('false', 'no'):
      return False
    return None

  def GetString(self, name, all=False):
    """Get the first value for a key, or None if it is not defined.

       This configuration file is used first, if the key is not
       defined or all = True then the defaults are also searched.
    """
    try:
      v = self._cache[_key(name)]
    except KeyError:
      if self.defaults:
        return self.defaults.GetString(name, all = all)
      v = []

    if not all:
      if v:
        return v[0]
      return None

    r = []
    r.extend(v)
    if self.defaults:
      r.extend(self.defaults.GetString(name, all = True))
    return r

  def SetString(self, name, value):
    """Set the value(s) for a key.
       Only this configuration file is modified.

       The supplied value should be either a string,
       or a list of strings (to store multiple values).
    """
    key = _key(name)

    try:
      old = self._cache[key]
    except KeyError:
      old = []

    if value is None:
      if old:
        del self._cache[key]
        self._do('--unset-all', name)

    elif isinstance(value, list):
      if len(value) == 0:
        self.SetString(name, None)

      elif len(value) == 1:
        self.SetString(name, value[0])

      elif old != value:
        self._cache[key] = list(value)
        self._do('--replace-all', name, value[0])
        for i in xrange(1, len(value)):
          self._do('--add', name, value[i])

    elif len(old) != 1 or old[0] != value:
      self._cache[key] = [value]
      self._do('--replace-all', name, value)

  def GetRemote(self, name):
    """Get the remote.$name.* configuration values as an object.
    """
    try:
      r = self._remotes[name]
    except KeyError:
      r = Remote(self, name)
      self._remotes[r.name] = r
    return r

  def GetBranch(self, name):
    """Get the branch.$name.* configuration values as an object.
    """
    try:
      b = self._branches[name]
    except KeyError:
      b = Branch(self, name)
      self._branches[b.name] = b
    return b

  def HasSection(self, section, subsection = ''):
    """Does at least one key in section.subsection exist?
    """
    try:
      return subsection in self._sections[section]
    except KeyError:
      return False

  @property
  def _sections(self):
    d = self._section_dict
    if d is None:
      d = {}
      for name in self._cache.keys():
        p = name.split('.')
        if 2 == len(p):
          section = p[0]
          subsect = ''
        else:
          section = p[0]
          subsect = '.'.join(p[1:-1])
        if section not in d:
          d[section] = set()
        d[section].add(subsect)
        self._section_dict = d
    return d

  @property
  def _cache(self):
    if self._cache_dict is None:
      self._cache_dict = self._Read()
    return self._cache_dict

  def _Read(self):
    d = self._ReadPickle()
    if d is None:
      d = self._ReadGit()
      self._SavePickle(d)
    return d

  def _ReadPickle(self):
    try:
      if os.path.getmtime(self._pickle) \
      <= os.path.getmtime(self.file):
        os.remove(self._pickle)
        return None
    except OSError:
      return None
    try:
      Trace(': unpickle %s', self.file)
      fd = open(self._pickle, 'rb')
      try:
        return cPickle.load(fd)
      finally:
        fd.close()
    except IOError:
      os.remove(self._pickle)
      return None
    except cPickle.PickleError:
      os.remove(self._pickle)
      return None

  def _SavePickle(self, cache):
    try:
      fd = open(self._pickle, 'wb')
      try:
        cPickle.dump(cache, fd, cPickle.HIGHEST_PROTOCOL)
      finally:
        fd.close()
    except IOError:
      os.remove(self._pickle)
    except cPickle.PickleError:
      os.remove(self._pickle)

  def _ReadGit(self):
    d = self._do('--null', '--list')
    c = {}
    while d:
      lf = d.index('\n')
      nul = d.index('\0', lf + 1)

      key = _key(d[0:lf])
      val = d[lf + 1:nul]

      if key in c:
        c[key].append(val)
      else:
        c[key] = [val]

      d = d[nul + 1:]
    return c

  def _do(self, *args):
    command = ['config', '--file', self.file]
    command.extend(args)

    p = GitCommand(None,
                   command,
                   capture_stdout = True,
                   capture_stderr = True)
    if p.Wait() == 0:
      return p.stdout
    else:
      GitError('git config %s: %s' % (str(args), p.stderr))


class RefSpec(object):
  """A Git refspec line, split into its components:

      forced:  True if the line starts with '+'
      src:     Left side of the line
      dst:     Right side of the line
  """

  @classmethod
  def FromString(cls, rs):
    lhs, rhs = rs.split(':', 2)
    if lhs.startswith('+'):
      lhs = lhs[1:]
      forced = True
    else:
      forced = False
    return cls(forced, lhs, rhs)

  def __init__(self, forced, lhs, rhs):
    self.forced = forced
    self.src = lhs
    self.dst = rhs

  def SourceMatches(self, rev):
    if self.src:
      if rev == self.src:
        return True
      if self.src.endswith('/*') and rev.startswith(self.src[:-1]):
        return True
    return False

  def DestMatches(self, ref):
    if self.dst:
      if ref == self.dst:
        return True
      if self.dst.endswith('/*') and ref.startswith(self.dst[:-1]):
        return True
    return False

  def MapSource(self, rev):
    if self.src.endswith('/*'):
      return self.dst[:-1] + rev[len(self.src) - 1:]
    return self.dst

  def __str__(self):
    s = ''
    if self.forced:
      s += '+'
    if self.src:
      s += self.src
    if self.dst:
      s += ':'
      s += self.dst
    return s


_ssh_cache = {}
_ssh_master = True

def _open_ssh(host, port):
  global _ssh_master

  key = '%s:%s' % (host, port)
  if key in _ssh_cache:
    return True

  if not _ssh_master \
  or 'GIT_SSH' in os.environ \
  or sys.platform == 'win32':
    # failed earlier, or cygwin ssh can't do this
    #
    return False

  command = ['ssh',
             '-o','ControlPath %s' % _ssh_sock(),
             '-p',str(port),
             '-M',
             '-N',
             host]
  try:
    Trace(': %s', ' '.join(command))
    p = subprocess.Popen(command)
  except Exception, e:
    _ssh_master = False
    print >>sys.stderr, \
      '\nwarn: cannot enable ssh control master for %s:%s\n%s' \
      % (host,port, str(e))
    return False

  _ssh_cache[key] = p
  time.sleep(1)
  return True

def close_ssh():
  for key,p in _ssh_cache.iteritems():
    os.kill(p.pid, SIGTERM)
    p.wait()
  _ssh_cache.clear()

  d = _ssh_sock(create=False)
  if d:
    try:
      os.rmdir(os.path.dirname(d))
    except OSError:
      pass

URI_SCP = re.compile(r'^([^@:]*@?[^:/]{1,}):')
URI_ALL = re.compile(r'^([a-z][a-z+]*)://([^@/]*@?[^/])/')

def _preconnect(url):
  m = URI_ALL.match(url)
  if m:
    scheme = m.group(1)
    host = m.group(2)
    if ':' in host:
      host, port = host.split(':')
    else:
      port = 22
    if scheme in ('ssh', 'git+ssh', 'ssh+git'):
      return _open_ssh(host, port)
    return False

  m = URI_SCP.match(url)
  if m:
    host = m.group(1)
    return _open_ssh(host, 22)


class Remote(object):
  """Configuration options related to a remote.
  """
  def __init__(self, config, name):
    self._config = config
    self.name = name
    self.url = self._Get('url')
    self.review = self._Get('review')
    self.projectname = self._Get('projectname')
    self.fetch = map(lambda x: RefSpec.FromString(x),
                     self._Get('fetch', all=True))
    self._review_protocol = None

  def PreConnectFetch(self):
    return _preconnect(self.url)

  @property
  def ReviewProtocol(self):
    if self._review_protocol is None:
      if self.review is None:
        return None

      u = self.review
      if not u.startswith('http:') and not u.startswith('https:'):
        u = 'http://%s' % u
      if u.endswith('/Gerrit'):
        u = u[:len(u) - len('/Gerrit')]
      if not u.endswith('/ssh_info'):
        if not u.endswith('/'):
          u += '/'
        u += 'ssh_info'

      if u in REVIEW_CACHE:
        info = REVIEW_CACHE[u]
        self._review_protocol = info[0]
        self._review_host = info[1]
        self._review_port = info[2]
      else:
        try:
          info = urlopen(u).read()
          if info == 'NOT_AVAILABLE':
            raise UploadError('Upload over ssh unavailable')
          if '<' in info:
            # Assume the server gave us some sort of HTML
            # response back, like maybe a login page.
            #
            raise UploadError('Cannot read %s:\n%s' % (u, info))

          self._review_protocol = 'ssh'
          self._review_host = info.split(" ")[0]
          self._review_port = info.split(" ")[1]
        except HTTPError, e:
          if e.code == 404:
            self._review_protocol = 'http-post'
            self._review_host = None
            self._review_port = None
          else:
            raise UploadError('Cannot guess Gerrit version')

        REVIEW_CACHE[u] = (
          self._review_protocol,
          self._review_host,
          self._review_port)
    return self._review_protocol

  def SshReviewUrl(self, userEmail):
    if self.ReviewProtocol != 'ssh':
      return None
    return 'ssh://%s@%s:%s/%s' % (
      userEmail.split("@")[0],
      self._review_host,
      self._review_port,
      self.projectname)

  def ToLocal(self, rev):
    """Convert a remote revision string to something we have locally.
    """
    if IsId(rev):
      return rev
    if rev.startswith(R_TAGS):
      return rev

    if not rev.startswith('refs/'):
      rev = R_HEADS + rev

    for spec in self.fetch:
      if spec.SourceMatches(rev):
        return spec.MapSource(rev)
    raise GitError('remote %s does not have %s' % (self.name, rev))

  def WritesTo(self, ref):
    """True if the remote stores to the tracking ref.
    """
    for spec in self.fetch:
      if spec.DestMatches(ref):
        return True
    return False

  def ResetFetch(self, mirror=False):
    """Set the fetch refspec to its default value.
    """
    if mirror:
      dst = 'refs/heads/*'
    else:
      dst = 'refs/remotes/%s/*' % self.name
    self.fetch = [RefSpec(True, 'refs/heads/*', dst)]

  def Save(self):
    """Save this remote to the configuration.
    """
    self._Set('url', self.url)
    self._Set('review', self.review)
    self._Set('projectname', self.projectname)
    self._Set('fetch', map(lambda x: str(x), self.fetch))

  def _Set(self, key, value):
    key = 'remote.%s.%s' % (self.name, key)
    return self._config.SetString(key, value)

  def _Get(self, key, all=False):
    key = 'remote.%s.%s' % (self.name, key)
    return self._config.GetString(key, all = all)


class Branch(object):
  """Configuration options related to a single branch.
  """
  def __init__(self, config, name):
    self._config = config
    self.name = name
    self.merge = self._Get('merge')

    r = self._Get('remote')
    if r:
      self.remote = self._config.GetRemote(r)
    else:
      self.remote = None

  @property
  def LocalMerge(self):
    """Convert the merge spec to a local name.
    """
    if self.remote and self.merge:
      return self.remote.ToLocal(self.merge)
    return None

  def Save(self):
    """Save this branch back into the configuration.
    """
    if self._config.HasSection('branch', self.name):
      if self.remote:
        self._Set('remote', self.remote.name)
      else:
        self._Set('remote', None)
      self._Set('merge', self.merge)

    else:
      fd = open(self._config.file, 'ab')
      try:
        fd.write('[branch "%s"]\n' % self.name)
        if self.remote:
          fd.write('\tremote = %s\n' % self.remote.name)
        if self.merge:
          fd.write('\tmerge = %s\n' % self.merge)
      finally:
        fd.close()

  def _Set(self, key, value):
    key = 'branch.%s.%s' % (self.name, key)
    return self._config.SetString(key, value)

  def _Get(self, key, all=False):
    key = 'branch.%s.%s' % (self.name, key)
    return self._config.GetString(key, all = all)
