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

import contextlib
import datetime
import errno
from http.client import HTTPException
import json
import os
import re
import ssl
import subprocess
import sys
from typing import Union
import urllib.error
import urllib.request

from error import GitError, UploadError
import platform_utils
from repo_trace import Trace
from git_command import GitCommand
from git_refs import R_CHANGES, R_HEADS, R_TAGS

# Prefix that is prepended to all the keys of SyncAnalysisState's data
# that is saved in the config.
SYNC_STATE_PREFIX = 'repo.syncstate.'

ID_RE = re.compile(r'^[0-9a-f]{40}$')

REVIEW_CACHE = dict()


def IsChange(rev):
  return rev.startswith(R_CHANGES)


def IsId(rev):
  return ID_RE.match(rev)


def IsTag(rev):
  return rev.startswith(R_TAGS)


def IsImmutable(rev):
    return IsChange(rev) or IsId(rev) or IsTag(rev)


def _key(name):
  parts = name.split('.')
  if len(parts) < 2:
    return name.lower()
  parts[0] = parts[0].lower()
  parts[-1] = parts[-1].lower()
  return '.'.join(parts)


class GitConfig(object):
  _ForUser = None

  _ForSystem = None
  _SYSTEM_CONFIG = '/etc/gitconfig'

  @classmethod
  def ForSystem(cls):
    if cls._ForSystem is None:
      cls._ForSystem = cls(configfile=cls._SYSTEM_CONFIG)
    return cls._ForSystem

  @classmethod
  def ForUser(cls):
    if cls._ForUser is None:
      cls._ForUser = cls(configfile=cls._getUserConfig())
    return cls._ForUser

  @staticmethod
  def _getUserConfig():
    return os.path.expanduser('~/.gitconfig')

  @classmethod
  def ForRepository(cls, gitdir, defaults=None):
    return cls(configfile=os.path.join(gitdir, 'config'),
               defaults=defaults)

  def __init__(self, configfile, defaults=None, jsonFile=None):
    self.file = configfile
    self.defaults = defaults
    self._cache_dict = None
    self._section_dict = None
    self._remotes = {}
    self._branches = {}

    self._json = jsonFile
    if self._json is None:
      self._json = os.path.join(
          os.path.dirname(self.file),
          '.repo_' + os.path.basename(self.file) + '.json')

  def ClearCache(self):
    """Clear the in-memory cache of config."""
    self._cache_dict = None

  def Has(self, name, include_defaults=True):
    """Return true if this configuration file has the key.
    """
    if _key(name) in self._cache:
      return True
    if include_defaults and self.defaults:
      return self.defaults.Has(name, include_defaults=True)
    return False

  def GetInt(self, name: str) -> Union[int, None]:
    """Returns an integer from the configuration file.

    This follows the git config syntax.

    Args:
      name: The key to lookup.

    Returns:
      None if the value was not defined, or is not an int.
      Otherwise, the number itself.
    """
    v = self.GetString(name)
    if v is None:
      return None
    v = v.strip()

    mult = 1
    if v.endswith('k'):
      v = v[:-1]
      mult = 1024
    elif v.endswith('m'):
      v = v[:-1]
      mult = 1024 * 1024
    elif v.endswith('g'):
      v = v[:-1]
      mult = 1024 * 1024 * 1024

    base = 10
    if v.startswith('0x'):
      base = 16

    try:
      return int(v, base=base) * mult
    except ValueError:
      print(
          f"warning: expected {name} to represent an integer, got {v} instead",
          file=sys.stderr)
      return None

  def DumpConfigDict(self):
    """Returns the current configuration dict.

    Configuration data is information only (e.g. logging) and
    should not be considered a stable data-source.

    Returns:
      dict of {<key>, <value>} for git configuration cache.
      <value> are strings converted by GetString.
    """
    config_dict = {}
    for key in self._cache:
      config_dict[key] = self.GetString(key)
    return config_dict

  def GetBoolean(self, name: str) -> Union[str, None]:
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
    print(f"warning: expected {name} to represent a boolean, got {v} instead",
          file=sys.stderr)
    return None

  def SetBoolean(self, name, value):
    """Set the truthy value for a key."""
    if value is not None:
      value = 'true' if value else 'false'
    self.SetString(name, value)

  def GetString(self, name: str, all_keys: bool = False) -> Union[str, None]:
    """Get the first value for a key, or None if it is not defined.

       This configuration file is used first, if the key is not
       defined or all_keys = True then the defaults are also searched.
    """
    try:
      v = self._cache[_key(name)]
    except KeyError:
      if self.defaults:
        return self.defaults.GetString(name, all_keys=all_keys)
      v = []

    if not all_keys:
      if v:
        return v[0]
      return None

    r = []
    r.extend(v)
    if self.defaults:
      r.extend(self.defaults.GetString(name, all_keys=True))
    return r

  def SetString(self, name, value):
    """Set the value(s) for a key.
       Only this configuration file is modified.

       The supplied value should be either a string, or a list of strings (to
       store multiple values), or None (to delete the key).
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
        for i in range(1, len(value)):
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

  def GetSyncAnalysisStateData(self):
    """Returns data to be logged for the analysis of sync performance."""
    return {k: v for k, v in self.DumpConfigDict().items() if k.startswith(SYNC_STATE_PREFIX)}

  def UpdateSyncAnalysisState(self, options, superproject_logging_data):
    """Update Config's SYNC_STATE_PREFIX* data with the latest sync data.

    Args:
      options: Options passed to sync returned from optparse. See _Options().
      superproject_logging_data: A dictionary of superproject data that is to be logged.

    Returns:
      SyncAnalysisState object.
    """
    return SyncAnalysisState(self, options, superproject_logging_data)

  def GetSubSections(self, section):
    """List all subsection names matching $section.*.*
    """
    return self._sections.get(section, set())

  def HasSection(self, section, subsection=''):
    """Does at least one key in section.subsection exist?
    """
    try:
      return subsection in self._sections[section]
    except KeyError:
      return False

  def UrlInsteadOf(self, url):
    """Resolve any url.*.insteadof references.
    """
    for new_url in self.GetSubSections('url'):
      for old_url in self.GetString('url.%s.insteadof' % new_url, True):
        if old_url is not None and url.startswith(old_url):
          return new_url + url[len(old_url):]
    return url

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
    d = self._ReadJson()
    if d is None:
      d = self._ReadGit()
      self._SaveJson(d)
    return d

  def _ReadJson(self):
    try:
      if os.path.getmtime(self._json) <= os.path.getmtime(self.file):
        platform_utils.remove(self._json)
        return None
    except OSError:
      return None
    try:
      with Trace(': parsing %s', self.file):
        with open(self._json) as fd:
          return json.load(fd)
    except (IOError, ValueError):
      platform_utils.remove(self._json, missing_ok=True)
      return None

  def _SaveJson(self, cache):
    try:
      with open(self._json, 'w') as fd:
        json.dump(cache, fd, indent=2)
    except (IOError, TypeError):
      platform_utils.remove(self._json, missing_ok=True)

  def _ReadGit(self):
    """
    Read configuration data from git.

    This internal method populates the GitConfig cache.

    """
    c = {}
    if not os.path.exists(self.file):
      return c

    d = self._do('--null', '--list')
    for line in d.rstrip('\0').split('\0'):
      if '\n' in line:
        key, val = line.split('\n', 1)
      else:
        key = line
        val = None

      if key in c:
        c[key].append(val)
      else:
        c[key] = [val]

    return c

  def _do(self, *args):
    if self.file == self._SYSTEM_CONFIG:
      command = ['config', '--system', '--includes']
    else:
      command = ['config', '--file', self.file, '--includes']
    command.extend(args)

    p = GitCommand(None,
                   command,
                   capture_stdout=True,
                   capture_stderr=True)
    if p.Wait() == 0:
      return p.stdout
    else:
      raise GitError('git config %s: %s' % (str(args), p.stderr))


class RepoConfig(GitConfig):
  """User settings for repo itself."""

  @staticmethod
  def _getUserConfig():
    repo_config_dir = os.getenv('REPO_CONFIG_DIR', os.path.expanduser('~'))
    return os.path.join(repo_config_dir, '.repoconfig/config')


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


URI_ALL = re.compile(r'^([a-z][a-z+-]*)://([^@/]*@?[^/]*)/')


def GetSchemeFromUrl(url):
  m = URI_ALL.match(url)
  if m:
    return m.group(1)
  return None


@contextlib.contextmanager
def GetUrlCookieFile(url, quiet):
  if url.startswith('persistent-'):
    try:
      p = subprocess.Popen(
          ['git-remote-persistent-https', '-print_config', url],
          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
          stderr=subprocess.PIPE)
      try:
        cookieprefix = 'http.cookiefile='
        proxyprefix = 'http.proxy='
        cookiefile = None
        proxy = None
        for line in p.stdout:
          line = line.strip().decode('utf-8')
          if line.startswith(cookieprefix):
            cookiefile = os.path.expanduser(line[len(cookieprefix):])
          if line.startswith(proxyprefix):
            proxy = line[len(proxyprefix):]
        # Leave subprocess open, as cookie file may be transient.
        if cookiefile or proxy:
          yield cookiefile, proxy
          return
      finally:
        p.stdin.close()
        if p.wait():
          err_msg = p.stderr.read().decode('utf-8')
          if ' -print_config' in err_msg:
            pass  # Persistent proxy doesn't support -print_config.
          elif not quiet:
            print(err_msg, file=sys.stderr)
    except OSError as e:
      if e.errno == errno.ENOENT:
        pass  # No persistent proxy.
      raise
  cookiefile = GitConfig.ForUser().GetString('http.cookiefile')
  if cookiefile:
    cookiefile = os.path.expanduser(cookiefile)
  yield cookiefile, None


class Remote(object):
  """Configuration options related to a remote.
  """

  def __init__(self, config, name):
    self._config = config
    self.name = name
    self.url = self._Get('url')
    self.pushUrl = self._Get('pushurl')
    self.review = self._Get('review')
    self.projectname = self._Get('projectname')
    self.fetch = list(map(RefSpec.FromString,
                          self._Get('fetch', all_keys=True)))
    self._review_url = None

  def _InsteadOf(self):
    globCfg = GitConfig.ForUser()
    urlList = globCfg.GetSubSections('url')
    longest = ""
    longestUrl = ""

    for url in urlList:
      key = "url." + url + ".insteadOf"
      insteadOfList = globCfg.GetString(key, all_keys=True)

      for insteadOf in insteadOfList:
        if (self.url.startswith(insteadOf)
                and len(insteadOf) > len(longest)):
          longest = insteadOf
          longestUrl = url

    if len(longest) == 0:
      return self.url

    return self.url.replace(longest, longestUrl, 1)

  def PreConnectFetch(self, ssh_proxy):
    """Run any setup for this remote before we connect to it.

    In practice, if the remote is using SSH, we'll attempt to create a new
    SSH master session to it for reuse across projects.

    Args:
      ssh_proxy: The SSH settings for managing master sessions.

    Returns:
      Whether the preconnect phase for this remote was successful.
    """
    if not ssh_proxy:
      return True

    connectionUrl = self._InsteadOf()
    return ssh_proxy.preconnect(connectionUrl)

  def ReviewUrl(self, userEmail, validate_certs):
    if self._review_url is None:
      if self.review is None:
        return None

      u = self.review
      if u.startswith('persistent-'):
        u = u[len('persistent-'):]
      if u.split(':')[0] not in ('http', 'https', 'sso', 'ssh'):
        u = 'http://%s' % u
      if u.endswith('/Gerrit'):
        u = u[:len(u) - len('/Gerrit')]
      if u.endswith('/ssh_info'):
        u = u[:len(u) - len('/ssh_info')]
      if not u.endswith('/'):
        u += '/'
      http_url = u

      if u in REVIEW_CACHE:
        self._review_url = REVIEW_CACHE[u]
      elif 'REPO_HOST_PORT_INFO' in os.environ:
        host, port = os.environ['REPO_HOST_PORT_INFO'].split()
        self._review_url = self._SshReviewUrl(userEmail, host, port)
        REVIEW_CACHE[u] = self._review_url
      elif u.startswith('sso:') or u.startswith('ssh:'):
        self._review_url = u  # Assume it's right
        REVIEW_CACHE[u] = self._review_url
      elif 'REPO_IGNORE_SSH_INFO' in os.environ:
        self._review_url = http_url
        REVIEW_CACHE[u] = self._review_url
      else:
        try:
          info_url = u + 'ssh_info'
          if not validate_certs:
              context = ssl._create_unverified_context()
              info = urllib.request.urlopen(info_url, context=context).read()
          else:
              info = urllib.request.urlopen(info_url).read()
          if info == b'NOT_AVAILABLE' or b'<' in info:
            # If `info` contains '<', we assume the server gave us some sort
            # of HTML response back, like maybe a login page.
            #
            # Assume HTTP if SSH is not enabled or ssh_info doesn't look right.
            self._review_url = http_url
          else:
            info = info.decode('utf-8')
            host, port = info.split()
            self._review_url = self._SshReviewUrl(userEmail, host, port)
        except urllib.error.HTTPError as e:
          raise UploadError('%s: %s' % (self.review, str(e)))
        except urllib.error.URLError as e:
          raise UploadError('%s: %s' % (self.review, str(e)))
        except HTTPException as e:
          raise UploadError('%s: %s' % (self.review, e.__class__.__name__))

        REVIEW_CACHE[u] = self._review_url
    return self._review_url + self.projectname

  def _SshReviewUrl(self, userEmail, host, port):
    username = self._config.GetString('review.%s.username' % self.review)
    if username is None:
      username = userEmail.split('@')[0]
    return 'ssh://%s@%s:%s/' % (username, host, port)

  def ToLocal(self, rev):
    """Convert a remote revision string to something we have locally.
    """
    if self.name == '.' or IsId(rev):
      return rev

    if not rev.startswith('refs/'):
      rev = R_HEADS + rev

    for spec in self.fetch:
      if spec.SourceMatches(rev):
        return spec.MapSource(rev)

    if not rev.startswith(R_HEADS):
      return rev

    raise GitError('%s: remote %s does not have %s' %
                   (self.projectname, self.name, rev))

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
    if self.pushUrl is not None:
      self._Set('pushurl', self.pushUrl + '/' + self.projectname)
    else:
      self._Set('pushurl', self.pushUrl)
    self._Set('review', self.review)
    self._Set('projectname', self.projectname)
    self._Set('fetch', list(map(str, self.fetch)))

  def _Set(self, key, value):
    key = 'remote.%s.%s' % (self.name, key)
    return self._config.SetString(key, value)

  def _Get(self, key, all_keys=False):
    key = 'remote.%s.%s' % (self.name, key)
    return self._config.GetString(key, all_keys=all_keys)


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
      with open(self._config.file, 'a') as fd:
        fd.write('[branch "%s"]\n' % self.name)
        if self.remote:
          fd.write('\tremote = %s\n' % self.remote.name)
        if self.merge:
          fd.write('\tmerge = %s\n' % self.merge)

  def _Set(self, key, value):
    key = 'branch.%s.%s' % (self.name, key)
    return self._config.SetString(key, value)

  def _Get(self, key, all_keys=False):
    key = 'branch.%s.%s' % (self.name, key)
    return self._config.GetString(key, all_keys=all_keys)


class SyncAnalysisState:
  """Configuration options related to logging of sync state for analysis.

  This object is versioned.
  """
  def __init__(self, config, options, superproject_logging_data):
    """Initializes SyncAnalysisState.

    Saves the following data into the |config| object.
    - sys.argv, options, superproject's logging data.
    - repo.*, branch.* and remote.* parameters from config object.
    - Current time as synctime.
    - Version number of the object.

    All the keys saved by this object are prepended with SYNC_STATE_PREFIX.

    Args:
      config: GitConfig object to store all options.
      options: Options passed to sync returned from optparse. See _Options().
      superproject_logging_data: A dictionary of superproject data that is to be logged.
    """
    self._config = config
    now = datetime.datetime.utcnow()
    self._Set('main.synctime', now.isoformat() + 'Z')
    self._Set('main.version', '1')
    self._Set('sys.argv', sys.argv)
    for key, value in superproject_logging_data.items():
      self._Set(f'superproject.{key}', value)
    for key, value in options.__dict__.items():
      self._Set(f'options.{key}', value)
    config_items = config.DumpConfigDict().items()
    EXTRACT_NAMESPACES = {'repo', 'branch', 'remote'}
    self._SetDictionary({k: v for k, v in config_items
                         if not k.startswith(SYNC_STATE_PREFIX) and
                         k.split('.', 1)[0] in EXTRACT_NAMESPACES})

  def _SetDictionary(self, data):
    """Save all key/value pairs of |data| dictionary.

    Args:
      data: A dictionary whose key/value are to be saved.
    """
    for key, value in data.items():
      self._Set(key, value)

  def _Set(self, key, value):
    """Set the |value| for a |key| in the |_config| member.

    |key| is prepended with the value of SYNC_STATE_PREFIX constant.

    Args:
      key: Name of the key.
      value: |value| could be of any type. If it is 'bool', it will be saved
             as a Boolean and for all other types, it will be saved as a String.
    """
    if value is None:
      return
    sync_key = f'{SYNC_STATE_PREFIX}{key}'
    sync_key = sync_key.replace('_', '')
    if isinstance(value, str):
      self._config.SetString(sync_key, value)
    elif isinstance(value, bool):
      self._config.SetBoolean(sync_key, value)
    else:
      self._config.SetString(sync_key, str(value))
