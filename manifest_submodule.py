#
# Copyright (C) 2009 The Android Open Source Project
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

import sys
import os
import shutil

from error import GitError
from error import ManifestParseError
from git_command import GitCommand
from git_config import GitConfig
from git_config import IsId
from manifest import Manifest
from progress import Progress
from project import RemoteSpec
from project import Project
from project import MetaProject
from project import R_HEADS
from project import HEAD
from project import _lwrite

import manifest_xml

GITLINK = '160000'

def _rmdir(dir, top):
  while dir != top:
    try:
      os.rmdir(dir)
    except OSError:
      break
    dir = os.path.dirname(dir)

def _rmref(gitdir, ref):
  os.remove(os.path.join(gitdir, ref))
  log = os.path.join(gitdir, 'logs', ref)
  if os.path.exists(log):
    os.remove(log)
    _rmdir(os.path.dirname(log), gitdir)

def _has_gitmodules(d):
  return os.path.exists(os.path.join(d, '.gitmodules'))

class SubmoduleManifest(Manifest):
  """manifest from .gitmodules file"""

  @classmethod
  def Is(cls, repodir):
    return _has_gitmodules(os.path.dirname(repodir)) \
        or _has_gitmodules(os.path.join(repodir, 'manifest')) \
        or _has_gitmodules(os.path.join(repodir, 'manifests'))

  @classmethod
  def IsBare(cls, p):
    try:
      p.bare_git.cat_file('-e', '%s:.gitmodules' % p.GetRevisionId())
    except GitError:
      return False
    return True

  def __init__(self, repodir):
    Manifest.__init__(self, repodir)

    gitdir = os.path.join(repodir, 'manifest.git')
    config = GitConfig.ForRepository(gitdir = gitdir)

    if config.GetBoolean('repo.mirror'):
      worktree = os.path.join(repodir, 'manifest')
      relpath = None
    else:
      worktree = self.topdir
      relpath  = '.'

    self.manifestProject = MetaProject(self, '__manifest__',
      gitdir   = gitdir,
      worktree = worktree,
      relpath  = relpath)
    self._modules = GitConfig(os.path.join(worktree, '.gitmodules'),
                              pickleFile = os.path.join(
                                repodir, '.repopickle_gitmodules'
                              ))
    self._review = GitConfig(os.path.join(worktree, '.review'),
                             pickleFile = os.path.join(
                               repodir, '.repopickle_review'
                             ))
    self._Unload()

  @property
  def projects(self):
    self._Load()
    return self._projects

  @property
  def notice(self):
    return self._modules.GetString('repo.notice')

  def InitBranch(self):
    m = self.manifestProject
    if m.CurrentBranch is None:
      b = m.revisionExpr
      if b.startswith(R_HEADS):
        b = b[len(R_HEADS):]
      return m.StartBranch(b)
    return True

  def SetMRefs(self, project):
    if project.revisionId is None:
      # Special project, e.g. the manifest or repo executable.
      #
      return

    ref = 'refs/remotes/m'
    cur = project.bare_ref.get(ref)
    exp = project.revisionId
    if cur != exp:
      msg = 'manifest set to %s' % exp
      project.bare_git.UpdateRef(ref, exp, message = msg, detach = True)

    ref = 'refs/remotes/m-revision'
    cur = project.bare_ref.symref(ref)
    exp = project.revisionExpr
    if exp is None:
      if cur:
        _rmref(project.gitdir, ref)
    elif cur != exp:
      remote = project.GetRemote(project.remote.name)
      dst = remote.ToLocal(exp)
      msg = 'manifest set to %s (%s)' % (exp, dst)
      project.bare_git.symbolic_ref('-m', msg, ref, dst)

  def Upgrade_Local(self, old):
    if isinstance(old, manifest_xml.XmlManifest):
      self.FromXml_Local_1(old, checkout=True)
      self.FromXml_Local_2(old)
    else:
      raise ManifestParseError, 'cannot upgrade manifest'

  def FromXml_Local_1(self, old, checkout):
    os.rename(old.manifestProject.gitdir,
              os.path.join(old.repodir, 'manifest.git'))

    oldmp = old.manifestProject
    oldBranch = oldmp.CurrentBranch
    b = oldmp.GetBranch(oldBranch).merge
    if not b:
      raise ManifestParseError, 'cannot upgrade manifest'
    if b.startswith(R_HEADS):
      b = b[len(R_HEADS):]

    newmp = self.manifestProject
    self._CleanOldMRefs(newmp)
    if oldBranch != b:
      newmp.bare_git.branch('-m', oldBranch, b)
      newmp.config.ClearCache()

    old_remote = newmp.GetBranch(b).remote.name
    act_remote = self._GuessRemoteName(old)
    if old_remote != act_remote:
      newmp.bare_git.remote('rename', old_remote, act_remote)
      newmp.config.ClearCache()
    newmp.remote.name = act_remote
    print >>sys.stderr, "Assuming remote named '%s'" % act_remote

    if checkout:
      for p in old.projects.values():
        for c in p.copyfiles:
          if os.path.exists(c.abs_dest):
            os.remove(c.abs_dest)
      newmp._InitWorkTree()
    else:
      newmp._LinkWorkTree()

    _lwrite(os.path.join(newmp.worktree,'.git',HEAD),
            'ref: refs/heads/%s\n' % b)

  def _GuessRemoteName(self, old):
    used = {}
    for p in old.projects.values():
      n = p.remote.name
      used[n] = used.get(n, 0) + 1

    remote_name = 'origin'
    remote_used = 0
    for n in used.keys():
      if remote_used < used[n]:
        remote_used = used[n]
        remote_name = n
    return remote_name

  def FromXml_Local_2(self, old):
    shutil.rmtree(old.manifestProject.worktree)
    os.remove(old._manifestFile)

    my_remote = self._Remote().name
    new_base = os.path.join(self.repodir, 'projects')
    old_base = os.path.join(self.repodir, 'projects.old')
    os.rename(new_base, old_base)
    os.makedirs(new_base)

    info = []
    pm = Progress('Converting projects', len(self.projects))
    for p in self.projects.values():
      pm.update()

      old_p = old.projects.get(p.name)
      old_gitdir = os.path.join(old_base, '%s.git' % p.relpath)
      if not os.path.isdir(old_gitdir):
        continue

      parent = os.path.dirname(p.gitdir)
      if not os.path.isdir(parent):
        os.makedirs(parent)
      os.rename(old_gitdir, p.gitdir)
      _rmdir(os.path.dirname(old_gitdir), self.repodir)

      if not os.path.isdir(p.worktree):
        os.makedirs(p.worktree)

      if os.path.isdir(os.path.join(p.worktree, '.git')):
        p._LinkWorkTree(relink=True)

      self._CleanOldMRefs(p)
      if old_p and old_p.remote.name != my_remote:
        info.append("%s/: renamed remote '%s' to '%s'" \
                    % (p.relpath, old_p.remote.name, my_remote))
        p.bare_git.remote('rename', old_p.remote.name, my_remote)
        p.config.ClearCache()

      self.SetMRefs(p)
    pm.end()
    for i in info:
      print >>sys.stderr, i

  def _CleanOldMRefs(self, p):
    all_refs = p._allrefs
    for ref in all_refs.keys():
      if ref.startswith(manifest_xml.R_M):
        if p.bare_ref.symref(ref) != '':
          _rmref(p.gitdir, ref)
        else:
          p.bare_git.DeleteRef(ref, all_refs[ref])

  def FromXml_Definition(self, old):
    """Convert another manifest representation to this one.
    """
    mp = self.manifestProject
    gm = self._modules
    gr = self._review

    fd = open(os.path.join(mp.worktree, '.gitignore'), 'ab')
    fd.write('/.repo\n')
    fd.close()

    sort_projects = list(old.projects.keys())
    sort_projects.sort()

    b = mp.GetBranch(mp.CurrentBranch).merge
    if b.startswith(R_HEADS):
      b = b[len(R_HEADS):]

    if old.notice:
      gm.SetString('repo.notice', old.notice)

    info = []
    pm = Progress('Converting manifest', len(sort_projects))
    for p in sort_projects:
      pm.update()
      p = old.projects[p]

      gm.SetString('submodule.%s.path' % p.name, p.relpath)
      gm.SetString('submodule.%s.url' % p.name, p.remote.url)

      if gr.GetString('review.url') is None:
        gr.SetString('review.url', p.remote.review)
      elif gr.GetString('review.url') != p.remote.review:
        gr.SetString('review.%s.url' % p.name, p.remote.review)

      r = p.revisionExpr
      if r and not IsId(r):
        if r.startswith(R_HEADS):
          r = r[len(R_HEADS):]
        if r == b:
          r = '.'
        gm.SetString('submodule.%s.revision' % p.name, r)

      for c in p.copyfiles:
        info.append('Moved %s out of %s' % (c.src, p.relpath))
        c._Copy()
        p.work_git.rm(c.src)
        mp.work_git.add(c.dest)

      self.SetRevisionId(p.relpath, p.GetRevisionId())
    mp.work_git.add('.gitignore', '.gitmodules', '.review')
    pm.end()
    for i in info:
      print >>sys.stderr, i

  def _Unload(self):
    self._loaded = False
    self._projects = {}
    self._revisionIds = None
    self.branch = None

  def _Load(self):
    if not self._loaded:
      f = os.path.join(self.repodir, manifest_xml.LOCAL_MANIFEST_NAME)
      if os.path.exists(f):
        print >>sys.stderr, 'warning: ignoring %s' % f

      m = self.manifestProject
      b = m.CurrentBranch
      if not b:
        raise ManifestParseError, 'manifest cannot be on detached HEAD'
      b = m.GetBranch(b).merge
      if b.startswith(R_HEADS):
        b = b[len(R_HEADS):]
      self.branch = b
      m.remote.name = self._Remote().name

      self._ParseModules()

      if self.IsMirror:
        self._AddMetaProjectMirror(self.repoProject)
        self._AddMetaProjectMirror(self.manifestProject)

      self._loaded = True

  def _ParseModules(self):
    byPath = dict()
    for name in self._modules.GetSubSections('submodule'):
      p = self._ParseProject(name)
      if self._projects.get(p.name):
        raise ManifestParseError, 'duplicate project "%s"' % p.name
      if byPath.get(p.relpath):
        raise ManifestParseError, 'duplicate path "%s"' % p.relpath
      self._projects[p.name] = p
      byPath[p.relpath] = p

    for relpath in self._allRevisionIds.keys():
      if relpath not in byPath:
        raise ManifestParseError, \
          'project "%s" not in .gitmodules' \
          % relpath

  def _Remote(self):
    m = self.manifestProject
    b = m.GetBranch(m.CurrentBranch)
    return b.remote

  def _ResolveUrl(self, url):
    if url.startswith('./') or url.startswith('../'):
      base = self._Remote().url
      try:
        base = base[:base.rindex('/')+1]
      except ValueError:
        base = base[:base.rindex(':')+1]
      if url.startswith('./'):
        url = url[2:]
      while '/' in base and url.startswith('../'):
        base = base[:base.rindex('/')+1]
        url = url[3:]
      return base + url
    return url

  def _GetRevisionId(self, path):
    return self._allRevisionIds.get(path)

  @property
  def _allRevisionIds(self):
    if self._revisionIds is None:
      a = dict()
      p = GitCommand(self.manifestProject,
                     ['ls-files','-z','--stage'],
                     capture_stdout = True)
      for line in p.process.stdout.read().split('\0')[:-1]:
        l_info, l_path = line.split('\t', 2)
        l_mode, l_id, l_stage = l_info.split(' ', 2)
        if l_mode == GITLINK and l_stage == '0':
          a[l_path] = l_id
      p.Wait()
      self._revisionIds = a
    return self._revisionIds

  def SetRevisionId(self, path, id):
    self.manifestProject.work_git.update_index(
      '--add','--cacheinfo', GITLINK, id, path)

  def _ParseProject(self, name):
    gm = self._modules
    gr = self._review

    path = gm.GetString('submodule.%s.path' % name)
    if not path:
      path = name

    revId = self._GetRevisionId(path)
    if not revId:
      raise ManifestParseError(
        'submodule "%s" has no revision at "%s"' \
        % (name, path))

    url = gm.GetString('submodule.%s.url' % name)
    if not url:
      url = name
    url = self._ResolveUrl(url)

    review = gr.GetString('review.%s.url' % name)
    if not review:
      review = gr.GetString('review.url')
    if not review:
      review = self._Remote().review

    remote = RemoteSpec(self._Remote().name, url, review)
    revExpr = gm.GetString('submodule.%s.revision' % name)
    if revExpr == '.':
      revExpr = self.branch

    if self.IsMirror:
      relpath = None
      worktree = None
      gitdir = os.path.join(self.topdir, '%s.git' % name)
    else:
      worktree = os.path.join(self.topdir, path)
      gitdir = os.path.join(self.repodir, 'projects/%s.git' % name)

    return Project(manifest = self,
                   name = name,
                   remote = remote,
                   gitdir = gitdir,
                   worktree = worktree,
                   relpath = path,
                   revisionExpr = revExpr,
                   revisionId = revId)

  def _AddMetaProjectMirror(self, m):
    m_url = m.GetRemote(m.remote.name).url
    if m_url.endswith('/.git'):
      raise ManifestParseError, 'refusing to mirror %s' % m_url

    name = self._GuessMetaName(m_url)
    if name.endswith('.git'):
      name = name[:-4]

    if name not in self._projects:
      m.PreSync()
      gitdir = os.path.join(self.topdir, '%s.git' % name)
      project = Project(manifest = self,
                        name = name,
                        remote = RemoteSpec(self._Remote().name, m_url),
                        gitdir = gitdir,
                        worktree = None,
                        relpath = None,
                        revisionExpr = m.revisionExpr,
                        revisionId = None)
      self._projects[project.name] = project

  def _GuessMetaName(self, m_url):
    parts = m_url.split('/')
    name = parts[-1]
    parts = parts[0:-1]
    s = len(parts) - 1
    while s > 0:
      l = '/'.join(parts[0:s]) + '/'
      r = '/'.join(parts[s:]) + '/'
      for p in self._projects.values():
        if p.name.startswith(r) and p.remote.url.startswith(l):
          return r + name
      s -= 1
    return m_url[m_url.rindex('/') + 1:]
