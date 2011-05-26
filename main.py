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

import optparse
import os
import re
import sys

from trace import SetTrace
from git_config import init_ssh, close_ssh
from command import InteractiveCommand
from command import MirrorSafeCommand
from command import PagedCommand
from error import ManifestInvalidRevisionError
from error import NoSuchProjectError
from error import RepoChangedException
from pager import RunPager

from subcmds import all as all_commands

# TODO: When python2 is no longer supported, do the following:
# * s/_print/print/
# * Delete the following block of code
# BEGIN PYTHON2 DUCK PUNCHING, etc
# Normally, we would get print, etc. by doing:
# from __future__ import print_function, etc.
# but the bash magic prevents us from doing that since that must be done at the
# beginning of the file
def _print(*args, **kwargs):
  kwargs.get('file', sys.stdout).write(' '.join(args) + '\n')
try:
  range=xrange
  # If we get here, we are using python2
except NameError:
  pass
# END PYTHON2 DUCK PUNCHING, etc

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
    name = None
    glob = []

    for i in range(0, len(argv)):
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
        _print('fatal: invalid usage of --version', file=sys.stderr)
        sys.exit(1)

    try:
      cmd = self.commands[name]
    except KeyError:
     _print("repo: '%s' is not a repo command.  See 'repo help'." % name,
            file=sys.stderr)
      sys.exit(1)

    cmd.repodir = self.repodir

    if not isinstance(cmd, MirrorSafeCommand) and cmd.manifest.IsMirror:
      _print("fatal: '%s' requires a working directory" % name, file=sys.stderr)
      sys.exit(1)

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
      cmd.Execute(copts, cargs)
    except ManifestInvalidRevisionError as e:
      _print('error: %s' % str(e), file=sys.stderr)
      sys.exit(1)
    except NoSuchProjectError as e:
      if e.name:
        _print('error: project %s not found' % e.name, file=sys.stderr)
      else:
        _print('error: no project in current directory', file=sys.stderr)
      sys.exit(1)

def _MyWrapperPath():
  return os.path.join(os.path.dirname(__file__), 'repo')

def _CurrentWrapperVersion():
  VERSION = None
  pat = re.compile(r'VERSION *= (.*)')
  fd = open(_MyWrapperPath())
  for line in fd:
    match = pat.match(line)
    if match:
      fd.close()
      VERSION = eval(match.group(1))
      return VERSION
  raise NameError('No VERSION in repo script')

def _CheckWrapperVersion(ver, repo_path):
  if not repo_path:
    repo_path = '~/bin/repo'

  if not ver:
     _print('no --wrapper-version argument', file=sys.stderr)
     sys.exit(1)

  exp = _CurrentWrapperVersion()
  ver = tuple(map(lambda x: int(x), ver.split('.')))
  if len(ver) == 1:
    ver = (0, ver[0])

  if exp[0] > ver[0] or ver < (0, 4):
    exp_str = '.'.join(map(lambda x: str(x), exp))
    _print(file=sys.stderr)
    _print('!!! A new repo command (%5s) is available.    !!!' % exp_str,
           file=sys.stderr)
    _print('!!! You must upgrade before you can continue:   !!!',
           file=sys.stderr)
    _print(file=sys.stderr)
    _print('    cp %s %s' % (_MyWrapperPath(), repo_path), file=sys.stderr)
    _print(file=sys.stderr)
    sys.exit(1)

  if exp > ver:
    exp_str = '.'.join(map(lambda x: str(x), exp))
    _print(file=sys.stderr)
    _print('... A new repo command (%5s) is available.' % exp_str,
           file=sys.stderr)
    _print('... You should upgrade soon.' % exp_str, file=sys.stderr)
    _print(file=sys.stderr)
    _print('    cp %s %s' % (_MyWrapperPath(), repo_path), file=sys.stderr)
    _print(file=sys.stderr)

def _CheckRepoDir(dir):
  if not dir:
     _print('no --repo-dir argument', file=sys.stderr)
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

def _Main(argv):
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

  repo = _Repo(opt.repodir)
  try:
    try:
      init_ssh()
      repo._Run(argv)
    finally:
      close_ssh()
  except KeyboardInterrupt:
    sys.exit(1)
  except RepoChangedException as rce:
    # If repo changed, re-exec ourselves.
    #
    argv = list(sys.argv)
    argv.extend(rce.extra_args)
    try:
      os.execv(__file__, argv)
    except OSError as e:
      _print('fatal: cannot restart repo after upgrade', file=sys.stderr)
      _print('fatal: %s' % e, file=sys.stderr)
      sys.exit(128)

if __name__ == '__main__':
  _Main(sys.argv[1:])
