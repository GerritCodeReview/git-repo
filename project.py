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
import filecmp
import os
import re
import shutil
import stat
import sys
import urllib2

from color import Coloring
from git_command import GitCommand
from git_config import GitConfig, IsId
from error import GitError, ImportError, UploadError
from error import ManifestInvalidRevisionError
from remote import Remote

HEAD    = 'HEAD'
R_HEADS = 'refs/heads/'
R_TAGS  = 'refs/tags/'
R_PUB   = 'refs/published/'
R_M     = 'refs/remotes/m/'

def _error(fmt, *args):
  msg = fmt % args
  print >>sys.stderr, 'error: %s' % msg

def not_rev(r):
  return '^' + r

def sq(r):
  return "'" + r.replace("'", "'\''") + "'"

hook_list = None
def repo_hooks():
  global hook_list
  if hook_list is None:
    d = os.path.abspath(os.path.dirname(__file__))
    d = os.path.join(d , 'hooks')
    hook_list = map(lambda x: os.path.join(d, x), os.listdir(d))
  return hook_list

def relpath(dst, src):
  src = os.path.dirname(src)
  top = os.path.commonprefix([dst, src])
  if top.endswith('/'):
    top = top[:-1]
  else:
    top = os.path.dirname(top)

  tmp = src
  rel = ''
  while top != tmp:
    rel += '../'
    tmp = os.path.dirname(tmp)
  return rel + dst[len(top) + 1:]


class DownloadedChange(object):
  _commit_cache = None

  def __init__(self, project, base, change_id, ps_id, commit):
    self.project = project
    self.base = base
    self.change_id = change_id
    self.ps_id = ps_id
    self.commit = commit

  @property
  def commits(self):
    if self._commit_cache is None:
      self._commit_cache = self.project.bare_git.rev_list(
        '--abbrev=8',
        '--abbrev-commit',
        '--pretty=oneline',
        '--reverse',
        '--date-order',
        not_rev(self.base),
        self.commit,
        '--')
    return self._commit_cache


class ReviewableBranch(object):
  _commit_cache = None

  def __init__(self, project, branch, base):
    self.project = project
    self.branch = branch
    self.base = base
    self.replace_changes = None

  @property
  def name(self):
    return self.branch.name

  @property
  def commits(self):
    if self._commit_cache is None:
      self._commit_cache = self.project.bare_git.rev_list(
        '--abbrev=8',
        '--abbrev-commit',
        '--pretty=oneline',
        '--reverse',
        '--date-order',
        not_rev(self.base),
        R_HEADS + self.name,
        '--')
    return self._commit_cache

  @property
  def unabbrev_commits(self):
    r = dict()
    for commit in self.project.bare_git.rev_list(
        not_rev(self.base),
        R_HEADS + self.name,
        '--'):
      r[commit[0:8]] = commit
    return r

  @property
  def date(self):
    return self.project.bare_git.log(
      '--pretty=format:%cd',
      '-n', '1',
      R_HEADS + self.name,
      '--')

  def UploadForReview(self, people):
    self.project.UploadForReview(self.name,
                                 self.replace_changes,
                                 people)

  @property
  def tip_url(self):
    me = self.project.GetBranch(self.name)
    commit = self.project.bare_git.rev_parse(R_HEADS + self.name)
    return 'http://%s/r/%s' % (me.remote.review, commit[0:12])

  @property
  def owner_email(self):
    return self.project.UserEmail


class StatusColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'status')
    self.project   = self.printer('header',    attr = 'bold')
    self.branch    = self.printer('header',    attr = 'bold')
    self.nobranch  = self.printer('nobranch',  fg = 'red')

    self.added     = self.printer('added',     fg = 'green')
    self.changed   = self.printer('changed',   fg = 'red')
    self.untracked = self.printer('untracked', fg = 'red')


class DiffColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'diff')
    self.project   = self.printer('header',    attr = 'bold')


class _CopyFile:
  def __init__(self, src, dest, abssrc, absdest):
    self.src = src
    self.dest = dest
    self.abs_src = abssrc
    self.abs_dest = absdest

  def _Copy(self):
    src = self.abs_src
    dest = self.abs_dest
    # copy file if it does not exist or is out of date
    if not os.path.exists(dest) or not filecmp.cmp(src, dest):
      try:
        # remove existing file first, since it might be read-only
        if os.path.exists(dest):
          os.remove(dest)
        shutil.copy(src, dest)
        # make the file read-only
        mode = os.stat(dest)[stat.ST_MODE]
        mode = mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        os.chmod(dest, mode)
      except IOError:
        _error('Cannot copy file %s to %s', src, dest)


class Project(object):
  def __init__(self,
               manifest,
               name,
               remote,
               gitdir,
               worktree,
               relpath,
               revision):
    self.manifest = manifest
    self.name = name
    self.remote = remote
    self.gitdir = gitdir
    self.worktree = worktree
    self.relpath = relpath
    self.revision = revision
    self.snapshots = {}
    self.extraRemotes = {}
    self.copyfiles = []
    self.config = GitConfig.ForRepository(
                    gitdir = self.gitdir,
                    defaults =  self.manifest.globalConfig)

    if self.worktree:
      self.work_git = self._GitGetByExec(self, bare=False)
    else:
      self.work_git = None
    self.bare_git = self._GitGetByExec(self, bare=True)

  @property
  def Exists(self):
    return os.path.isdir(self.gitdir)

  @property
  def CurrentBranch(self):
    """Obtain the name of the currently checked out branch.
       The branch name omits the 'refs/heads/' prefix.
       None is returned if the project is on a detached HEAD.
    """
    try:
      b = self.work_git.GetHead()
    except GitError:
      return None
    if b.startswith(R_HEADS):
      return b[len(R_HEADS):]
    return None

  def IsDirty(self, consider_untracked=True):
    """Is the working directory modified in some way?
    """
    self.work_git.update_index('-q',
                               '--unmerged',
                               '--ignore-missing',
                               '--refresh')
    if self.work_git.DiffZ('diff-index','-M','--cached',HEAD):
      return True
    if self.work_git.DiffZ('diff-files'):
      return True
    if consider_untracked and self.work_git.LsOthers():
      return True
    return False

  _userident_name = None
  _userident_email = None

  @property
  def UserName(self):
    """Obtain the user's personal name.
    """
    if self._userident_name is None:
      self._LoadUserIdentity()
    return self._userident_name

  @property
  def UserEmail(self):
    """Obtain the user's email address.  This is very likely
       to be their Gerrit login.
    """
    if self._userident_email is None:
      self._LoadUserIdentity()
    return self._userident_email

  def _LoadUserIdentity(self):
      u = self.bare_git.var('GIT_COMMITTER_IDENT')
      m = re.compile("^(.*) <([^>]*)> ").match(u)
      if m:
        self._userident_name = m.group(1)
        self._userident_email = m.group(2)
      else:
        self._userident_name = ''
        self._userident_email = ''

  def GetRemote(self, name):
    """Get the configuration for a single remote.
    """
    return self.config.GetRemote(name)

  def GetBranch(self, name):
    """Get the configuration for a single branch.
    """
    return self.config.GetBranch(name)

  def GetBranches(self):
    """Get all existing local branches.
    """
    current = self.CurrentBranch
    all = self.bare_git.ListRefs()
    heads = {}
    pubd = {}

    for name, id in all.iteritems():
      if name.startswith(R_HEADS):
        name = name[len(R_HEADS):]
        b = self.GetBranch(name)
        b.current = name == current
        b.published = None
        b.revision = id
        heads[name] = b

    for name, id in all.iteritems():
      if name.startswith(R_PUB):
        name = name[len(R_PUB):]
        b = heads.get(name)
        if b:
          b.published = id

    return heads


## Status Display ##

  def PrintWorkTreeStatus(self):
    """Prints the status of the repository to stdout.
    """
    if not os.path.isdir(self.worktree):
      print ''
      print 'project %s/' % self.relpath
      print '  missing (run "repo sync")'
      return

    self.work_git.update_index('-q',
                               '--unmerged',
                               '--ignore-missing',
                               '--refresh')
    di = self.work_git.DiffZ('diff-index', '-M', '--cached', HEAD)
    df = self.work_git.DiffZ('diff-files')
    do = self.work_git.LsOthers()
    if not di and not df and not do:
      return 'CLEAN'

    out = StatusColoring(self.config)
    out.project('project %-40s', self.relpath + '/')

    branch = self.CurrentBranch
    if branch is None:
      out.nobranch('(*** NO BRANCH ***)')
    else:
      out.branch('branch %s', branch)
    out.nl()

    paths = list()
    paths.extend(di.keys())
    paths.extend(df.keys())
    paths.extend(do)

    paths = list(set(paths))
    paths.sort()

    for p in paths:
      try: i = di[p]
      except KeyError: i = None

      try: f = df[p]
      except KeyError: f = None
 
      if i: i_status = i.status.upper()
      else: i_status = '-'

      if f: f_status = f.status.lower()
      else: f_status = '-'

      if i and i.src_path:
        line = ' %s%s\t%s => %s (%s%%)' % (i_status, f_status,
                                        i.src_path, p, i.level)
      else:
        line = ' %s%s\t%s' % (i_status, f_status, p)

      if i and not f:
        out.added('%s', line)
      elif (i and f) or (not i and f):
        out.changed('%s', line)
      elif not i and not f:
        out.untracked('%s', line)
      else:
        out.write('%s', line)
      out.nl()
    return 'DIRTY'

  def PrintWorkTreeDiff(self):
    """Prints the status of the repository to stdout.
    """
    out = DiffColoring(self.config)
    cmd = ['diff']
    if out.is_on:
      cmd.append('--color')
    cmd.append(HEAD)
    cmd.append('--')
    p = GitCommand(self,
                   cmd,
                   capture_stdout = True,
                   capture_stderr = True)
    has_diff = False
    for line in p.process.stdout:
      if not has_diff:
        out.nl()
        out.project('project %s/' % self.relpath)
        out.nl()
        has_diff = True
      print line[:-1]
    p.Wait()


## Publish / Upload ##

  def WasPublished(self, branch):
    """Was the branch published (uploaded) for code review?
       If so, returns the SHA-1 hash of the last published
       state for the branch.
    """
    try:
      return self.bare_git.rev_parse(R_PUB + branch)
    except GitError:
      return None

  def CleanPublishedCache(self):
    """Prunes any stale published refs.
    """
    heads = set()
    canrm = {}
    for name, id in self._allrefs.iteritems():
      if name.startswith(R_HEADS):
        heads.add(name)
      elif name.startswith(R_PUB):
        canrm[name] = id

    for name, id in canrm.iteritems():
      n = name[len(R_PUB):]
      if R_HEADS + n not in heads:
        self.bare_git.DeleteRef(name, id)

  def GetUploadableBranches(self):
    """List any branches which can be uploaded for review.
    """
    heads = {}
    pubed = {}

    for name, id in self._allrefs.iteritems():
      if name.startswith(R_HEADS):
        heads[name[len(R_HEADS):]] = id
      elif name.startswith(R_PUB):
        pubed[name[len(R_PUB):]] = id

    ready = []
    for branch, id in heads.iteritems():
      if branch in pubed and pubed[branch] == id:
        continue

      rb = self.GetUploadableBranch(branch)
      if rb:
        ready.append(rb)
    return ready

  def GetUploadableBranch(self, branch_name):
    """Get a single uploadable branch, or None.
    """
    branch = self.GetBranch(branch_name)
    base = branch.LocalMerge
    if branch.LocalMerge:
      rb = ReviewableBranch(self, branch, base)
      if rb.commits:
        return rb
    return None

  def UploadForReview(self, branch=None, replace_changes=None, people=([],[])):
    """Uploads the named branch for code review.
    """
    if branch is None:
      branch = self.CurrentBranch
    if branch is None:
      raise GitError('not currently on a branch')

    branch = self.GetBranch(branch)
    if not branch.LocalMerge:
      raise GitError('branch %s does not track a remote' % branch.name)
    if not branch.remote.review:
      raise GitError('remote %s has no review url' % branch.remote.name)

    dest_branch = branch.merge
    if not dest_branch.startswith(R_HEADS):
      dest_branch = R_HEADS + dest_branch

    if not branch.remote.projectname:
      branch.remote.projectname = self.name
      branch.remote.Save()

    if branch.remote.ReviewProtocol == 'ssh':
      if dest_branch.startswith(R_HEADS):
        dest_branch = dest_branch[len(R_HEADS):]

      rp = ['gerrit receive-pack']
      for e in people[0]:
        rp.append('--reviewer=%s' % sq(e))
      for e in people[1]:
        rp.append('--cc=%s' % sq(e))

      cmd = ['push']
      cmd.append('--receive-pack=%s' % " ".join(rp))
      cmd.append(branch.remote.SshReviewUrl(self.UserEmail))
      cmd.append('%s:refs/for/%s' % (R_HEADS + branch.name, dest_branch))
      if replace_changes:
        for change_id,commit_id in replace_changes.iteritems():
          cmd.append('%s:refs/changes/%s/new' % (commit_id, change_id))
      if GitCommand(self, cmd, bare = True).Wait() != 0:
        raise UploadError('Upload failed')

    else:
        raise UploadError('Unsupported protocol %s' \
          % branch.remote.review)

    msg = "posted to %s for %s" % (branch.remote.review, dest_branch)
    self.bare_git.UpdateRef(R_PUB + branch.name,
                            R_HEADS + branch.name,
                            message = msg)


## Sync ##

  def Sync_NetworkHalf(self):
    """Perform only the network IO portion of the sync process.
       Local working directory/branch state is not affected.
    """
    if not self.Exists:
      print >>sys.stderr
      print >>sys.stderr, 'Initializing project %s ...' % self.name
      self._InitGitDir()

    self._InitRemote()
    for r in self.extraRemotes.values():
      if not self._RemoteFetch(r.name):
        return False
    if not self._RemoteFetch():
      return False

    if self.worktree:
      self._InitMRef()
    else:
      self._InitMirrorHead()
      try:
        os.remove(os.path.join(self.gitdir, 'FETCH_HEAD'))
      except OSError:
        pass
    return True

  def PostRepoUpgrade(self):
    self._InitHooks()

  def _CopyFiles(self):
    for file in self.copyfiles:
      file._Copy()

  def Sync_LocalHalf(self, syncbuf):
    """Perform only the local IO portion of the sync process.
       Network access is not required.
    """
    self._InitWorkTree()
    self.CleanPublishedCache()

    rem = self.GetRemote(self.remote.name)
    rev = rem.ToLocal(self.revision)
    try:
      self.bare_git.rev_parse('--verify', '%s^0' % rev)
    except GitError:
      raise ManifestInvalidRevisionError(
        'revision %s in %s not found' % (self.revision, self.name))

    branch = self.CurrentBranch

    if branch is None or syncbuf.detach_head:
      # Currently on a detached HEAD.  The user is assumed to
      # not have any local modifications worth worrying about.
      #
      if os.path.exists(os.path.join(self.worktree, '.dotest')) \
      or os.path.exists(os.path.join(self.worktree, '.git', 'rebase-apply')):
        syncbuf.fail(self, _PriorSyncFailedError())
        return

      lost = self._revlist(not_rev(rev), HEAD)
      if lost:
        syncbuf.info(self, "discarding %d commits", len(lost))
      try:
        self._Checkout(rev, quiet=True)
      except GitError, e:
        syncbuf.fail(self, e)
        return
      self._CopyFiles()
      return

    branch = self.GetBranch(branch)
    merge = branch.LocalMerge

    if not merge:
      # The current branch has no tracking configuration.
      # Jump off it to a deatched HEAD.
      #
      syncbuf.info(self,
                   "leaving %s; does not track upstream",
                   branch.name)
      try:
        self._Checkout(rev, quiet=True)
      except GitError, e:
        syncbuf.fail(self, e)
        return
      self._CopyFiles()
      return

    upstream_gain = self._revlist(not_rev(HEAD), rev)
    pub = self.WasPublished(branch.name)
    if pub:
      not_merged = self._revlist(not_rev(rev), pub)
      if not_merged:
        if upstream_gain:
          # The user has published this branch and some of those
          # commits are not yet merged upstream.  We do not want
          # to rewrite the published commits so we punt.
          #
          syncbuf.info(self,
                       "branch %s is published but is now %d commits behind",
                       branch.name,
                       len(upstream_gain))
          syncbuf.info(self, "consider merging or rebasing the unpublished commits")
        return
      elif upstream_gain:
        # We can fast-forward safely.
        #
        def _doff():
          self._FastForward(rev)
          self._CopyFiles()
        syncbuf.later1(self, _doff)
        return
      else:
        # Trivially no changes in the upstream.
        #
        return

    if merge == rev:
      try:
        old_merge = self.bare_git.rev_parse('%s@{1}' % merge)
      except GitError:
        old_merge = merge
      if old_merge == '0000000000000000000000000000000000000000' \
         or old_merge == '':
        old_merge = merge
    else:
      # The upstream switched on us.  Time to cross our fingers
      # and pray that the old upstream also wasn't in the habit
      # of rebasing itself.
      #
      syncbuf.info(self, "manifest switched %s...%s", merge, rev)
      old_merge = merge

    if rev == old_merge:
      upstream_lost = []
    else:
      upstream_lost = self._revlist(not_rev(rev), old_merge)

    if not upstream_lost and not upstream_gain:
      # Trivially no changes caused by the upstream.
      #
      return

    if self.IsDirty(consider_untracked=False):
      syncbuf.fail(self, _DirtyError())
      return

    if upstream_lost:
      # Upstream rebased.  Not everything in HEAD
      # may have been caused by the user.
      #
      syncbuf.info(self,
                   "discarding %d commits removed from upstream",
                   len(upstream_lost))

    branch.remote = rem
    branch.merge = self.revision
    branch.Save()

    my_changes = self._revlist(not_rev(old_merge), HEAD)
    if my_changes:
      def _dorebase():
        self._Rebase(upstream = old_merge, onto = rev)
        self._CopyFiles()
      syncbuf.later2(self, _dorebase)
    elif upstream_lost:
      try:
        self._ResetHard(rev)
        self._CopyFiles()
      except GitError, e:
        syncbuf.fail(self, e)
        return
    else:
      def _doff():
        self._FastForward(rev)
        self._CopyFiles()
      syncbuf.later1(self, _doff)

  def AddCopyFile(self, src, dest, absdest):
    # dest should already be an absolute path, but src is project relative
    # make src an absolute path
    abssrc = os.path.join(self.worktree, src)
    self.copyfiles.append(_CopyFile(src, dest, abssrc, absdest))

  def DownloadPatchSet(self, change_id, patch_id):
    """Download a single patch set of a single change to FETCH_HEAD.
    """
    remote = self.GetRemote(self.remote.name)

    cmd = ['fetch', remote.name]
    cmd.append('refs/changes/%2.2d/%d/%d' \
               % (change_id % 100, change_id, patch_id))
    cmd.extend(map(lambda x: str(x), remote.fetch))
    if GitCommand(self, cmd, bare=True).Wait() != 0:
      return None
    return DownloadedChange(self,
                            remote.ToLocal(self.revision),
                            change_id,
                            patch_id,
                            self.bare_git.rev_parse('FETCH_HEAD'))


## Branch Management ##

  def StartBranch(self, name):
    """Create a new branch off the manifest's revision.
    """
    try:
      self.bare_git.rev_parse(R_HEADS + name)
      exists = True
    except GitError:
      exists = False;

    if exists:
      if name == self.CurrentBranch:
        return True
      else:
        cmd = ['checkout', name, '--']
        return GitCommand(self, cmd).Wait() == 0

    else:
      branch = self.GetBranch(name)
      branch.remote = self.GetRemote(self.remote.name)
      branch.merge = self.revision

      rev = branch.LocalMerge
      cmd = ['checkout', '-b', branch.name, rev]
      if GitCommand(self, cmd).Wait() == 0:
        branch.Save()
        return True
      else:
        return False

  def CheckoutBranch(self, name):
    """Checkout a local topic branch.
    """

    # Be sure the branch exists
    try:
      tip_rev = self.bare_git.rev_parse(R_HEADS + name)
    except GitError:
      return False;

    # Do the checkout
    cmd = ['checkout', name, '--']
    return GitCommand(self, cmd).Wait() == 0

  def AbandonBranch(self, name):
    """Destroy a local topic branch.
    """
    try:
      tip_rev = self.bare_git.rev_parse(R_HEADS + name)
    except GitError:
      return

    if self.CurrentBranch == name:
      self._Checkout(
        self.GetRemote(self.remote.name).ToLocal(self.revision),
        quiet=True)

    cmd = ['branch', '-D', name]
    GitCommand(self, cmd, capture_stdout=True).Wait()

  def PruneHeads(self):
    """Prune any topic branches already merged into upstream.
    """
    cb = self.CurrentBranch
    kill = []
    left = self._allrefs
    for name in left.keys():
      if name.startswith(R_HEADS):
        name = name[len(R_HEADS):]
        if cb is None or name != cb:
          kill.append(name)

    rev = self.GetRemote(self.remote.name).ToLocal(self.revision)
    if cb is not None \
       and not self._revlist(HEAD + '...' + rev) \
       and not self.IsDirty(consider_untracked = False):
      self.work_git.DetachHead(HEAD)
      kill.append(cb)

    if kill:
      try:
        old = self.bare_git.GetHead()
      except GitError:
        old = 'refs/heads/please_never_use_this_as_a_branch_name'

      try:
        self.bare_git.DetachHead(rev)

        b = ['branch', '-d']
        b.extend(kill)
        b = GitCommand(self, b, bare=True,
                       capture_stdout=True,
                       capture_stderr=True)
        b.Wait()
      finally:
        self.bare_git.SetHead(old)
        left = self._allrefs

      for branch in kill:
        if (R_HEADS + branch) not in left:
          self.CleanPublishedCache()
          break

    if cb and cb not in kill:
      kill.append(cb)
    kill.sort()

    kept = []
    for branch in kill:
      if (R_HEADS + branch) in left:
        branch = self.GetBranch(branch)
        base = branch.LocalMerge
        if not base:
          base = rev
        kept.append(ReviewableBranch(self, branch, base))
    return kept


## Direct Git Commands ##

  def _RemoteFetch(self, name=None):
    if not name:
      name = self.remote.name
    cmd = ['fetch']
    if not self.worktree:
      cmd.append('--update-head-ok')
    cmd.append(name)
    return GitCommand(self, cmd, bare = True).Wait() == 0

  def _Checkout(self, rev, quiet=False):
    cmd = ['checkout']
    if quiet:
      cmd.append('-q')
    cmd.append(rev)
    cmd.append('--')
    if GitCommand(self, cmd).Wait() != 0:
      if self._allrefs:
        raise GitError('%s checkout %s ' % (self.name, rev))

  def _ResetHard(self, rev, quiet=True):
    cmd = ['reset', '--hard']
    if quiet:
      cmd.append('-q')
    cmd.append(rev)
    if GitCommand(self, cmd).Wait() != 0:
      raise GitError('%s reset --hard %s ' % (self.name, rev))

  def _Rebase(self, upstream, onto = None):
    cmd = ['rebase']
    if onto is not None:
      cmd.extend(['--onto', onto])
    cmd.append(upstream)
    if GitCommand(self, cmd).Wait() != 0:
      raise GitError('%s rebase %s ' % (self.name, upstream))

  def _FastForward(self, head):
    cmd = ['merge', head]
    if GitCommand(self, cmd).Wait() != 0:
      raise GitError('%s merge %s ' % (self.name, head))

  def _InitGitDir(self):
    if not os.path.exists(self.gitdir):
      os.makedirs(self.gitdir)
      self.bare_git.init()

      if self.manifest.IsMirror:
        self.config.SetString('core.bare', 'true')
      else:
        self.config.SetString('core.bare', None)

      hooks = self._gitdir_path('hooks')
      try:
        to_rm = os.listdir(hooks)
      except OSError:
        to_rm = []
      for old_hook in to_rm:
        os.remove(os.path.join(hooks, old_hook))
      self._InitHooks()

      m = self.manifest.manifestProject.config
      for key in ['user.name', 'user.email']:
        if m.Has(key, include_defaults = False):
          self.config.SetString(key, m.GetString(key))

  def _InitHooks(self):
    hooks = self._gitdir_path('hooks')
    if not os.path.exists(hooks):
      os.makedirs(hooks)
    for stock_hook in repo_hooks():
      dst = os.path.join(hooks, os.path.basename(stock_hook))
      try:
        os.symlink(relpath(stock_hook, dst), dst)
      except OSError, e:
        if e.errno == errno.EEXIST:
          pass
        elif e.errno == errno.EPERM:
          raise GitError('filesystem must support symlinks')
        else:
          raise

  def _InitRemote(self):
    if self.remote.fetchUrl:
      remote = self.GetRemote(self.remote.name)

      url = self.remote.fetchUrl
      while url.endswith('/'):
        url = url[:-1]
      url += '/%s.git' % self.name
      remote.url = url
      remote.review = self.remote.reviewUrl
      if remote.projectname is None:
        remote.projectname = self.name

      if self.worktree:
        remote.ResetFetch(mirror=False)
      else:
        remote.ResetFetch(mirror=True)
      remote.Save()

    for r in self.extraRemotes.values():
      remote = self.GetRemote(r.name)
      remote.url = r.fetchUrl
      remote.review = r.reviewUrl
      if r.projectName:
        remote.projectname = r.projectName
      elif remote.projectname is None:
        remote.projectname = self.name
      remote.ResetFetch()
      remote.Save()

  def _InitMRef(self):
    if self.manifest.branch:
      msg = 'manifest set to %s' % self.revision
      ref = R_M + self.manifest.branch

      if IsId(self.revision):
        dst = self.revision + '^0'
        self.bare_git.UpdateRef(ref, dst, message = msg, detach = True)
      else:
        remote = self.GetRemote(self.remote.name)
        dst = remote.ToLocal(self.revision)
        self.bare_git.symbolic_ref('-m', msg, ref, dst)

  def _InitMirrorHead(self):
    dst = self.GetRemote(self.remote.name).ToLocal(self.revision)
    msg = 'manifest set to %s' % self.revision
    self.bare_git.SetHead(dst, message=msg)

  def _InitWorkTree(self):
    dotgit = os.path.join(self.worktree, '.git')
    if not os.path.exists(dotgit):
      os.makedirs(dotgit)

      for name in ['config',
                   'description',
                   'hooks',
                   'info',
                   'logs',
                   'objects',
                   'packed-refs',
                   'refs',
                   'rr-cache',
                   'svn']:
        try:
          src = os.path.join(self.gitdir, name)
          dst = os.path.join(dotgit, name)
          os.symlink(relpath(src, dst), dst)
        except OSError, e:
          if e.errno == errno.EPERM:
            raise GitError('filesystem must support symlinks')
          else:
            raise

      rev = self.GetRemote(self.remote.name).ToLocal(self.revision)
      rev = self.bare_git.rev_parse('%s^0' % rev)

      f = open(os.path.join(dotgit, HEAD), 'wb')
      f.write("%s\n" % rev)
      f.close()

      cmd = ['read-tree', '--reset', '-u']
      cmd.append('-v')
      cmd.append('HEAD')
      if GitCommand(self, cmd).Wait() != 0:
        raise GitError("cannot initialize work tree")

  def _gitdir_path(self, path):
    return os.path.join(self.gitdir, path)

  def _revlist(self, *args):
    cmd = []
    cmd.extend(args)
    cmd.append('--')
    return self.work_git.rev_list(*args)

  @property
  def _allrefs(self):
    return self.bare_git.ListRefs()

  class _GitGetByExec(object):
    def __init__(self, project, bare):
      self._project = project
      self._bare = bare

    def ListRefs(self, *args):
      cmdv = ['for-each-ref', '--format=%(objectname) %(refname)']
      cmdv.extend(args)
      p = GitCommand(self._project,
                     cmdv,
                     bare = self._bare,
                     capture_stdout = True,
                     capture_stderr = True)
      r = {}
      for line in p.process.stdout:
        id, name = line[:-1].split(' ', 2)
        r[name] = id
      if p.Wait() != 0:
        raise GitError('%s for-each-ref %s: %s' % (
                       self._project.name,
                       str(args),
                       p.stderr))
      return r

    def LsOthers(self):
      p = GitCommand(self._project,
                     ['ls-files',
                      '-z',
                      '--others',
                      '--exclude-standard'],
                     bare = False,
                     capture_stdout = True,
                     capture_stderr = True)
      if p.Wait() == 0:
        out = p.stdout
        if out:
          return out[:-1].split("\0")
      return []

    def DiffZ(self, name, *args):
      cmd = [name]
      cmd.append('-z')
      cmd.extend(args)
      p = GitCommand(self._project,
                     cmd,
                     bare = False,
                     capture_stdout = True,
                     capture_stderr = True)
      try:
        out = p.process.stdout.read()
        r = {}
        if out:
          out = iter(out[:-1].split('\0'))
          while out:
            try:
              info = out.next()
              path = out.next()
            except StopIteration:
              break

            class _Info(object):
              def __init__(self, path, omode, nmode, oid, nid, state):
                self.path = path
                self.src_path = None
                self.old_mode = omode
                self.new_mode = nmode
                self.old_id = oid
                self.new_id = nid

                if len(state) == 1:
                  self.status = state
                  self.level = None
                else:
                  self.status = state[:1]
                  self.level = state[1:]
                  while self.level.startswith('0'):
                    self.level = self.level[1:]

            info = info[1:].split(' ')
            info =_Info(path, *info)
            if info.status in ('R', 'C'):
              info.src_path = info.path
              info.path = out.next()
            r[info.path] = info
        return r
      finally:
        p.Wait()

    def GetHead(self):
      return self.symbolic_ref(HEAD)

    def SetHead(self, ref, message=None):
      cmdv = []
      if message is not None:
        cmdv.extend(['-m', message])
      cmdv.append(HEAD)
      cmdv.append(ref)
      self.symbolic_ref(*cmdv)

    def DetachHead(self, new, message=None):
      cmdv = ['--no-deref']
      if message is not None:
        cmdv.extend(['-m', message])
      cmdv.append(HEAD)
      cmdv.append(new)
      self.update_ref(*cmdv)

    def UpdateRef(self, name, new, old=None,
                  message=None,
                  detach=False):
      cmdv = []
      if message is not None:
        cmdv.extend(['-m', message])
      if detach:
        cmdv.append('--no-deref')
      cmdv.append(name)
      cmdv.append(new)
      if old is not None:
        cmdv.append(old)
      self.update_ref(*cmdv)

    def DeleteRef(self, name, old=None):
      if not old:
        old = self.rev_parse(name)
      self.update_ref('-d', name, old)

    def rev_list(self, *args):
      cmdv = ['rev-list']
      cmdv.extend(args)
      p = GitCommand(self._project,
                     cmdv,
                     bare = self._bare,
                     capture_stdout = True,
                     capture_stderr = True)
      r = []
      for line in p.process.stdout:
        r.append(line[:-1])
      if p.Wait() != 0:
        raise GitError('%s rev-list %s: %s' % (
                       self._project.name,
                       str(args),
                       p.stderr))
      return r

    def __getattr__(self, name):
      name = name.replace('_', '-')
      def runner(*args):
        cmdv = [name]
        cmdv.extend(args)
        p = GitCommand(self._project,
                       cmdv,
                       bare = self._bare,
                       capture_stdout = True,
                       capture_stderr = True)
        if p.Wait() != 0:
          raise GitError('%s %s: %s' % (
                         self._project.name,
                         name,
                         p.stderr))
        r = p.stdout
        if r.endswith('\n') and r.index('\n') == len(r) - 1:
          return r[:-1]
        return r
      return runner


class _PriorSyncFailedError(Exception):
  def __str__(self):
    return 'prior sync failed; rebase still in progress'

class _DirtyError(Exception):
  def __str__(self):
    return 'contains uncommitted changes'

class _InfoMessage(object):
  def __init__(self, project, text):
    self.project = project
    self.text = text

  def Print(self, syncbuf):
    syncbuf.out.info('%s/: %s', self.project.relpath, self.text)
    syncbuf.out.nl()

class _Failure(object):
  def __init__(self, project, why):
    self.project = project
    self.why = why

  def Print(self, syncbuf):
    syncbuf.out.fail('error: %s/: %s',
                     self.project.relpath,
                     str(self.why))
    syncbuf.out.nl()

class _Later(object):
  def __init__(self, project, action):
    self.project = project
    self.action = action

  def Run(self, syncbuf):
    out = syncbuf.out
    out.project('project %s/', self.project.relpath)
    out.nl()
    try:
      self.action()
      out.nl()
      return True
    except GitError, e:
      out.nl()
      return False

class _SyncColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'reposync')
    self.project   = self.printer('header', attr = 'bold')
    self.info      = self.printer('info')
    self.fail      = self.printer('fail', fg='red')

class SyncBuffer(object):
  def __init__(self, config, detach_head=False):
    self._messages = []
    self._failures = []
    self._later_queue1 = []
    self._later_queue2 = []

    self.out = _SyncColoring(config)
    self.out.redirect(sys.stderr)

    self.detach_head = detach_head
    self.clean = True

  def info(self, project, fmt, *args):
    self._messages.append(_InfoMessage(project, fmt % args))

  def fail(self, project, err=None):
    self._failures.append(_Failure(project, err))
    self.clean = False

  def later1(self, project, what):
    self._later_queue1.append(_Later(project, what))

  def later2(self, project, what):
    self._later_queue2.append(_Later(project, what))

  def Finish(self):
    self._PrintMessages()
    self._RunLater()
    self._PrintMessages()
    return self.clean

  def _RunLater(self):
    for q in ['_later_queue1', '_later_queue2']:
      if not self._RunQueue(q):
        return

  def _RunQueue(self, queue):
    for m in getattr(self, queue):
      if not m.Run(self):
        self.clean = False
        return False
    setattr(self, queue, [])
    return True

  def _PrintMessages(self):
    for m in self._messages:
      m.Print(self)
    for m in self._failures:
      m.Print(self)

    self._messages = []
    self._failures = []


class MetaProject(Project):
  """A special project housed under .repo.
  """
  def __init__(self, manifest, name, gitdir, worktree):
    repodir = manifest.repodir
    Project.__init__(self,
                     manifest = manifest,
                     name = name,
                     gitdir = gitdir,
                     worktree = worktree,
                     remote = Remote('origin'),
                     relpath = '.repo/%s' % name,
                     revision = 'refs/heads/master')

  def PreSync(self):
    if self.Exists:
      cb = self.CurrentBranch
      if cb:
        base = self.GetBranch(cb).merge
        if base:
          self.revision = base

  @property
  def HasChanges(self):
    """Has the remote received new commits not yet checked out?
    """
    rev = self.GetRemote(self.remote.name).ToLocal(self.revision)
    if self._revlist(not_rev(HEAD), rev):
      return True
    return False
