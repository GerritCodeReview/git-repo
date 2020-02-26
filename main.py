#!/usr/bin/env python
# -*- coding:utf-8 -*-
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

"""The repo tool.

People shouldn't run this directly; instead, they should use the `repo` wrapper
which takes care of execing this entry point.
"""

from __future__ import print_function
import getpass
import netrc
import optparse
import os
import shlex
import sys
import textwrap
import time

from pyversion import is_python3
if is_python3():
  import urllib.request
else:
  import imp
  import urllib2
  urllib = imp.new_module('urllib')
  urllib.request = urllib2

try:
  import kerberos
except ImportError:
  kerberos = None

from color import SetDefaultColoring
import event_log
from repo_trace import SetTrace
from git_command import user_agent
from git_config import init_ssh, close_ssh, RepoConfig
from command import InteractiveCommand
from command import MirrorSafeCommand
from command import GitcAvailableCommand, GitcClientCommand
from subcmds.version import Version
from editor import Editor
from error import DownloadError
from error import InvalidProjectGroupsError
from error import ManifestInvalidRevisionError
from error import ManifestParseError
from error import NoManifestException
from error import NoSuchProjectError
from error import RepoChangedException
import gitc_utils
from manifest_xml import GitcManifest, XmlManifest
from pager import RunPager, TerminatePager
from wrapper import WrapperPath, Wrapper

from subcmds import all_commands

if not is_python3():
  input = raw_input  # noqa: F821

# NB: These do not need to be kept in sync with the repo launcher script.
# These may be much newer as it allows the repo launcher to roll between
# different repo releases while source versions might require a newer python.
#
# The soft version is when we start warning users that the version is old and
# we'll be dropping support for it.  We'll refuse to work with versions older
# than the hard version.
#
# python-3.6 is in Ubuntu Bionic.
MIN_PYTHON_VERSION_SOFT = (3, 6)
MIN_PYTHON_VERSION_HARD = (3, 4)

if sys.version_info.major < 3:
  print('repo: warning: Python 2 is no longer supported; '
        'Please upgrade to Python {}.{}+.'.format(*MIN_PYTHON_VERSION_SOFT),
        file=sys.stderr)
else:
  if sys.version_info < MIN_PYTHON_VERSION_HARD:
    print('repo: error: Python 3 version is too old; '
          'Please upgrade to Python {}.{}+.'.format(*MIN_PYTHON_VERSION_SOFT),
          file=sys.stderr)
    sys.exit(1)
  elif sys.version_info < MIN_PYTHON_VERSION_SOFT:
    print('repo: warning: your Python 3 version is no longer supported; '
          'Please upgrade to Python {}.{}+.'.format(*MIN_PYTHON_VERSION_SOFT),
          file=sys.stderr)


global_options = optparse.OptionParser(
    usage='repo [-p|--paginate|--no-pager] COMMAND [ARGS]',
    add_help_option=False)
global_options.add_option('-h', '--help', action='store_true',
                          help='show this help message and exit')
global_options.add_option('-p', '--paginate',
                          dest='pager', action='store_true',
                          help='display command output in the pager')
global_options.add_option('--no-pager',
                          dest='pager', action='store_false',
                          help='disable the pager')
global_options.add_option('--color',
                          choices=('auto', 'always', 'never'), default=None,
                          help='control color usage: auto, always, never')
global_options.add_option('--trace',
                          dest='trace', action='store_true',
                          help='trace git command execution (REPO_TRACE=1)')
global_options.add_option('--trace-python',
                          dest='trace_python', action='store_true',
                          help='trace python command execution')
global_options.add_option('--time',
                          dest='time', action='store_true',
                          help='time repo command execution')
global_options.add_option('--version',
                          dest='show_version', action='store_true',
                          help='display this version of repo')
global_options.add_option('--event-log',
                          dest='event_log', action='store',
                          help='filename of event log to append timeline to')


class _Repo(object):
  def __init__(self, repodir):
    self.repodir = repodir
    self.commands = all_commands
    # add 'branch' as an alias for 'branches'
    all_commands['branch'] = all_commands['branches']

  def _ParseArgs(self, argv):
    """Parse the main `repo` command line options."""
    name = None
    glob = []

    for i in range(len(argv)):
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
    gopts, _gargs = global_options.parse_args(glob)

    name, alias_args = self._ExpandAlias(name)
    argv = alias_args + argv

    if gopts.help:
      global_options.print_help()
      commands = ' '.join(sorted(self.commands))
      wrapped_commands = textwrap.wrap(commands, width=77)
      print('\nAvailable commands:\n  %s' % ('\n  '.join(wrapped_commands),))
      print('\nRun `repo help <command>` for command-specific details.')
      global_options.exit()

    return (name, gopts, argv)

  def _ExpandAlias(self, name):
    """Look up user registered aliases."""
    # We don't resolve aliases for existing subcommands.  This matches git.
    if name in self.commands:
      return name, []

    key = 'alias.%s' % (name,)
    alias = RepoConfig.ForRepository(self.repodir).GetString(key)
    if alias is None:
      alias = RepoConfig.ForUser().GetString(key)
    if alias is None:
      return name, []

    args = alias.strip().split(' ', 1)
    name = args[0]
    if len(args) == 2:
      args = shlex.split(args[1])
    else:
      args = []
    return name, args

  def _Run(self, name, gopts, argv):
    """Execute the requested subcommand."""
    result = 0

    if gopts.trace:
      SetTrace()
    if gopts.show_version:
      if name == 'help':
        name = 'version'
      else:
        print('fatal: invalid usage of --version', file=sys.stderr)
        return 1

    SetDefaultColoring(gopts.color)

    try:
      cmd = self.commands[name]
    except KeyError:
      print("repo: '%s' is not a repo command.  See 'repo help'." % name,
            file=sys.stderr)
      return 1

    cmd.repodir = self.repodir
    cmd.manifest = XmlManifest(cmd.repodir)
    cmd.gitc_manifest = None
    gitc_client_name = gitc_utils.parse_clientdir(os.getcwd())
    if gitc_client_name:
      cmd.gitc_manifest = GitcManifest(cmd.repodir, gitc_client_name)
      cmd.manifest.isGitcClient = True

    Editor.globalConfig = cmd.manifest.globalConfig

    if not isinstance(cmd, MirrorSafeCommand) and cmd.manifest.IsMirror:
      print("fatal: '%s' requires a working directory" % name,
            file=sys.stderr)
      return 1

    if isinstance(cmd, GitcAvailableCommand) and not gitc_utils.get_gitc_manifest_dir():
      print("fatal: '%s' requires GITC to be available" % name,
            file=sys.stderr)
      return 1

    if isinstance(cmd, GitcClientCommand) and not gitc_client_name:
      print("fatal: '%s' requires a GITC client" % name,
            file=sys.stderr)
      return 1

    try:
      copts, cargs = cmd.OptionParser.parse_args(argv)
      copts = cmd.ReadEnvironmentOptions(copts)
    except NoManifestException as e:
      print('error: in `%s`: %s' % (' '.join([name] + argv), str(e)),
            file=sys.stderr)
      print('error: manifest missing or unreadable -- please run init',
            file=sys.stderr)
      return 1

    if gopts.pager is not False and not isinstance(cmd, InteractiveCommand):
      config = cmd.manifest.globalConfig
      if gopts.pager:
        use_pager = True
      else:
        use_pager = config.GetBoolean('pager.%s' % name)
        if use_pager is None:
          use_pager = cmd.WantPager(copts)
      if use_pager:
        RunPager(config)

    start = time.time()
    cmd_event = cmd.event_log.Add(name, event_log.TASK_COMMAND, start)
    cmd.event_log.SetParent(cmd_event)
    try:
      cmd.ValidateOptions(copts, cargs)
      result = cmd.Execute(copts, cargs)
    except (DownloadError, ManifestInvalidRevisionError,
            NoManifestException) as e:
      print('error: in `%s`: %s' % (' '.join([name] + argv), str(e)),
            file=sys.stderr)
      if isinstance(e, NoManifestException):
        print('error: manifest missing or unreadable -- please run init',
              file=sys.stderr)
      result = 1
    except NoSuchProjectError as e:
      if e.name:
        print('error: project %s not found' % e.name, file=sys.stderr)
      else:
        print('error: no project in current directory', file=sys.stderr)
      result = 1
    except InvalidProjectGroupsError as e:
      if e.name:
        print('error: project group must be enabled for project %s' % e.name, file=sys.stderr)
      else:
        print('error: project group must be enabled for the project in the current directory',
              file=sys.stderr)
      result = 1
    except SystemExit as e:
      if e.code:
        result = e.code
      raise
    finally:
      finish = time.time()
      elapsed = finish - start
      hours, remainder = divmod(elapsed, 3600)
      minutes, seconds = divmod(remainder, 60)
      if gopts.time:
        if hours == 0:
          print('real\t%dm%.3fs' % (minutes, seconds), file=sys.stderr)
        else:
          print('real\t%dh%dm%.3fs' % (hours, minutes, seconds),
                file=sys.stderr)

      cmd.event_log.FinishEvent(cmd_event, finish,
                                result is None or result == 0)
      if gopts.event_log:
        cmd.event_log.Write(os.path.abspath(
                            os.path.expanduser(gopts.event_log)))

    return result


def _CheckWrapperVersion(ver_str, repo_path):
  """Verify the repo launcher is new enough for this checkout.

  Args:
    ver_str: The version string passed from the repo launcher when it ran us.
    repo_path: The path to the repo launcher that loaded us.
  """
  # Refuse to work with really old wrapper versions.  We don't test these,
  # so might as well require a somewhat recent sane version.
  # v1.15 of the repo launcher was released in ~Mar 2012.
  MIN_REPO_VERSION = (1, 15)
  min_str = '.'.join(str(x) for x in MIN_REPO_VERSION)

  if not repo_path:
    repo_path = '~/bin/repo'

  if not ver_str:
    print('no --wrapper-version argument', file=sys.stderr)
    sys.exit(1)

  # Pull out the version of the repo launcher we know about to compare.
  exp = Wrapper().VERSION
  ver = tuple(map(int, ver_str.split('.')))

  exp_str = '.'.join(map(str, exp))
  if ver < MIN_REPO_VERSION:
    print("""
repo: error:
!!! Your version of repo %s is too old.
!!! We need at least version %s.
!!! A new version of repo (%s) is available.
!!! You must upgrade before you can continue:

    cp %s %s
""" % (ver_str, min_str, exp_str, WrapperPath(), repo_path), file=sys.stderr)
    sys.exit(1)

  if exp > ver:
    print('\n... A new version of repo (%s) is available.' % (exp_str,),
          file=sys.stderr)
    if os.access(repo_path, os.W_OK):
      print("""\
... You should upgrade soon:
    cp %s %s
""" % (WrapperPath(), repo_path), file=sys.stderr)
    else:
      print("""\
... New version is available at: %s
... The launcher is run from: %s
!!! The launcher is not writable.  Please talk to your sysadmin or distro
!!! to get an update installed.
""" % (WrapperPath(), repo_path), file=sys.stderr)


def _CheckRepoDir(repo_dir):
  if not repo_dir:
    print('no --repo-dir argument', file=sys.stderr)
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


class _UserAgentHandler(urllib.request.BaseHandler):
  def http_request(self, req):
    req.add_header('User-Agent', user_agent.repo)
    return req

  def https_request(self, req):
    req.add_header('User-Agent', user_agent.repo)
    return req


def _AddPasswordFromUserInput(handler, msg, req):
  # If repo could not find auth info from netrc, try to get it from user input
  url = req.get_full_url()
  user, password = handler.passwd.find_user_password(None, url)
  if user is None:
    print(msg)
    try:
      user = input('User: ')
      password = getpass.getpass()
    except KeyboardInterrupt:
      return
    handler.passwd.add_password(None, url, user, password)


class _BasicAuthHandler(urllib.request.HTTPBasicAuthHandler):
  def http_error_401(self, req, fp, code, msg, headers):
    _AddPasswordFromUserInput(self, msg, req)
    return urllib.request.HTTPBasicAuthHandler.http_error_401(
        self, req, fp, code, msg, headers)

  def http_error_auth_reqed(self, authreq, host, req, headers):
    try:
      old_add_header = req.add_header

      def _add_header(name, val):
        val = val.replace('\n', '')
        old_add_header(name, val)
      req.add_header = _add_header
      return urllib.request.AbstractBasicAuthHandler.http_error_auth_reqed(
          self, authreq, host, req, headers)
    except Exception:
      reset = getattr(self, 'reset_retry_count', None)
      if reset is not None:
        reset()
      elif getattr(self, 'retried', None):
        self.retried = 0
      raise


class _DigestAuthHandler(urllib.request.HTTPDigestAuthHandler):
  def http_error_401(self, req, fp, code, msg, headers):
    _AddPasswordFromUserInput(self, msg, req)
    return urllib.request.HTTPDigestAuthHandler.http_error_401(
        self, req, fp, code, msg, headers)

  def http_error_auth_reqed(self, auth_header, host, req, headers):
    try:
      old_add_header = req.add_header

      def _add_header(name, val):
        val = val.replace('\n', '')
        old_add_header(name, val)
      req.add_header = _add_header
      return urllib.request.AbstractDigestAuthHandler.http_error_auth_reqed(
          self, auth_header, host, req, headers)
    except Exception:
      reset = getattr(self, 'reset_retry_count', None)
      if reset is not None:
        reset()
      elif getattr(self, 'retried', None):
        self.retried = 0
      raise


class _KerberosAuthHandler(urllib.request.BaseHandler):
  def __init__(self):
    self.retried = 0
    self.context = None
    self.handler_order = urllib.request.BaseHandler.handler_order - 50

  def http_error_401(self, req, fp, code, msg, headers):
    host = req.get_host()
    retry = self.http_error_auth_reqed('www-authenticate', host, req, headers)
    return retry

  def http_error_auth_reqed(self, auth_header, host, req, headers):
    try:
      spn = "HTTP@%s" % host
      authdata = self._negotiate_get_authdata(auth_header, headers)

      if self.retried > 3:
        raise urllib.request.HTTPError(req.get_full_url(), 401,
                                       "Negotiate auth failed", headers, None)
      else:
        self.retried += 1

      neghdr = self._negotiate_get_svctk(spn, authdata)
      if neghdr is None:
        return None

      req.add_unredirected_header('Authorization', neghdr)
      response = self.parent.open(req)

      srvauth = self._negotiate_get_authdata(auth_header, response.info())
      if self._validate_response(srvauth):
        return response
    except kerberos.GSSError:
      return None
    except Exception:
      self.reset_retry_count()
      raise
    finally:
      self._clean_context()

  def reset_retry_count(self):
    self.retried = 0

  def _negotiate_get_authdata(self, auth_header, headers):
    authhdr = headers.get(auth_header, None)
    if authhdr is not None:
      for mech_tuple in authhdr.split(","):
        mech, __, authdata = mech_tuple.strip().partition(" ")
        if mech.lower() == "negotiate":
          return authdata.strip()
    return None

  def _negotiate_get_svctk(self, spn, authdata):
    if authdata is None:
      return None

    result, self.context = kerberos.authGSSClientInit(spn)
    if result < kerberos.AUTH_GSS_COMPLETE:
      return None

    result = kerberos.authGSSClientStep(self.context, authdata)
    if result < kerberos.AUTH_GSS_CONTINUE:
      return None

    response = kerberos.authGSSClientResponse(self.context)
    return "Negotiate %s" % response

  def _validate_response(self, authdata):
    if authdata is None:
      return None
    result = kerberos.authGSSClientStep(self.context, authdata)
    if result == kerberos.AUTH_GSS_COMPLETE:
      return True
    return None

  def _clean_context(self):
    if self.context is not None:
      kerberos.authGSSClientClean(self.context)
      self.context = None


def init_http():
  handlers = [_UserAgentHandler()]

  mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
  try:
    n = netrc.netrc()
    for host in n.hosts:
      p = n.hosts[host]
      mgr.add_password(p[1], 'http://%s/' % host, p[0], p[2])
      mgr.add_password(p[1], 'https://%s/' % host, p[0], p[2])
  except netrc.NetrcParseError:
    pass
  except IOError:
    pass
  handlers.append(_BasicAuthHandler(mgr))
  handlers.append(_DigestAuthHandler(mgr))
  if kerberos:
    handlers.append(_KerberosAuthHandler())

  if 'http_proxy' in os.environ:
    url = os.environ['http_proxy']
    handlers.append(urllib.request.ProxyHandler({'http': url, 'https': url}))
  if 'REPO_CURL_VERBOSE' in os.environ:
    handlers.append(urllib.request.HTTPHandler(debuglevel=1))
    handlers.append(urllib.request.HTTPSHandler(debuglevel=1))
  urllib.request.install_opener(urllib.request.build_opener(*handlers))


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
      name, gopts, argv = repo._ParseArgs(argv)
      run = lambda: repo._Run(name, gopts, argv) or 0
      if gopts.trace_python:
        import trace
        tracer = trace.Trace(count=False, trace=True, timing=True,
                             ignoredirs=set(sys.path[1:]))
        result = tracer.runfunc(run)
      else:
        result = run()
    finally:
      close_ssh()
  except KeyboardInterrupt:
    print('aborted by user', file=sys.stderr)
    result = 1
  except ManifestParseError as mpe:
    print('fatal: %s' % mpe, file=sys.stderr)
    result = 1
  except RepoChangedException as rce:
    # If repo changed, re-exec ourselves.
    #
    argv = list(sys.argv)
    argv.extend(rce.extra_args)
    try:
      os.execv(__file__, argv)
    except OSError as e:
      print('fatal: cannot restart repo after upgrade', file=sys.stderr)
      print('fatal: %s' % e, file=sys.stderr)
      result = 128

  TerminatePager()
  sys.exit(result)


if __name__ == '__main__':
  _Main(sys.argv[1:])
