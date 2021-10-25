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
import platform
import re
import subprocess
import sys
import urllib.parse

from color import Coloring
from command import InteractiveCommand, MirrorSafeCommand
from error import ManifestParseError
from project import SyncBuffer
from git_config import GitConfig
from git_command import git_require, MIN_GIT_VERSION_SOFT, MIN_GIT_VERSION_HARD
import fetch
import git_superproject
import platform_utils
from wrapper import Wrapper


class Init(InteractiveCommand, MirrorSafeCommand):
  COMMON = True
  helpSummary = "Initialize a repo client checkout in the current directory"
  helpUsage = """
%prog [options] [manifest url]
"""
  helpDescription = """
The '%prog' command is run once to install and initialize repo.
The latest repo source code and manifest collection is downloaded
from the server and is installed in the .repo/ directory in the
current working directory.

When creating a new checkout, the manifest URL is the only required setting.
It may be specified using the --manifest-url option, or as the first optional
argument.

The optional -b argument can be used to select the manifest branch
to checkout and use.  If no branch is specified, the remote's default
branch is used.  This is equivalent to using -b HEAD.

The optional -m argument can be used to specify an alternate manifest
to be used. If no manifest is specified, the manifest default.xml
will be used.

If the --standalone-manifest argument is set, the manifest will be downloaded
directly from the specified --manifest-url as a static file (rather than
setting up a manifest git checkout). With --standalone-manifest, the manifest
will be fully static and will not be re-downloaded during subsesquent
`repo init` and `repo sync` calls.

The --reference option can be used to point to a directory that
has the content of a --mirror sync. This will make the working
directory use as much data as possible from the local reference
directory when fetching from the server. This will make the sync
go a lot faster by reducing data traffic on the network.

The --dissociate option can be used to borrow the objects from
the directory specified with the --reference option only to reduce
network transfer, and stop borrowing from them after a first clone
is made by making necessary local copies of borrowed objects.

The --no-clone-bundle option disables any attempt to use
$URL/clone.bundle to bootstrap a new Git repository from a
resumeable bundle file on a content delivery network. This
may be necessary if there are problems with the local Python
HTTP client or proxy configuration, but the Git binary works.

# Switching Manifest Branches

To switch to another manifest branch, `repo init -b otherbranch`
may be used in an existing client.  However, as this only updates the
manifest, a subsequent `repo sync` (or `repo sync -d`) is necessary
to update the working directory files.
"""

  def _CommonOptions(self, p):
    """Disable due to re-use of Wrapper()."""

  def _Options(self, p, gitc_init=False):
    Wrapper().InitParser(p, gitc_init=gitc_init)

  def _RegisteredEnvironmentOptions(self):
    return {'REPO_MANIFEST_URL': 'manifest_url',
            'REPO_MIRROR_LOCATION': 'reference'}

  def _CloneSuperproject(self, opt):
    """Clone the superproject based on the superproject's url and branch.

    Args:
      opt: Program options returned from optparse.  See _Options().
    """
    superproject = git_superproject.Superproject(self.manifest,
                                                 self.repodir,
                                                 self.git_event_log,
                                                 quiet=opt.quiet)
    sync_result = superproject.Sync()
    if not sync_result.success:
      print('warning: git update of superproject failed, repo sync will not '
            'use superproject to fetch source; while this error is not fatal, '
            'and you can continue to run repo sync, please run repo init with '
            'the --no-use-superproject option to stop seeing this warning',
            file=sys.stderr)
      if sync_result.fatal and opt.use_superproject is not None:
        sys.exit(1)

  def _SyncManifest(self, opt):
    m = self.manifest.manifestProject
    is_new = not m.Exists

    # If repo has already been initialized, we take -u with the absence of
    # --standalone-manifest to mean "transition to a standard repo set up",
    # which necessitates starting fresh.
    # If --standalone-manifest is set, we always tear everything down and start
    # anew.
    if not is_new:
      was_standalone_manifest = m.config.GetString('manifest.standalone')
      if was_standalone_manifest and not opt.manifest_url:
        print('fatal: repo was initialized with a standlone manifest, '
              'cannot be re-initialized without --manifest-url/-u')
        sys.exit(1)

      if opt.standalone_manifest or (
          was_standalone_manifest and opt.manifest_url):
        m.config.ClearCache()
        if m.gitdir and os.path.exists(m.gitdir):
          platform_utils.rmtree(m.gitdir)
        if m.worktree and os.path.exists(m.worktree):
          platform_utils.rmtree(m.worktree)

    is_new = not m.Exists
    if is_new:
      if not opt.manifest_url:
        print('fatal: manifest url is required.', file=sys.stderr)
        sys.exit(1)

      if not opt.quiet:
        print('Downloading manifest from %s' %
              (GitConfig.ForUser().UrlInsteadOf(opt.manifest_url),),
              file=sys.stderr)

      # The manifest project object doesn't keep track of the path on the
      # server where this git is located, so let's save that here.
      mirrored_manifest_git = None
      if opt.reference:
        manifest_git_path = urllib.parse.urlparse(opt.manifest_url).path[1:]
        mirrored_manifest_git = os.path.join(opt.reference, manifest_git_path)
        if not mirrored_manifest_git.endswith(".git"):
          mirrored_manifest_git += ".git"
        if not os.path.exists(mirrored_manifest_git):
          mirrored_manifest_git = os.path.join(opt.reference,
                                               '.repo/manifests.git')

      m._InitGitDir(mirror_git=mirrored_manifest_git)

    # If standalone_manifest is set, mark the project as "standalone" -- we'll
    # still do much of the manifests.git set up, but will avoid actual syncs to
    # a remote.
    standalone_manifest = False
    if opt.standalone_manifest:
      standalone_manifest = True
      m.config.SetString('manifest.standalone', opt.manifest_url)
    elif not opt.manifest_url and not opt.manifest_branch:
      # If -u is set and --standalone-manifest is not, then we're not in
      # standalone mode. Otherwise, use config to infer what we were in the last
      # init.
      standalone_manifest = bool(m.config.GetString('manifest.standalone'))
    if not standalone_manifest:
      m.config.SetString('manifest.standalone', None)

    self._ConfigureDepth(opt)

    # Set the remote URL before the remote branch as we might need it below.
    if opt.manifest_url:
      r = m.GetRemote(m.remote.name)
      r.url = opt.manifest_url
      r.ResetFetch()
      r.Save()

    if not standalone_manifest:
      if opt.manifest_branch:
        if opt.manifest_branch == 'HEAD':
          opt.manifest_branch = m.ResolveRemoteHead()
          if opt.manifest_branch is None:
            print('fatal: unable to resolve HEAD', file=sys.stderr)
            sys.exit(1)
        m.revisionExpr = opt.manifest_branch
      else:
        if is_new:
          default_branch = m.ResolveRemoteHead()
          if default_branch is None:
            # If the remote doesn't have HEAD configured, default to master.
            default_branch = 'refs/heads/master'
          m.revisionExpr = default_branch
        else:
          m.PreSync()

    groups = re.split(r'[,\s]+', opt.groups)
    all_platforms = ['linux', 'darwin', 'windows']
    platformize = lambda x: 'platform-' + x
    if opt.platform == 'auto':
      if (not opt.mirror and
              not m.config.GetString('repo.mirror') == 'true'):
        groups.append(platformize(platform.system().lower()))
    elif opt.platform == 'all':
      groups.extend(map(platformize, all_platforms))
    elif opt.platform in all_platforms:
      groups.append(platformize(opt.platform))
    elif opt.platform != 'none':
      print('fatal: invalid platform flag', file=sys.stderr)
      sys.exit(1)

    groups = [x for x in groups if x]
    groupstr = ','.join(groups)
    if opt.platform == 'auto' and groupstr == self.manifest.GetDefaultGroupsStr():
      groupstr = None
    m.config.SetString('manifest.groups', groupstr)

    if opt.reference:
      m.config.SetString('repo.reference', opt.reference)

    if opt.dissociate:
      m.config.SetBoolean('repo.dissociate', opt.dissociate)

    if opt.worktree:
      if opt.mirror:
        print('fatal: --mirror and --worktree are incompatible',
              file=sys.stderr)
        sys.exit(1)
      if opt.submodules:
        print('fatal: --submodules and --worktree are incompatible',
              file=sys.stderr)
        sys.exit(1)
      m.config.SetBoolean('repo.worktree', opt.worktree)
      if is_new:
        m.use_git_worktrees = True
      print('warning: --worktree is experimental!', file=sys.stderr)

    if opt.archive:
      if is_new:
        m.config.SetBoolean('repo.archive', opt.archive)
      else:
        print('fatal: --archive is only supported when initializing a new '
              'workspace.', file=sys.stderr)
        print('Either delete the .repo folder in this workspace, or initialize '
              'in another location.', file=sys.stderr)
        sys.exit(1)

    if opt.mirror:
      if is_new:
        m.config.SetBoolean('repo.mirror', opt.mirror)
      else:
        print('fatal: --mirror is only supported when initializing a new '
              'workspace.', file=sys.stderr)
        print('Either delete the .repo folder in this workspace, or initialize '
              'in another location.', file=sys.stderr)
        sys.exit(1)

    if opt.partial_clone is not None:
      if opt.mirror:
        print('fatal: --mirror and --partial-clone are mutually exclusive',
              file=sys.stderr)
        sys.exit(1)
      m.config.SetBoolean('repo.partialclone', opt.partial_clone)
      if opt.clone_filter:
        m.config.SetString('repo.clonefilter', opt.clone_filter)
    elif m.config.GetBoolean('repo.partialclone'):
      opt.clone_filter = m.config.GetString('repo.clonefilter')
    else:
      opt.clone_filter = None

    if opt.partial_clone_exclude is not None:
      m.config.SetString('repo.partialcloneexclude', opt.partial_clone_exclude)

    if opt.clone_bundle is None:
      opt.clone_bundle = False if opt.partial_clone else True
    else:
      m.config.SetBoolean('repo.clonebundle', opt.clone_bundle)

    if opt.submodules:
      m.config.SetBoolean('repo.submodules', opt.submodules)

    if opt.use_superproject is not None:
      m.config.SetBoolean('repo.superproject', opt.use_superproject)

    if standalone_manifest:
      if is_new:
        manifest_name = 'default.xml'
        manifest_data = fetch.fetch_file(opt.manifest_url, verbose=opt.verbose)
        dest = os.path.join(m.worktree, manifest_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as f:
          f.write(manifest_data)
      return

    if not m.Sync_NetworkHalf(is_new=is_new, quiet=opt.quiet, verbose=opt.verbose,
                              clone_bundle=opt.clone_bundle,
                              current_branch_only=opt.current_branch_only,
                              tags=opt.tags, submodules=opt.submodules,
                              clone_filter=opt.clone_filter,
                              partial_clone_exclude=self.manifest.PartialCloneExclude):
      r = m.GetRemote(m.remote.name)
      print('fatal: cannot obtain manifest %s' % r.url, file=sys.stderr)

      # Better delete the manifest git dir if we created it; otherwise next
      # time (when user fixes problems) we won't go through the "is_new" logic.
      if is_new:
        platform_utils.rmtree(m.gitdir)
      sys.exit(1)

    if opt.manifest_branch:
      m.MetaBranchSwitch(submodules=opt.submodules)

    syncbuf = SyncBuffer(m.config)
    m.Sync_LocalHalf(syncbuf, submodules=opt.submodules)
    syncbuf.Finish()

    if is_new or m.CurrentBranch is None:
      if not m.StartBranch('default'):
        print('fatal: cannot create default in manifest', file=sys.stderr)
        sys.exit(1)

  def _LinkManifest(self, name):
    if not name:
      print('fatal: manifest name (-m) is required.', file=sys.stderr)
      sys.exit(1)

    try:
      self.manifest.Link(name)
    except ManifestParseError as e:
      print("fatal: manifest '%s' not available" % name, file=sys.stderr)
      print('fatal: %s' % str(e), file=sys.stderr)
      sys.exit(1)

  def _Prompt(self, prompt, value):
    print('%-10s [%s]: ' % (prompt, value), end='')
    # TODO: When we require Python 3, use flush=True w/print above.
    sys.stdout.flush()
    a = sys.stdin.readline().strip()
    if a == '':
      return value
    return a

  def _ShouldConfigureUser(self, opt):
    gc = self.client.globalConfig
    mp = self.manifest.manifestProject

    # If we don't have local settings, get from global.
    if not mp.config.Has('user.name') or not mp.config.Has('user.email'):
      if not gc.Has('user.name') or not gc.Has('user.email'):
        return True

      mp.config.SetString('user.name', gc.GetString('user.name'))
      mp.config.SetString('user.email', gc.GetString('user.email'))

    if not opt.quiet:
      print()
      print('Your identity is: %s <%s>' % (mp.config.GetString('user.name'),
                                           mp.config.GetString('user.email')))
      print("If you want to change this, please re-run 'repo init' with --config-name")
    return False

  def _ConfigureUser(self, opt):
    mp = self.manifest.manifestProject

    while True:
      if not opt.quiet:
        print()
      name = self._Prompt('Your Name', mp.UserName)
      email = self._Prompt('Your Email', mp.UserEmail)

      if not opt.quiet:
        print()
      print('Your identity is: %s <%s>' % (name, email))
      print('is this correct [y/N]? ', end='')
      # TODO: When we require Python 3, use flush=True w/print above.
      sys.stdout.flush()
      a = sys.stdin.readline().strip().lower()
      if a in ('yes', 'y', 't', 'true'):
        break

    if name != mp.UserName:
      mp.config.SetString('user.name', name)
    if email != mp.UserEmail:
      mp.config.SetString('user.email', email)

  def _HasColorSet(self, gc):
    for n in ['ui', 'diff', 'status']:
      if gc.Has('color.%s' % n):
        return True
    return False

  def _ConfigureColor(self):
    gc = self.client.globalConfig
    if self._HasColorSet(gc):
      return

    class _Test(Coloring):
      def __init__(self):
        Coloring.__init__(self, gc, 'test color display')
        self._on = True
    out = _Test()

    print()
    print("Testing colorized output (for 'repo diff', 'repo status'):")

    for c in ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan']:
      out.write(' ')
      out.printer(fg=c)(' %-6s ', c)
    out.write(' ')
    out.printer(fg='white', bg='black')(' %s ' % 'white')
    out.nl()

    for c in ['bold', 'dim', 'ul', 'reverse']:
      out.write(' ')
      out.printer(fg='black', attr=c)(' %-6s ', c)
    out.nl()

    print('Enable color display in this user account (y/N)? ', end='')
    # TODO: When we require Python 3, use flush=True w/print above.
    sys.stdout.flush()
    a = sys.stdin.readline().strip().lower()
    if a in ('y', 'yes', 't', 'true', 'on'):
      gc.SetString('color.ui', 'auto')

  def _ConfigureDepth(self, opt):
    """Configure the depth we'll sync down.

    Args:
      opt: Options from optparse.  We care about opt.depth.
    """
    # Opt.depth will be non-None if user actually passed --depth to repo init.
    if opt.depth is not None:
      if opt.depth > 0:
        # Positive values will set the depth.
        depth = str(opt.depth)
      else:
        # Negative numbers will clear the depth; passing None to SetString
        # will do that.
        depth = None

      # We store the depth in the main manifest project.
      self.manifest.manifestProject.config.SetString('repo.depth', depth)

  def _DisplayResult(self, opt):
    if self.manifest.IsMirror:
      init_type = 'mirror '
    else:
      init_type = ''

    if not opt.quiet:
      print()
      print('repo %shas been initialized in %s' %
            (init_type, self.manifest.topdir))

    current_dir = os.getcwd()
    if current_dir != self.manifest.topdir:
      print('If this is not the directory in which you want to initialize '
            'repo, please run:')
      print('   rm -r %s/.repo' % self.manifest.topdir)
      print('and try again.')

  def ValidateOptions(self, opt, args):
    if opt.reference:
      opt.reference = os.path.expanduser(opt.reference)

    # Check this here, else manifest will be tagged "not new" and init won't be
    # possible anymore without removing the .repo/manifests directory.
    if opt.archive and opt.mirror:
      self.OptionParser.error('--mirror and --archive cannot be used together.')

    if opt.standalone_manifest and (
        opt.manifest_branch or opt.manifest_name != 'default.xml'):
      self.OptionParser.error('--manifest-branch and --manifest-name cannot'
                              ' be used with --standalone-manifest.')

    if args:
      if opt.manifest_url:
        self.OptionParser.error(
            '--manifest-url option and URL argument both specified: only use '
            'one to select the manifest URL.')

      opt.manifest_url = args.pop(0)

      if args:
        self.OptionParser.error('too many arguments to init')

  def Execute(self, opt, args):
    git_require(MIN_GIT_VERSION_HARD, fail=True)
    if not git_require(MIN_GIT_VERSION_SOFT):
      print('repo: warning: git-%s+ will soon be required; please upgrade your '
            'version of git to maintain support.'
            % ('.'.join(str(x) for x in MIN_GIT_VERSION_SOFT),),
            file=sys.stderr)

    rp = self.manifest.repoProject

    # Handle new --repo-url requests.
    if opt.repo_url:
      remote = rp.GetRemote('origin')
      remote.url = opt.repo_url
      remote.Save()

    # Handle new --repo-rev requests.
    if opt.repo_rev:
      wrapper = Wrapper()
      remote_ref, rev = wrapper.check_repo_rev(
          rp.gitdir, opt.repo_rev, repo_verify=opt.repo_verify, quiet=opt.quiet)
      branch = rp.GetBranch('default')
      branch.merge = remote_ref
      rp.work_git.reset('--hard', rev)
      branch.Save()

    if opt.worktree:
      # Older versions of git supported worktree, but had dangerous gc bugs.
      git_require((2, 15, 0), fail=True, msg='git gc worktree corruption')

    self._SyncManifest(opt)
    self._LinkManifest(opt.manifest_name)

    if self.manifest.manifestProject.config.GetBoolean('repo.superproject'):
      self._CloneSuperproject(opt)

    if os.isatty(0) and os.isatty(1) and not self.manifest.IsMirror:
      if opt.config_name or self._ShouldConfigureUser(opt):
        self._ConfigureUser(opt)
      self._ConfigureColor()

    self._DisplayResult(opt)
