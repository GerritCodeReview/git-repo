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
import sys

from color import Coloring
from command import InteractiveCommand, MirrorSafeCommand
from error import ManifestParseError
from remote import Remote
from project import SyncBuffer
from git_command import git, MIN_GIT_VERSION

class Init(InteractiveCommand, MirrorSafeCommand):
  common = True
  helpSummary = "Initialize repo in the current directory"
  helpUsage = """
%prog [options]
"""
  helpDescription = """
The '%prog' command is run once to install and initialize repo.
The latest repo source code and manifest collection is downloaded
from the server and is installed in the .repo/ directory in the
current working directory.

The optional <manifest> argument can be used to specify an alternate
manifest to be used. If no manifest is specified, the manifest
default.xml will be used.
"""

  def _Options(self, p):
    # Logging
    g = p.add_option_group('Logging options')
    g.add_option('-q', '--quiet',
                 dest="quiet", action="store_true", default=False,
                 help="be quiet")

    # Manifest
    g = p.add_option_group('Manifest options')
    g.add_option('-u', '--manifest-url',
                 dest='manifest_url',
                 help='manifest repository location', metavar='URL')
    g.add_option('-b', '--manifest-branch',
                 dest='manifest_branch',
                 help='manifest branch or revision', metavar='REVISION')
    g.add_option('-m', '--manifest-name',
                 dest='manifest_name', default='default.xml',
                 help='initial manifest file', metavar='NAME.xml')
    g.add_option('--mirror',
                 dest='mirror', action='store_true',
                 help='mirror the forrest')


    # Tool
    g = p.add_option_group('Version options')
    g.add_option('--repo-url',
                 dest='repo_url',
                 help='repo repository location', metavar='URL')
    g.add_option('--repo-branch',
                 dest='repo_branch',
                 help='repo branch or revision', metavar='REVISION')
    g.add_option('--no-repo-verify',
                 dest='no_repo_verify', action='store_true',
                 help='do not verify repo source code')

  def _CheckGitVersion(self):
    ver_str = git.version()
    if not ver_str.startswith('git version '):
      print >>sys.stderr, 'error: "%s" unsupported' % ver_str
      sys.exit(1)

    ver_str = ver_str[len('git version '):].strip()
    ver_act = tuple(map(lambda x: int(x), ver_str.split('.')[0:3]))
    if ver_act < MIN_GIT_VERSION:
      need = '.'.join(map(lambda x: str(x), MIN_GIT_VERSION))
      print >>sys.stderr, 'fatal: git %s or later required' % need
      sys.exit(1)

  def _SyncManifest(self, opt):
    m = self.manifest.manifestProject
    is_new = not m.Exists

    if is_new:
      if not opt.manifest_url:
        print >>sys.stderr, 'fatal: manifest url (-u) is required.'
        sys.exit(1)

      if not opt.quiet:
        print >>sys.stderr, 'Getting manifest ...'
        print >>sys.stderr, '   from %s' % opt.manifest_url
      m._InitGitDir()

      if opt.manifest_branch:
        m.revision = opt.manifest_branch
      else:
        m.revision = 'refs/heads/master'
    else:
      if opt.manifest_branch:
        m.revision = opt.manifest_branch
      else:
        m.PreSync()

    if opt.manifest_url:
      r = m.GetRemote(m.remote.name)
      r.url = opt.manifest_url
      r.ResetFetch()
      r.Save()

    if opt.mirror:
      if is_new:
        m.config.SetString('repo.mirror', 'true')
      else:
        print >>sys.stderr, 'fatal: --mirror not supported on existing client'
        sys.exit(1)

    if not m.Sync_NetworkHalf():
      r = m.GetRemote(m.remote.name)
      print >>sys.stderr, 'fatal: cannot obtain manifest %s' % r.url
      sys.exit(1)

    syncbuf = SyncBuffer(m.config)
    m.Sync_LocalHalf(syncbuf)
    syncbuf.Finish()

    if is_new or m.CurrentBranch is None:
      if not m.StartBranch('default'):
        print >>sys.stderr, 'fatal: cannot create default in manifest'
        sys.exit(1)

  def _LinkManifest(self, name):
    if not name:
      print >>sys.stderr, 'fatal: manifest name (-m) is required.'
      sys.exit(1)

    try:
      self.manifest.Link(name)
    except ManifestParseError, e:
      print >>sys.stderr, "fatal: manifest '%s' not available" % name
      print >>sys.stderr, 'fatal: %s' % str(e)
      sys.exit(1)

  def _PromptKey(self, prompt, key, value):
    mp = self.manifest.manifestProject

    sys.stdout.write('%-10s [%s]: ' % (prompt, value))
    a = sys.stdin.readline().strip()
    if a != '' and a != value:
      mp.config.SetString(key, a)

  def _ConfigureUser(self):
    mp = self.manifest.manifestProject

    print ''
    self._PromptKey('Your Name', 'user.name', mp.UserName)
    self._PromptKey('Your Email', 'user.email', mp.UserEmail)

  def _HasColorSet(self, gc):
    for n in ['ui', 'diff', 'status']:
      if gc.Has('color.%s' % n):
        return True
    return False

  def _ConfigureColor(self):
    gc = self.manifest.globalConfig
    if self._HasColorSet(gc):
      return

    class _Test(Coloring):
      def __init__(self):
        Coloring.__init__(self, gc, 'test color display')
        self._on = True
    out = _Test()

    print ''
    print "Testing colorized output (for 'repo diff', 'repo status'):"

    for c in ['black','red','green','yellow','blue','magenta','cyan']:
      out.write(' ')
      out.printer(fg=c)(' %-6s ', c)
    out.write(' ')
    out.printer(fg='white', bg='black')(' %s ' % 'white')
    out.nl()

    for c in ['bold','dim','ul','reverse']:
      out.write(' ')
      out.printer(fg='black', attr=c)(' %-6s ', c)
    out.nl()

    sys.stdout.write('Enable color display in this user account (y/n)? ')
    a = sys.stdin.readline().strip().lower()
    if a in ('y', 'yes', 't', 'true', 'on'):
      gc.SetString('color.ui', 'auto')

  def Execute(self, opt, args):
    self._CheckGitVersion()
    self._SyncManifest(opt)
    self._LinkManifest(opt.manifest_name)

    if os.isatty(0) and os.isatty(1) and not self.manifest.IsMirror:
      self._ConfigureUser()
      self._ConfigureColor()

    if self.manifest.IsMirror:
      type = 'mirror '
    else:
      type = ''

    print ''
    print 'repo %sinitialized in %s' % (type, self.manifest.topdir)
