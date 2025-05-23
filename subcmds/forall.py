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

import errno
import functools
import io
import multiprocessing
import re
import os
import signal
import sys
import subprocess

from color import Coloring
from command import DEFAULT_LOCAL_JOBS, Command, MirrorSafeCommand, WORKER_BATCH_SIZE
from error import ManifestInvalidRevisionError

_CAN_COLOR = [
    'branch',
    'diff',
    'grep',
    'log',
]


class ForallColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'forall')
    self.project = self.printer('project', attr='bold')


class Forall(Command, MirrorSafeCommand):
  COMMON = False
  helpSummary = "Run a shell command in each project"
  helpUsage = """
%prog [<project>...] -c <command> [<arg>...]
%prog -r str1 [str2] ... -c <command> [<arg>...]
"""
  helpDescription = """
Executes the same shell command in each project.

The -r option allows running the command only on projects matching
regex or wildcard expression.

By default, projects are processed non-interactively in parallel.  If you want
to run interactive commands, make sure to pass --interactive to force --jobs 1.
While the processing order of projects is not guaranteed, the order of project
output is stable.

# Output Formatting

The -p option causes '%prog' to bind pipes to the command's stdin,
stdout and stderr streams, and pipe all output into a continuous
stream that is displayed in a single pager session.  Project headings
are inserted before the output of each command is displayed.  If the
command produces no output in a project, no heading is displayed.

The formatting convention used by -p is very suitable for some
types of searching, e.g. `repo forall -p -c git log -SFoo` will
print all commits that add or remove references to Foo.

The -v option causes '%prog' to display stderr messages if a
command produces output only on stderr.  Normally the -p option
causes command output to be suppressed until the command produces
at least one byte of output on stdout.

# Environment

pwd is the project's working directory.  If the current client is
a mirror client, then pwd is the Git repository.

REPO_PROJECT is set to the unique name of the project.

REPO_PATH is the path relative the the root of the client.

REPO_OUTERPATH is the path of the sub manifest's root relative to the root of
the client.

REPO_INNERPATH is the path relative to the root of the sub manifest.

REPO_REMOTE is the name of the remote system from the manifest.

REPO_LREV is the name of the revision from the manifest, translated
to a local tracking branch.  If you need to pass the manifest
revision to a locally executed git command, use REPO_LREV.

REPO_RREV is the name of the revision from the manifest, exactly
as written in the manifest.

REPO_COUNT is the total number of projects being iterated.

REPO_I is the current (1-based) iteration count. Can be used in
conjunction with REPO_COUNT to add a simple progress indicator to your
command.

REPO__* are any extra environment variables, specified by the
"annotation" element under any project element.  This can be useful
for differentiating trees based on user-specific criteria, or simply
annotating tree details.

shell positional arguments ($1, $2, .., $#) are set to any arguments
following <command>.

Example: to list projects:

  %prog -c 'echo $REPO_PROJECT'

Notice that $REPO_PROJECT is quoted to ensure it is expanded in
the context of running <command> instead of in the calling shell.

Unless -p is used, stdin, stdout, stderr are inherited from the
terminal and are not redirected.

If -e is used, when a command exits unsuccessfully, '%prog' will abort
without iterating through the remaining projects.
"""
  PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

  @staticmethod
  def _cmd_option(option, _opt_str, _value, parser):
    setattr(parser.values, option.dest, list(parser.rargs))
    while parser.rargs:
      del parser.rargs[0]

  def _Options(self, p):
    p.add_option('-r', '--regex',
                 dest='regex', action='store_true',
                 help='execute the command only on projects matching regex or wildcard expression')
    p.add_option('-i', '--inverse-regex',
                 dest='inverse_regex', action='store_true',
                 help='execute the command only on projects not matching regex or '
                      'wildcard expression')
    p.add_option('-g', '--groups',
                 dest='groups',
                 help='execute the command only on projects matching the specified groups')
    p.add_option('-c', '--command',
                 help='command (and arguments) to execute',
                 dest='command',
                 action='callback',
                 callback=self._cmd_option)
    p.add_option('-e', '--abort-on-errors',
                 dest='abort_on_errors', action='store_true',
                 help='abort if a command exits unsuccessfully')
    p.add_option('--ignore-missing', action='store_true',
                 help='silently skip & do not exit non-zero due missing '
                      'checkouts')

    g = p.get_option_group('--quiet')
    g.add_option('-p',
                 dest='project_header', action='store_true',
                 help='show project headers before output')
    p.add_option('--interactive',
                 action='store_true',
                 help='force interactive usage')

  def WantPager(self, opt):
    return opt.project_header and opt.jobs == 1

  def ValidateOptions(self, opt, args):
    if not opt.command:
      self.Usage()

  def Execute(self, opt, args):
    cmd = [opt.command[0]]
    all_trees = not opt.this_manifest_only

    shell = True
    if re.compile(r'^[a-z0-9A-Z_/\.-]+$').match(cmd[0]):
      shell = False

    if shell:
      cmd.append(cmd[0])
    cmd.extend(opt.command[1:])

    # Historically, forall operated interactively, and in serial.  If the user
    # has selected 1 job, then default to interacive mode.
    if opt.jobs == 1:
      opt.interactive = True

    if opt.project_header \
            and not shell \
            and cmd[0] == 'git':
      # If this is a direct git command that can enable colorized
      # output and the user prefers coloring, add --color into the
      # command line because we are going to wrap the command into
      # a pipe and git won't know coloring should activate.
      #
      for cn in cmd[1:]:
        if not cn.startswith('-'):
          break
      else:
        cn = None
      if cn and cn in _CAN_COLOR:
        class ColorCmd(Coloring):
          def __init__(self, config, cmd):
            Coloring.__init__(self, config, cmd)
        if ColorCmd(self.manifest.manifestProject.config, cn).is_on:
          cmd.insert(cmd.index(cn) + 1, '--color')

    mirror = self.manifest.IsMirror
    rc = 0

    smart_sync_manifest_name = "smart_sync_override.xml"
    smart_sync_manifest_path = os.path.join(
        self.manifest.manifestProject.worktree, smart_sync_manifest_name)

    if os.path.isfile(smart_sync_manifest_path):
      self.manifest.Override(smart_sync_manifest_path)

    if opt.regex:
      projects = self.FindProjects(args, all_manifests=all_trees)
    elif opt.inverse_regex:
      projects = self.FindProjects(args, inverse=True, all_manifests=all_trees)
    else:
      projects = self.GetProjects(args, groups=opt.groups, all_manifests=all_trees)

    os.environ['REPO_COUNT'] = str(len(projects))

    try:
      config = self.manifest.manifestProject.config
      with multiprocessing.Pool(opt.jobs, InitWorker) as pool:
        results_it = pool.imap(
            functools.partial(DoWorkWrapper, mirror, opt, cmd, shell, config),
            enumerate(projects),
            chunksize=WORKER_BATCH_SIZE)
        first = True
        for (r, output) in results_it:
          if output:
            if first:
              first = False
            elif opt.project_header:
              print()
            # To simplify the DoWorkWrapper, take care of automatic newlines.
            end = '\n'
            if output[-1] == '\n':
              end = ''
            print(output, end=end)
          rc = rc or r
          if r != 0 and opt.abort_on_errors:
            raise Exception('Aborting due to previous error')
    except (KeyboardInterrupt, WorkerKeyboardInterrupt):
      # Catch KeyboardInterrupt raised inside and outside of workers
      rc = rc or errno.EINTR
    except Exception as e:
      # Catch any other exceptions raised
      print('forall: unhandled error, terminating the pool: %s: %s' %
            (type(e).__name__, e),
            file=sys.stderr)
      rc = rc or getattr(e, 'errno', 1)
    if rc != 0:
      sys.exit(rc)


class WorkerKeyboardInterrupt(Exception):
  """ Keyboard interrupt exception for worker processes. """


def InitWorker():
  signal.signal(signal.SIGINT, signal.SIG_IGN)


def DoWorkWrapper(mirror, opt, cmd, shell, config, args):
  """ A wrapper around the DoWork() method.

  Catch the KeyboardInterrupt exceptions here and re-raise them as a different,
  ``Exception``-based exception to stop it flooding the console with stacktraces
  and making the parent hang indefinitely.

  """
  cnt, project = args
  try:
    return DoWork(project, mirror, opt, cmd, shell, cnt, config)
  except KeyboardInterrupt:
    print('%s: Worker interrupted' % project.name)
    raise WorkerKeyboardInterrupt()


def DoWork(project, mirror, opt, cmd, shell, cnt, config):
  env = os.environ.copy()

  def setenv(name, val):
    if val is None:
      val = ''
    env[name] = val

  setenv('REPO_PROJECT', project.name)
  setenv('REPO_OUTERPATH', project.manifest.path_prefix)
  setenv('REPO_INNERPATH', project.relpath)
  setenv('REPO_PATH', project.RelPath(local=opt.this_manifest_only))
  setenv('REPO_REMOTE', project.remote.name)
  try:
    # If we aren't in a fully synced state and we don't have the ref the manifest
    # wants, then this will fail.  Ignore it for the purposes of this code.
    lrev = '' if mirror else project.GetRevisionId()
  except ManifestInvalidRevisionError:
    lrev = ''
  setenv('REPO_LREV', lrev)
  setenv('REPO_RREV', project.revisionExpr)
  setenv('REPO_UPSTREAM', project.upstream)
  setenv('REPO_DEST_BRANCH', project.dest_branch)
  setenv('REPO_I', str(cnt + 1))
  for annotation in project.annotations:
    setenv("REPO__%s" % (annotation.name), annotation.value)

  if mirror:
    setenv('GIT_DIR', project.gitdir)
    cwd = project.gitdir
  else:
    cwd = project.worktree

  if not os.path.exists(cwd):
    # Allow the user to silently ignore missing checkouts so they can run on
    # partial checkouts (good for infra recovery tools).
    if opt.ignore_missing:
      return (0, '')

    output = ''
    if ((opt.project_header and opt.verbose)
            or not opt.project_header):
      output = 'skipping %s/' % project.RelPath(local=opt.this_manifest_only)
    return (1, output)

  if opt.verbose:
    stderr = subprocess.STDOUT
  else:
    stderr = subprocess.DEVNULL

  stdin = None if opt.interactive else subprocess.DEVNULL

  result = subprocess.run(
      cmd, cwd=cwd, shell=shell, env=env, check=False,
      encoding='utf-8', errors='replace',
      stdin=stdin, stdout=subprocess.PIPE, stderr=stderr)

  output = result.stdout
  if opt.project_header:
    if output:
      buf = io.StringIO()
      out = ForallColoring(config)
      out.redirect(buf)
      if mirror:
        project_header_path = project.name
      else:
        project_header_path = project.RelPath(local=opt.this_manifest_only)
      out.project('project %s/' % project_header_path)
      out.nl()
      buf.write(output)
      output = buf.getvalue()
  return (result.returncode, output)
