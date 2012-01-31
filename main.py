#!/bin/sh
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

magic='--calling-python-from-/bin/sh--'
"""exec" python -E "$0" "$@" """#$magic"
if __name__ == '__main__':
  import sys
  if sys.argv[-1] == '#%s' % magic:
    del sys.argv[-1]
del magic

import netrc
import optparse
import os
import re
import sys
import time
import urllib2

from trace import SetTrace
from git_command import git, GitCommand
from git_config import init_ssh, close_ssh
from command import InteractiveCommand
from command import MirrorSafeCommand
from command import PagedCommand
from subcmds.version import Version
from editor import Editor
from error import DownloadError
from error import ManifestInvalidRevisionError
from error import NoSuchProjectError
from error import RepoChangedException
from manifest_xml import XmlManifest
from pager import RunPager

from subcmds import all as all_commands

global_options = optparse.OptionParser(
                 usage="repo [-p|--paginate|--no-pager] COMMAND [ARGS]"
                 )
global_options.add_option('-p', '--paginate',
                          dest='pager', action='store_true',
                          help='display command output in the pager')
global_options.add_option('--no-pager',
                          dest='no_pager', action='store_true',
                          help='disable the pager')
global_options.add_option('--trace',
                          dest='trace', action='store_true',
                          help='trace git command execution')
global_options.add_option('--time',
                          dest='time', action='store_true',
                          help='time repo command execution')
global_options.add_option('--version',
                          dest='show_version', action='store_true',
                          help='display this version of repo')

class _Repo(object):
  def __init__(self, repodir):
    self.repodir = repodir
    self.commands = all_commands
    # add 'branch' as an alias for 'branches'
    all_commands['branch'] = all_commands['branches']

  def _Run(self, argv):
    result = 0
    name = None
    glob = []

    for i in xrange(0, len(argv)):
      if not argv[i].startswith('-'):
        name = argv[i]
        if i > 0:
          glob = argv[:i]
        argv = argv[i + 1:]
        break
    if not name:
      glob = argv
      name = 'help'
      argv = []
    gopts, gargs = global_options.parse_args(glob)

    if gopts.trace:
      SetTrace()
    if gopts.show_version:
      if name == 'help':
        name = 'version'
      else:
        print >>sys.stderr, 'fatal: invalid usage of --version'
        return 1

    try:
      cmd = self.commands[name]
    except KeyError:
      print >>sys.stderr,\
            "repo: '%s' is not a repo command.  See 'repo help'."\
            % name
      return 1

    cmd.repodir = self.repodir
    cmd.manifest = XmlManifest(cmd.repodir)
    Editor.globalConfig = cmd.manifest.globalConfig

    if not isinstance(cmd, MirrorSafeCommand) and cmd.manifest.IsMirror:
      print >>sys.stderr, \
            "fatal: '%s' requires a working directory"\
            % name
      return 1

    copts, cargs = cmd.OptionParser.parse_args(argv)

    if not gopts.no_pager and not isinstance(cmd, InteractiveCommand):
      config = cmd.manifest.globalConfig
      if gopts.pager:
        use_pager = True
      else:
        use_pager = config.GetBoolean('pager.%s' % name)
        if use_pager is None:
          use_pager = cmd.WantPager(copts)
      if use_pager:
        RunPager(config)

    try:
      start = time.time()
      try:
        result = cmd.Execute(copts, cargs)
      finally:
        elapsed = time.time() - start
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if gopts.time:
          if hours == 0:
            print >>sys.stderr, 'real\t%dm%.3fs' \
              % (minutes, seconds)
          else:
            print >>sys.stderr, 'real\t%dh%dm%.3fs' \
              % (hours, minutes, seconds)
    except DownloadError, e:
      print >>sys.stderr, 'error: %s' % str(e)
      return 1
    except ManifestInvalidRevisionError, e:
      print >>sys.stderr, 'error: %s' % str(e)
      return 1
    except NoSuchProjectError, e:
      if e.name:
        print >>sys.stderr, 'error: project %s not found' % e.name
      else:
        print >>sys.stderr, 'error: no project in current directory'
      return 1

    return result

def _MyRepoPath():
  return os.path.dirname(__file__)

def _MyWrapperPath():
  return os.path.join(os.path.dirname(__file__), 'repo')

def _CurrentWrapperVersion():
  VERSION = None
  pat = re.compile(r'^VERSION *=')
  fd = open(_MyWrapperPath())
  for line in fd:
    if pat.match(line):
      fd.close()
      exec line
      return VERSION
  raise NameError, 'No VERSION in repo script'

def _CheckWrapperVersion(ver, repo_path):
  if not repo_path:
    repo_path = '~/bin/repo'

  if not ver:
     print >>sys.stderr, 'no --wrapper-version argument'
     sys.exit(1)

  exp = _CurrentWrapperVersion()
  ver = tuple(map(lambda x: int(x), ver.split('.')))
  if len(ver) == 1:
    ver = (0, ver[0])

  if exp[0] > ver[0] or ver < (0, 4):
    exp_str = '.'.join(map(lambda x: str(x), exp))
    print >>sys.stderr, """
!!! A new repo command (%5s) is available.    !!!
!!! You must upgrade before you can continue:   !!!

    cp %s %s
""" % (exp_str, _MyWrapperPath(), repo_path)
    sys.exit(1)

  if exp > ver:
    exp_str = '.'.join(map(lambda x: str(x), exp))
    print >>sys.stderr, """
... A new repo command (%5s) is available.
... You should upgrade soon:

    cp %s %s
""" % (exp_str, _MyWrapperPath(), repo_path)

def _CheckRepoDir(dir):
  if not dir:
     print >>sys.stderr, 'no --repo-dir argument'
     sys.exit(1)

def _PruneOptions(argv, opt):
  i = 0
  while i < len(argv):
    a = argv[i]
    if a == '--':
      break
    if a.startswith('--'):
      eq = a.find('=')
      if eq > 0:
        a = a[0:eq]
    if not opt.has_option(a):
      del argv[i]
      continue
    i += 1

_user_agent = None

def _UserAgent():
  global _user_agent

  if _user_agent is None:
    py_version = sys.version_info

    os_name = sys.platform
    if os_name == 'linux2':
      os_name = 'Linux'
    elif os_name == 'win32':
      os_name = 'Win32'
    elif os_name == 'cygwin':
      os_name = 'Cygwin'
    elif os_name == 'darwin':
      os_name = 'Darwin'

    p = GitCommand(
      None, ['describe', 'HEAD'],
      cwd = _MyRepoPath(),
      capture_stdout = True)
    if p.Wait() == 0:
      repo_version = p.stdout
      if len(repo_version) > 0 and repo_version[-1] == '\n':
        repo_version = repo_version[0:-1]
      if len(repo_version) > 0 and repo_version[0] == 'v':
        repo_version = repo_version[1:]
    else:
      repo_version = 'unknown'

    _user_agent = 'git-repo/%s (%s) git/%s Python/%d.%d.%d' % (
      repo_version,
      os_name,
      '.'.join(map(lambda d: str(d), git.version_tuple())),
      py_version[0], py_version[1], py_version[2])
  return _user_agent

class _UserAgentHandler(urllib2.BaseHandler):
  def http_request(self, req):
    req.add_header('User-Agent', _UserAgent())
    return req

  def https_request(self, req):
    req.add_header('User-Agent', _UserAgent())
    return req

class _BasicAuthHandler(urllib2.HTTPBasicAuthHandler):
  def http_error_auth_reqed(self, authreq, host, req, headers):
    try:
      old_add_header = req.add_header
      def _add_header(name, val):
        val = val.replace('\n', '')
        old_add_header(name, val)
      req.add_header = _add_header
      return urllib2.AbstractBasicAuthHandler.http_error_auth_reqed(
        self, authreq, host, req, headers)
    except:
      reset = getattr(self, 'reset_retry_count', None)
      if reset is not None:
        reset()
      elif getattr(self, 'retried', None):
        self.retried = 0
      raise

class _DigestAuthHandler(urllib2.HTTPDigestAuthHandler):
  def http_error_auth_reqed(self, auth_header, host, req, headers):
    try:
      old_add_header = req.add_header
      def _add_header(name, val):
        val = val.replace('\n', '')
        old_add_header(name, val)
      req.add_header = _add_header
      return urllib2.AbstractDigestAuthHandler.http_error_auth_reqed(
        self, auth_header, host, req, headers)
    except:
      reset = getattr(self, 'reset_retry_count', None)
      if reset is not None:
        reset()
      elif getattr(self, 'retried', None):
        self.retried = 0
      raise

def init_http():
  handlers = [_UserAgentHandler()]

  mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
  try:
    n = netrc.netrc()
    for host in n.hosts:
      p = n.hosts[host]
      mgr.add_password(p[1], 'http://%s/'  % host, p[0], p[2])
      mgr.add_password(p[1], 'https://%s/' % host, p[0], p[2])
  except netrc.NetrcParseError:
    pass
  except IOError:
    pass
  handlers.append(_BasicAuthHandler(mgr))
  handlers.append(_DigestAuthHandler(mgr))

  if 'http_proxy' in os.environ:
    url = os.environ['http_proxy']
    handlers.append(urllib2.ProxyHandler({'http': url, 'https': url}))
  if 'REPO_CURL_VERBOSE' in os.environ:
    handlers.append(urllib2.HTTPHandler(debuglevel=1))
    handlers.append(urllib2.HTTPSHandler(debuglevel=1))
  urllib2.install_opener(urllib2.build_opener(*handlers))

def _Main(argv):
  result = 0

  opt = optparse.OptionParser(usage="repo wrapperinfo -- ...")
  opt.add_option("--repo-dir", dest="repodir",
                 help="path to .repo/")
  opt.add_option("--wrapper-version", dest="wrapper_version",
                 help="version of the wrapper script")
  opt.add_option("--wrapper-path", dest="wrapper_path",
                 help="location of the wrapper script")
  _PruneOptions(argv, opt)
  opt, argv = opt.parse_args(argv)

  _CheckWrapperVersion(opt.wrapper_version, opt.wrapper_path)
  _CheckRepoDir(opt.repodir)

  Version.wrapper_version = opt.wrapper_version
  Version.wrapper_path = opt.wrapper_path

  repo = _Repo(opt.repodir)
  try:
    try:
      init_ssh()
      init_http()
      result = repo._Run(argv) or 0
    finally:
      close_ssh()
  except KeyboardInterrupt:
    result = 1
  except RepoChangedException, rce:
    # If repo changed, re-exec ourselves.
    #
    argv = list(sys.argv)
    argv.extend(rce.extra_args)
    try:
      os.execv(__file__, argv)
    except OSError, e:
      print >>sys.stderr, 'fatal: cannot restart repo after upgrade'
      print >>sys.stderr, 'fatal: %s' % e
      result = 128

  sys.exit(result)

if __name__ == '__main__':
  _Main(sys.argv[1:])
