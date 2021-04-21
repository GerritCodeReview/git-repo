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

import functools
import http.cookiejar as cookielib
import io
import json
import multiprocessing
import netrc
from optparse import SUPPRESS_HELP
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client

try:
  import threading as _threading
except ImportError:
  import dummy_threading as _threading

try:
  import resource

  def _rlimit_nofile():
    return resource.getrlimit(resource.RLIMIT_NOFILE)
except ImportError:
  def _rlimit_nofile():
    return (256, 256)

import event_log
from git_command import git_require
from git_config import GetUrlCookieFile
from git_refs import R_HEADS, HEAD
import git_superproject
import gitc_utils
from project import Project
from project import RemoteSpec
from command import Command, MirrorSafeCommand, WORKER_BATCH_SIZE
from error import RepoChangedException, GitError, ManifestParseError
import platform_utils
from project import SyncBuffer
from progress import Progress
from wrapper import Wrapper
from manifest_xml import GitcManifest

_ONE_DAY_S = 24 * 60 * 60


class Sync(Command, MirrorSafeCommand):
  jobs = 1
  common = True
  helpSummary = "Update working tree to the latest revision"
  helpUsage = """
%prog [<project>...]
"""
  helpDescription = """
The '%prog' command synchronizes local project directories
with the remote repositories specified in the manifest.  If a local
project does not yet exist, it will clone a new local directory from
the remote repository and set up tracking branches as specified in
the manifest.  If the local project already exists, '%prog'
will update the remote branches and rebase any new local changes
on top of the new remote changes.

'%prog' will synchronize all projects listed at the command
line.  Projects can be specified either by name, or by a relative
or absolute path to the project's local directory. If no projects
are specified, '%prog' will synchronize all projects listed in
the manifest.

The -d/--detach option can be used to switch specified projects
back to the manifest revision.  This option is especially helpful
if the project is currently on a topic branch, but the manifest
revision is temporarily needed.

The -s/--smart-sync option can be used to sync to a known good
build as specified by the manifest-server element in the current
manifest. The -t/--smart-tag option is similar and allows you to
specify a custom tag/label.

The -u/--manifest-server-username and -p/--manifest-server-password
options can be used to specify a username and password to authenticate
with the manifest server when using the -s or -t option.

If -u and -p are not specified when using the -s or -t option, '%prog'
will attempt to read authentication credentials for the manifest server
from the user's .netrc file.

'%prog' will not use authentication credentials from -u/-p or .netrc
if the manifest server specified in the manifest file already includes
credentials.

By default, all projects will be synced. The --fail-fast option can be used
to halt syncing as soon as possible when the first project fails to sync.

The --force-sync option can be used to overwrite existing git
directories if they have previously been linked to a different
object directory. WARNING: This may cause data to be lost since
refs may be removed when overwriting.

The --force-remove-dirty option can be used to remove previously used
projects with uncommitted changes. WARNING: This may cause data to be
lost since uncommitted changes may be removed with projects that no longer
exist in the manifest.

The --no-clone-bundle option disables any attempt to use
$URL/clone.bundle to bootstrap a new Git repository from a
resumeable bundle file on a content delivery network. This
may be necessary if there are problems with the local Python
HTTP client or proxy configuration, but the Git binary works.

The --fetch-submodules option enables fetching Git submodules
of a project from server.

The -c/--current-branch option can be used to only fetch objects that
are on the branch specified by a project's revision.

The --optimized-fetch option can be used to only fetch projects that
are fixed to a sha1 revision if the sha1 revision does not already
exist locally.

The --prune option can be used to remove any refs that no longer
exist on the remote.

# SSH Connections

If at least one project remote URL uses an SSH connection (ssh://,
git+ssh://, or user@host:path syntax) repo will automatically
enable the SSH ControlMaster option when connecting to that host.
This feature permits other projects in the same '%prog' session to
reuse the same SSH tunnel, saving connection setup overheads.

To disable this behavior on UNIX platforms, set the GIT_SSH
environment variable to 'ssh'.  For example:

  export GIT_SSH=ssh
  %prog

# Compatibility

This feature is automatically disabled on Windows, due to the lack
of UNIX domain socket support.

This feature is not compatible with url.insteadof rewrites in the
user's ~/.gitconfig.  '%prog' is currently not able to perform the
rewrite early enough to establish the ControlMaster tunnel.

If the remote SSH daemon is Gerrit Code Review, version 2.0.10 or
later is required to fix a server side protocol bug.

"""
  PARALLEL_JOBS = 1

  def _CommonOptions(self, p):
    try:
      self.PARALLEL_JOBS = self.manifest.default.sync_j
    except ManifestParseError:
      pass
    super()._CommonOptions(p)

  def _Options(self, p, show_smart=True):
    p.add_option('--jobs-network', default=None, type=int, metavar='JOBS',
                 help='number of network jobs to run in parallel (defaults to --jobs)')
    p.add_option('--jobs-checkout', default=None, type=int, metavar='JOBS',
                 help='number of local checkout jobs to run in parallel (defaults to --jobs)')

    p.add_option('-f', '--force-broken',
                 dest='force_broken', action='store_true',
                 help='obsolete option (to be deleted in the future)')
    p.add_option('--fail-fast',
                 dest='fail_fast', action='store_true',
                 help='stop syncing after first error is hit')
    p.add_option('--force-sync',
                 dest='force_sync', action='store_true',
                 help="overwrite an existing git directory if it needs to "
                      "point to a different object directory. WARNING: this "
                      "may cause loss of data")
    p.add_option('--force-remove-dirty',
                 dest='force_remove_dirty', action='store_true',
                 help="force remove projects with uncommitted modifications if "
                      "projects no longer exist in the manifest. "
                      "WARNING: this may cause loss of data")
    p.add_option('-l', '--local-only',
                 dest='local_only', action='store_true',
                 help="only update working tree, don't fetch")
    p.add_option('--no-manifest-update', '--nmu',
                 dest='mp_update', action='store_false', default='true',
                 help='use the existing manifest checkout as-is. '
                      '(do not update to the latest revision)')
    p.add_option('-n', '--network-only',
                 dest='network_only', action='store_true',
                 help="fetch only, don't update working tree")
    p.add_option('-d', '--detach',
                 dest='detach_head', action='store_true',
                 help='detach projects back to manifest revision')
    p.add_option('-c', '--current-branch',
                 dest='current_branch_only', action='store_true',
                 help='fetch only current branch from server')
    p.add_option('-m', '--manifest-name',
                 dest='manifest_name',
                 help='temporary manifest to use for this sync', metavar='NAME.xml')
    p.add_option('--clone-bundle', action='store_true',
                 help='enable use of /clone.bundle on HTTP/HTTPS')
    p.add_option('--no-clone-bundle', dest='clone_bundle', action='store_false',
                 help='disable use of /clone.bundle on HTTP/HTTPS')
    p.add_option('-u', '--manifest-server-username', action='store',
                 dest='manifest_server_username',
                 help='username to authenticate with the manifest server')
    p.add_option('-p', '--manifest-server-password', action='store',
                 dest='manifest_server_password',
                 help='password to authenticate with the manifest server')
    p.add_option('--fetch-submodules',
                 dest='fetch_submodules', action='store_true',
                 help='fetch submodules from server')
    p.add_option('--use-superproject', action='store_true',
                 help='use the manifest superproject to sync projects')
    p.add_option('--no-tags',
                 dest='tags', default=True, action='store_false',
                 help="don't fetch tags")
    p.add_option('--optimized-fetch',
                 dest='optimized_fetch', action='store_true',
                 help='only fetch projects fixed to sha1 if revision does not exist locally')
    p.add_option('--retry-fetches',
                 default=0, action='store', type='int',
                 help='number of times to retry fetches on transient errors')
    p.add_option('--prune', dest='prune', action='store_true',
                 help='delete refs that no longer exist on the remote')
    if show_smart:
      p.add_option('-s', '--smart-sync',
                   dest='smart_sync', action='store_true',
                   help='smart sync using manifest from the latest known good build')
      p.add_option('-t', '--smart-tag',
                   dest='smart_tag', action='store',
                   help='smart sync using manifest from a known tag')

    g = p.add_option_group('repo Version options')
    g.add_option('--no-repo-verify',
                 dest='repo_verify', default=True, action='store_false',
                 help='do not verify repo source code')
    g.add_option('--repo-upgraded',
                 dest='repo_upgraded', action='store_true',
                 help=SUPPRESS_HELP)

  def _GetBranch(self):
    """Returns the branch name for getting the approved manifest."""
    p = self.manifest.manifestProject
    b = p.GetBranch(p.CurrentBranch)
    branch = b.merge
    if branch.startswith(R_HEADS):
      branch = branch[len(R_HEADS):]
    return branch

  def _UseSuperproject(self, opt):
    """Returns True if use-superproject option is enabled"""
    return (opt.use_superproject or
            self.manifest.manifestProject.config.GetBoolean(
                'repo.superproject'))

  def _GetCurrentBranchOnly(self, opt):
    """Returns True if current-branch or use-superproject options are enabled."""
    return opt.current_branch_only or self._UseSuperproject(opt)

  def _UpdateProjectsRevisionId(self, opt, args):
    """Update revisionId of every project with the SHA from superproject.

    This function updates each project's revisionId with SHA from superproject.
    It writes the updated manifest into a file and reloads the manifest from it.

    Args:
      opt: Program options returned from optparse.  See _Options().
      args: Arguments to pass to GetProjects. See the GetProjects
          docstring for details.

    Returns:
      Returns path to the overriding manifest file.
    """
    superproject = git_superproject.Superproject(self.manifest,
                                                 self.repodir,
                                                 quiet=opt.quiet)
    all_projects = self.GetProjects(args,
                                    missing_ok=True,
                                    submodules_ok=opt.fetch_submodules)
    manifest_path = superproject.UpdateProjectsRevisionId(all_projects)
    if not manifest_path:
      print('error: Update of revsionId from superproject has failed',
            file=sys.stderr)
      sys.exit(1)
    self._ReloadManifest(manifest_path)
    return manifest_path

  def _FetchProjectList(self, opt, projects):
    """Main function of the fetch worker.

    The projects we're given share the same underlying git object store, so we
    have to fetch them in serial.

    Delegates most of the work to _FetchHelper.

    Args:
      opt: Program options returned from optparse.  See _Options().
      projects: Projects to fetch.
    """
    return [self._FetchOne(opt, x) for x in projects]

  def _FetchOne(self, opt, project):
    """Fetch git objects for a single project.

    Args:
      opt: Program options returned from optparse.  See _Options().
      project: Project object for the project to fetch.

    Returns:
      Whether the fetch was successful.
    """
    start = time.time()
    success = False
    buf = io.StringIO()
    try:
      success = project.Sync_NetworkHalf(
          quiet=opt.quiet,
          verbose=opt.verbose,
          output_redir=buf,
          current_branch_only=self._GetCurrentBranchOnly(opt),
          force_sync=opt.force_sync,
          clone_bundle=opt.clone_bundle,
          tags=opt.tags, archive=self.manifest.IsArchive,
          optimized_fetch=opt.optimized_fetch,
          retry_fetches=opt.retry_fetches,
          prune=opt.prune,
          clone_filter=self.manifest.CloneFilter,
          partial_clone_exclude=self.manifest.PartialCloneExclude)

      output = buf.getvalue()
      if opt.verbose and output:
        print('\n' + output.rstrip())

      if not success:
        print('error: Cannot fetch %s from %s'
              % (project.name, project.remote.url),
              file=sys.stderr)
    except GitError as e:
      print('error.GitError: Cannot fetch %s' % str(e), file=sys.stderr)
    except Exception as e:
      print('error: Cannot fetch %s (%s: %s)'
            % (project.name, type(e).__name__, str(e)), file=sys.stderr)
      raise

    finish = time.time()
    return (success, project, start, finish)

  def _Fetch(self, projects, opt, err_event):
    ret = True

    jobs = opt.jobs_network if opt.jobs_network else self.jobs
    fetched = set()
    pm = Progress('Fetching', len(projects), delay=False, quiet=opt.quiet)

    objdir_project_map = dict()
    for project in projects:
      objdir_project_map.setdefault(project.objdir, []).append(project)
    projects_list = list(objdir_project_map.values())

    def _ProcessResults(results_sets):
      ret = True
      for results in results_sets:
        for (success, project, start, finish) in results:
          self._fetch_times.Set(project, finish - start)
          self.event_log.AddSync(project, event_log.TASK_SYNC_NETWORK,
                                 start, finish, success)
          # Check for any errors before running any more tasks.
          # ...we'll let existing jobs finish, though.
          if not success:
            ret = False
          else:
            fetched.add(project.gitdir)
          pm.update(msg=project.name)
        if not ret and opt.fail_fast:
          break
      return ret

    # NB: Multiprocessing is heavy, so don't spin it up for one job.
    if len(projects_list) == 1 or jobs == 1:
      if not _ProcessResults(self._FetchProjectList(opt, x) for x in projects_list):
        ret = False
    else:
      # Favor throughput over responsiveness when quiet.  It seems that imap()
      # will yield results in batches relative to chunksize, so even as the
      # children finish a sync, we won't see the result until one child finishes
      # ~chunksize jobs.  When using a large --jobs with large chunksize, this
      # can be jarring as there will be a large initial delay where repo looks
      # like it isn't doing anything and sits at 0%, but then suddenly completes
      # a lot of jobs all at once.  Since this code is more network bound, we
      # can accept a bit more CPU overhead with a smaller chunksize so that the
      # user sees more immediate & continuous feedback.
      if opt.quiet:
        chunksize = WORKER_BATCH_SIZE
      else:
        pm.update(inc=0, msg='warming up')
        chunksize = 4
      with multiprocessing.Pool(jobs) as pool:
        results = pool.imap_unordered(
            functools.partial(self._FetchProjectList, opt),
            projects_list,
            chunksize=chunksize)
        if not _ProcessResults(results):
          ret = False
          pool.close()

    pm.end()
    self._fetch_times.Save()

    if not self.manifest.IsArchive:
      self._GCProjects(projects, opt, err_event)

    return (ret, fetched)

  def _CheckoutOne(self, detach_head, force_sync, project):
    """Checkout work tree for one project

    Args:
      detach_head: Whether to leave a detached HEAD.
      force_sync: Force checking out of the repo.
      project: Project object for the project to checkout.

    Returns:
      Whether the fetch was successful.
    """
    start = time.time()
    syncbuf = SyncBuffer(self.manifest.manifestProject.config,
                         detach_head=detach_head)
    success = False
    try:
      project.Sync_LocalHalf(syncbuf, force_sync=force_sync)
      success = syncbuf.Finish()
    except GitError as e:
      print('error.GitError: Cannot checkout %s: %s' %
            (project.name, str(e)), file=sys.stderr)
    except Exception as e:
      print('error: Cannot checkout %s: %s: %s' %
            (project.name, type(e).__name__, str(e)),
            file=sys.stderr)
      raise

    if not success:
      print('error: Cannot checkout %s' % (project.name), file=sys.stderr)
    finish = time.time()
    return (success, project, start, finish)

  def _Checkout(self, all_projects, opt, err_results):
    """Checkout projects listed in all_projects

    Args:
      all_projects: List of all projects that should be checked out.
      opt: Program options returned from optparse.  See _Options().
      err_results: A list of strings, paths to git repos where checkout failed.
    """
    # Only checkout projects with worktrees.
    all_projects = [x for x in all_projects if x.worktree]

    def _ProcessResults(pool, pm, results):
      ret = True
      for (success, project, start, finish) in results:
        self.event_log.AddSync(project, event_log.TASK_SYNC_LOCAL,
                               start, finish, success)
        # Check for any errors before running any more tasks.
        # ...we'll let existing jobs finish, though.
        if not success:
          ret = False
          err_results.append(project.relpath)
          if opt.fail_fast:
            if pool:
              pool.close()
            return ret
        pm.update(msg=project.name)
      return ret

    return self.ExecuteInParallel(
        opt.jobs_checkout if opt.jobs_checkout else self.jobs,
        functools.partial(self._CheckoutOne, opt.detach_head, opt.force_sync),
        all_projects,
        callback=_ProcessResults,
        output=Progress('Checking out', len(all_projects), quiet=opt.quiet)) and not err_results

  def _GCProjects(self, projects, opt, err_event):
    pm = Progress('Garbage collecting', len(projects), delay=False, quiet=opt.quiet)
    pm.update(inc=0, msg='prescan')

    gc_gitdirs = {}
    for project in projects:
      # Make sure pruning never kicks in with shared projects.
      if (not project.use_git_worktrees and
              len(project.manifest.GetProjectsWithName(project.name)) > 1):
        if not opt.quiet:
          print('\r%s: Shared project %s found, disabling pruning.' %
                (project.relpath, project.name))
        if git_require((2, 7, 0)):
          project.EnableRepositoryExtension('preciousObjects')
        else:
          # This isn't perfect, but it's the best we can do with old git.
          print('\r%s: WARNING: shared projects are unreliable when using old '
                'versions of git; please upgrade to git-2.7.0+.'
                % (project.relpath,),
                file=sys.stderr)
          project.config.SetString('gc.pruneExpire', 'never')
      gc_gitdirs[project.gitdir] = project.bare_git

    pm.update(inc=len(projects) - len(gc_gitdirs), msg='warming up')

    cpu_count = os.cpu_count()
    jobs = min(self.jobs, cpu_count)

    if jobs < 2:
      for bare_git in gc_gitdirs.values():
        pm.update(msg=bare_git._project.name)
        bare_git.gc('--auto')
      pm.end()
      return

    config = {'pack.threads': cpu_count // jobs if cpu_count > jobs else 1}

    threads = set()
    sem = _threading.Semaphore(jobs)

    def GC(bare_git):
      pm.start(bare_git._project.name)
      try:
        try:
          bare_git.gc('--auto', config=config)
        except GitError:
          err_event.set()
        except Exception:
          err_event.set()
          raise
      finally:
        pm.finish(bare_git._project.name)
        sem.release()

    for bare_git in gc_gitdirs.values():
      if err_event.is_set() and opt.fail_fast:
        break
      sem.acquire()
      t = _threading.Thread(target=GC, args=(bare_git,))
      t.daemon = True
      threads.add(t)
      t.start()

    for t in threads:
      t.join()
    pm.end()

  def _ReloadManifest(self, manifest_name=None):
    if manifest_name:
      # Override calls _Unload already
      self.manifest.Override(manifest_name)
    else:
      self.manifest._Unload()

  def UpdateProjectList(self, opt):
    new_project_paths = []
    for project in self.GetProjects(None, missing_ok=True):
      if project.relpath:
        new_project_paths.append(project.relpath)
    file_name = 'project.list'
    file_path = os.path.join(self.repodir, file_name)
    old_project_paths = []

    if os.path.exists(file_path):
      with open(file_path, 'r') as fd:
        old_project_paths = fd.read().split('\n')
      # In reversed order, so subfolders are deleted before parent folder.
      for path in sorted(old_project_paths, reverse=True):
        if not path:
          continue
        if path not in new_project_paths:
          # If the path has already been deleted, we don't need to do it
          gitdir = os.path.join(self.manifest.topdir, path, '.git')
          if os.path.exists(gitdir):
            project = Project(
                manifest=self.manifest,
                name=path,
                remote=RemoteSpec('origin'),
                gitdir=gitdir,
                objdir=gitdir,
                use_git_worktrees=os.path.isfile(gitdir),
                worktree=os.path.join(self.manifest.topdir, path),
                relpath=path,
                revisionExpr='HEAD',
                revisionId=None,
                groups=None)
            if not project.DeleteWorktree(
                    quiet=opt.quiet,
                    force=opt.force_remove_dirty):
              return 1

    new_project_paths.sort()
    with open(file_path, 'w') as fd:
      fd.write('\n'.join(new_project_paths))
      fd.write('\n')
    return 0

  def _SmartSyncSetup(self, opt, smart_sync_manifest_path):
    if not self.manifest.manifest_server:
      print('error: cannot smart sync: no manifest server defined in '
            'manifest', file=sys.stderr)
      sys.exit(1)

    manifest_server = self.manifest.manifest_server
    if not opt.quiet:
      print('Using manifest server %s' % manifest_server)

    if '@' not in manifest_server:
      username = None
      password = None
      if opt.manifest_server_username and opt.manifest_server_password:
        username = opt.manifest_server_username
        password = opt.manifest_server_password
      else:
        try:
          info = netrc.netrc()
        except IOError:
          # .netrc file does not exist or could not be opened
          pass
        else:
          try:
            parse_result = urllib.parse.urlparse(manifest_server)
            if parse_result.hostname:
              auth = info.authenticators(parse_result.hostname)
              if auth:
                username, _account, password = auth
              else:
                print('No credentials found for %s in .netrc'
                      % parse_result.hostname, file=sys.stderr)
          except netrc.NetrcParseError as e:
            print('Error parsing .netrc file: %s' % e, file=sys.stderr)

      if (username and password):
        manifest_server = manifest_server.replace('://', '://%s:%s@' %
                                                  (username, password),
                                                  1)

    transport = PersistentTransport(manifest_server)
    if manifest_server.startswith('persistent-'):
      manifest_server = manifest_server[len('persistent-'):]

    try:
      server = xmlrpc.client.Server(manifest_server, transport=transport)
      if opt.smart_sync:
        branch = self._GetBranch()

        if 'SYNC_TARGET' in os.environ:
          target = os.environ['SYNC_TARGET']
          [success, manifest_str] = server.GetApprovedManifest(branch, target)
        elif ('TARGET_PRODUCT' in os.environ and
              'TARGET_BUILD_VARIANT' in os.environ):
          target = '%s-%s' % (os.environ['TARGET_PRODUCT'],
                              os.environ['TARGET_BUILD_VARIANT'])
          [success, manifest_str] = server.GetApprovedManifest(branch, target)
        else:
          [success, manifest_str] = server.GetApprovedManifest(branch)
      else:
        assert(opt.smart_tag)
        [success, manifest_str] = server.GetManifest(opt.smart_tag)

      if success:
        manifest_name = os.path.basename(smart_sync_manifest_path)
        try:
          with open(smart_sync_manifest_path, 'w') as f:
            f.write(manifest_str)
        except IOError as e:
          print('error: cannot write manifest to %s:\n%s'
                % (smart_sync_manifest_path, e),
                file=sys.stderr)
          sys.exit(1)
        self._ReloadManifest(manifest_name)
      else:
        print('error: manifest server RPC call failed: %s' %
              manifest_str, file=sys.stderr)
        sys.exit(1)
    except (socket.error, IOError, xmlrpc.client.Fault) as e:
      print('error: cannot connect to manifest server %s:\n%s'
            % (self.manifest.manifest_server, e), file=sys.stderr)
      sys.exit(1)
    except xmlrpc.client.ProtocolError as e:
      print('error: cannot connect to manifest server %s:\n%d %s'
            % (self.manifest.manifest_server, e.errcode, e.errmsg),
            file=sys.stderr)
      sys.exit(1)

    return manifest_name

  def _UpdateManifestProject(self, opt, mp, manifest_name):
    """Fetch & update the local manifest project."""
    if not opt.local_only:
      start = time.time()
      success = mp.Sync_NetworkHalf(quiet=opt.quiet, verbose=opt.verbose,
                                    current_branch_only=self._GetCurrentBranchOnly(opt),
                                    force_sync=opt.force_sync,
                                    tags=opt.tags,
                                    optimized_fetch=opt.optimized_fetch,
                                    retry_fetches=opt.retry_fetches,
                                    submodules=self.manifest.HasSubmodules,
                                    clone_filter=self.manifest.CloneFilter,
                                    partial_clone_exclude=self.manifest.PartialCloneExclude)
      finish = time.time()
      self.event_log.AddSync(mp, event_log.TASK_SYNC_NETWORK,
                             start, finish, success)

    if mp.HasChanges:
      syncbuf = SyncBuffer(mp.config)
      start = time.time()
      mp.Sync_LocalHalf(syncbuf, submodules=self.manifest.HasSubmodules)
      clean = syncbuf.Finish()
      self.event_log.AddSync(mp, event_log.TASK_SYNC_LOCAL,
                             start, time.time(), clean)
      if not clean:
        sys.exit(1)
      self._ReloadManifest(opt.manifest_name)
      if opt.jobs is None:
        self.jobs = self.manifest.default.sync_j

  def ValidateOptions(self, opt, args):
    if opt.force_broken:
      print('warning: -f/--force-broken is now the default behavior, and the '
            'options are deprecated', file=sys.stderr)
    if opt.network_only and opt.detach_head:
      self.OptionParser.error('cannot combine -n and -d')
    if opt.network_only and opt.local_only:
      self.OptionParser.error('cannot combine -n and -l')
    if opt.manifest_name and opt.smart_sync:
      self.OptionParser.error('cannot combine -m and -s')
    if opt.manifest_name and opt.smart_tag:
      self.OptionParser.error('cannot combine -m and -t')
    if opt.manifest_server_username or opt.manifest_server_password:
      if not (opt.smart_sync or opt.smart_tag):
        self.OptionParser.error('-u and -p may only be combined with -s or -t')
      if None in [opt.manifest_server_username, opt.manifest_server_password]:
        self.OptionParser.error('both -u and -p must be given')

  def Execute(self, opt, args):
    if opt.jobs:
      self.jobs = opt.jobs
    if self.jobs > 1:
      soft_limit, _ = _rlimit_nofile()
      self.jobs = min(self.jobs, (soft_limit - 5) // 3)

    if opt.manifest_name:
      self.manifest.Override(opt.manifest_name)

    manifest_name = opt.manifest_name
    smart_sync_manifest_path = os.path.join(
        self.manifest.manifestProject.worktree, 'smart_sync_override.xml')

    if opt.clone_bundle is None:
      opt.clone_bundle = self.manifest.CloneBundle

    if opt.smart_sync or opt.smart_tag:
      manifest_name = self._SmartSyncSetup(opt, smart_sync_manifest_path)
    else:
      if os.path.isfile(smart_sync_manifest_path):
        try:
          platform_utils.remove(smart_sync_manifest_path)
        except OSError as e:
          print('error: failed to remove existing smart sync override manifest: %s' %
                e, file=sys.stderr)

    err_event = _threading.Event()

    rp = self.manifest.repoProject
    rp.PreSync()
    cb = rp.CurrentBranch
    if cb:
      base = rp.GetBranch(cb).merge
      if not base or not base.startswith('refs/heads/'):
        print('warning: repo is not tracking a remote branch, so it will not '
              'receive updates; run `repo init --repo-rev=stable` to fix.',
              file=sys.stderr)

    mp = self.manifest.manifestProject
    mp.PreSync()

    if opt.repo_upgraded:
      _PostRepoUpgrade(self.manifest, quiet=opt.quiet)

    if not opt.mp_update:
      print('Skipping update of local manifest project.')
    else:
      self._UpdateManifestProject(opt, mp, manifest_name)

    if self._UseSuperproject(opt):
      manifest_name = self._UpdateProjectsRevisionId(opt, args)

    if self.gitc_manifest:
      gitc_manifest_projects = self.GetProjects(args,
                                                missing_ok=True)
      gitc_projects = []
      opened_projects = []
      for project in gitc_manifest_projects:
        if project.relpath in self.gitc_manifest.paths and \
           self.gitc_manifest.paths[project.relpath].old_revision:
          opened_projects.append(project.relpath)
        else:
          gitc_projects.append(project.relpath)

      if not args:
        gitc_projects = None

      if gitc_projects != [] and not opt.local_only:
        print('Updating GITC client: %s' % self.gitc_manifest.gitc_client_name)
        manifest = GitcManifest(self.repodir, self.gitc_manifest.gitc_client_name)
        if manifest_name:
          manifest.Override(manifest_name)
        else:
          manifest.Override(self.manifest.manifestFile)
        gitc_utils.generate_gitc_manifest(self.gitc_manifest,
                                          manifest,
                                          gitc_projects)
        print('GITC client successfully synced.')

      # The opened projects need to be synced as normal, therefore we
      # generate a new args list to represent the opened projects.
      # TODO: make this more reliable -- if there's a project name/path overlap,
      # this may choose the wrong project.
      args = [os.path.relpath(self.manifest.paths[path].worktree, os.getcwd())
              for path in opened_projects]
      if not args:
        return
    all_projects = self.GetProjects(args,
                                    missing_ok=True,
                                    submodules_ok=opt.fetch_submodules)

    err_network_sync = False
    err_update_projects = False

    self._fetch_times = _FetchTimes(self.manifest)
    if not opt.local_only:
      to_fetch = []
      now = time.time()
      if _ONE_DAY_S <= (now - rp.LastFetch):
        to_fetch.append(rp)
      to_fetch.extend(all_projects)
      to_fetch.sort(key=self._fetch_times.Get, reverse=True)

      success, fetched = self._Fetch(to_fetch, opt, err_event)
      if not success:
        err_event.set()

      _PostRepoFetch(rp, opt.repo_verify)
      if opt.network_only:
        # bail out now; the rest touches the working tree
        if err_event.is_set():
          print('\nerror: Exited sync due to fetch errors.\n', file=sys.stderr)
          sys.exit(1)
        return

      # Iteratively fetch missing and/or nested unregistered submodules
      previously_missing_set = set()
      while True:
        self._ReloadManifest(manifest_name)
        all_projects = self.GetProjects(args,
                                        missing_ok=True,
                                        submodules_ok=opt.fetch_submodules)
        missing = []
        for project in all_projects:
          if project.gitdir not in fetched:
            missing.append(project)
        if not missing:
          break
        # Stop us from non-stopped fetching actually-missing repos: If set of
        # missing repos has not been changed from last fetch, we break.
        missing_set = set(p.name for p in missing)
        if previously_missing_set == missing_set:
          break
        previously_missing_set = missing_set
        success, new_fetched = self._Fetch(to_fetch, opt, err_event)
        if not success:
          err_event.set()
        fetched.update(new_fetched)

      # If we saw an error, exit with code 1 so that other scripts can check.
      if err_event.is_set():
        err_network_sync = True
        if opt.fail_fast:
          print('\nerror: Exited sync due to fetch errors.\n'
                'Local checkouts *not* updated. Resolve network issues & '
                'retry.\n'
                '`repo sync -l` will update some local checkouts.',
                file=sys.stderr)
          sys.exit(1)

    if self.manifest.IsMirror or self.manifest.IsArchive:
      # bail out now, we have no working tree
      return

    if self.UpdateProjectList(opt):
      err_event.set()
      err_update_projects = True
      if opt.fail_fast:
        print('\nerror: Local checkouts *not* updated.', file=sys.stderr)
        sys.exit(1)

    err_results = []
    # NB: We don't exit here because this is the last step.
    err_checkout = not self._Checkout(all_projects, opt, err_results)
    if err_checkout:
      err_event.set()

    # If there's a notice that's supposed to print at the end of the sync, print
    # it now...
    if self.manifest.notice:
      print(self.manifest.notice)

    # If we saw an error, exit with code 1 so that other scripts can check.
    if err_event.is_set():
      print('\nerror: Unable to fully sync the tree.', file=sys.stderr)
      if err_network_sync:
        print('error: Downloading network changes failed.', file=sys.stderr)
      if err_update_projects:
        print('error: Updating local project lists failed.', file=sys.stderr)
      if err_checkout:
        print('error: Checking out local projects failed.', file=sys.stderr)
        if err_results:
          print('Failing repos:\n%s' % '\n'.join(err_results), file=sys.stderr)
      print('Try re-running with "-j1 --fail-fast" to exit at the first error.',
            file=sys.stderr)
      sys.exit(1)

    if not opt.quiet:
      print('repo sync has finished successfully.')


def _PostRepoUpgrade(manifest, quiet=False):
  wrapper = Wrapper()
  if wrapper.NeedSetupGnuPG():
    wrapper.SetupGnuPG(quiet)
  for project in manifest.projects:
    if project.Exists:
      project.PostRepoUpgrade()


def _PostRepoFetch(rp, repo_verify=True, verbose=False):
  if rp.HasChanges:
    print('info: A new version of repo is available', file=sys.stderr)
    wrapper = Wrapper()
    try:
      rev = rp.bare_git.describe(rp.GetRevisionId())
    except GitError:
      rev = None
    _, new_rev = wrapper.check_repo_rev(rp.gitdir, rev, repo_verify=repo_verify)
    # See if we're held back due to missing signed tag.
    current_revid = rp.bare_git.rev_parse('HEAD')
    new_revid = rp.bare_git.rev_parse('--verify', new_rev)
    if current_revid != new_revid:
      # We want to switch to the new rev, but also not trash any uncommitted
      # changes.  This helps with local testing/hacking.
      # If a local change has been made, we will throw that away.
      # We also have to make sure this will switch to an older commit if that's
      # the latest tag in order to support release rollback.
      try:
        rp.work_git.reset('--keep', new_rev)
      except GitError as e:
        sys.exit(str(e))
      print('info: Restarting repo with latest version', file=sys.stderr)
      raise RepoChangedException(['--repo-upgraded'])
    else:
      print('warning: Skipped upgrade to unverified version', file=sys.stderr)
  else:
    if verbose:
      print('repo version %s is current' % rp.work_git.describe(HEAD),
            file=sys.stderr)


class _FetchTimes(object):
  _ALPHA = 0.5

  def __init__(self, manifest):
    self._path = os.path.join(manifest.repodir, '.repo_fetchtimes.json')
    self._times = None
    self._seen = set()

  def Get(self, project):
    self._Load()
    return self._times.get(project.name, _ONE_DAY_S)

  def Set(self, project, t):
    self._Load()
    name = project.name
    old = self._times.get(name, t)
    self._seen.add(name)
    a = self._ALPHA
    self._times[name] = (a * t) + ((1 - a) * old)

  def _Load(self):
    if self._times is None:
      try:
        with open(self._path) as f:
          self._times = json.load(f)
      except (IOError, ValueError):
        try:
          platform_utils.remove(self._path)
        except OSError:
          pass
        self._times = {}

  def Save(self):
    if self._times is None:
      return

    to_delete = []
    for name in self._times:
      if name not in self._seen:
        to_delete.append(name)
    for name in to_delete:
      del self._times[name]

    try:
      with open(self._path, 'w') as f:
        json.dump(self._times, f, indent=2)
    except (IOError, TypeError):
      try:
        platform_utils.remove(self._path)
      except OSError:
        pass

# This is a replacement for xmlrpc.client.Transport using urllib2
# and supporting persistent-http[s]. It cannot change hosts from
# request to request like the normal transport, the real url
# is passed during initialization.


class PersistentTransport(xmlrpc.client.Transport):
  def __init__(self, orig_host):
    self.orig_host = orig_host

  def request(self, host, handler, request_body, verbose=False):
    with GetUrlCookieFile(self.orig_host, not verbose) as (cookiefile, proxy):
      # Python doesn't understand cookies with the #HttpOnly_ prefix
      # Since we're only using them for HTTP, copy the file temporarily,
      # stripping those prefixes away.
      if cookiefile:
        tmpcookiefile = tempfile.NamedTemporaryFile(mode='w')
        tmpcookiefile.write("# HTTP Cookie File")
        try:
          with open(cookiefile) as f:
            for line in f:
              if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
              tmpcookiefile.write(line)
          tmpcookiefile.flush()

          cookiejar = cookielib.MozillaCookieJar(tmpcookiefile.name)
          try:
            cookiejar.load()
          except cookielib.LoadError:
            cookiejar = cookielib.CookieJar()
        finally:
          tmpcookiefile.close()
      else:
        cookiejar = cookielib.CookieJar()

      proxyhandler = urllib.request.ProxyHandler
      if proxy:
        proxyhandler = urllib.request.ProxyHandler({
            "http": proxy,
            "https": proxy})

      opener = urllib.request.build_opener(
          urllib.request.HTTPCookieProcessor(cookiejar),
          proxyhandler)

      url = urllib.parse.urljoin(self.orig_host, handler)
      parse_results = urllib.parse.urlparse(url)

      scheme = parse_results.scheme
      if scheme == 'persistent-http':
        scheme = 'http'
      if scheme == 'persistent-https':
        # If we're proxying through persistent-https, use http. The
        # proxy itself will do the https.
        if proxy:
          scheme = 'http'
        else:
          scheme = 'https'

      # Parse out any authentication information using the base class
      host, extra_headers, _ = self.get_host_info(parse_results.netloc)

      url = urllib.parse.urlunparse((
          scheme,
          host,
          parse_results.path,
          parse_results.params,
          parse_results.query,
          parse_results.fragment))

      request = urllib.request.Request(url, request_body)
      if extra_headers is not None:
        for (name, header) in extra_headers:
          request.add_header(name, header)
      request.add_header('Content-Type', 'text/xml')
      try:
        response = opener.open(request)
      except urllib.error.HTTPError as e:
        if e.code == 501:
          # We may have been redirected through a login process
          # but our POST turned into a GET. Retry.
          response = opener.open(request)
        else:
          raise

      p, u = xmlrpc.client.getparser()
      while 1:
        data = response.read(1024)
        if not data:
          break
        p.feed(data)
      p.close()
      return u.close()

  def close(self):
    pass
