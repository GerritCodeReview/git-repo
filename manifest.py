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
import xml.dom.minidom

from git_config import GitConfig, IsId
from project import Project, MetaProject, R_HEADS, HEAD
from remote import Remote
from error import ManifestParseError

MANIFEST_FILE_NAME = 'manifest.xml'
LOCAL_MANIFEST_NAME = 'local_manifest.xml'

class _Default(object):
  """Project defaults within the manifest."""

  revision = None
  remote = None


class Manifest(object):
  """manages the repo configuration file"""

  def __init__(self, repodir):
    self.repodir = os.path.abspath(repodir)
    self.topdir = os.path.dirname(self.repodir)
    self.manifestFile = os.path.join(self.repodir, MANIFEST_FILE_NAME)
    self.globalConfig = GitConfig.ForUser()

    self.repoProject = MetaProject(self, 'repo',
      gitdir   = os.path.join(repodir, 'repo/.git'),
      worktree = os.path.join(repodir, 'repo'))

    self.manifestProject = MetaProject(self, 'manifests',
      gitdir   = os.path.join(repodir, 'manifests.git'),
      worktree = os.path.join(repodir, 'manifests'))

    self._Unload()

  def Link(self, name):
    """Update the repo metadata to use a different manifest.
    """
    path = os.path.join(self.manifestProject.worktree, name)
    if not os.path.isfile(path):
      raise ManifestParseError('manifest %s not found' % name)

    old = self.manifestFile
    try:
      self.manifestFile = path
      self._Unload()
      self._Load()
    finally:
      self.manifestFile = old

    try:
      if os.path.exists(self.manifestFile):
        os.remove(self.manifestFile)
      os.symlink('manifests/%s' % name, self.manifestFile)
    except OSError, e:
      raise ManifestParseError('cannot link manifest %s' % name)

  def _RemoteToXml(self, r, doc, root):
    e = doc.createElement('remote')
    root.appendChild(e)
    e.setAttribute('name', r.name)
    e.setAttribute('fetch', r.fetchUrl)
    if r.reviewUrl is not None:
      e.setAttribute('review', r.reviewUrl)
    if r.projectName is not None:
      e.setAttribute('project-name', r.projectName)

  def Save(self, fd, peg_rev=False):
    """Write the current manifest out to the given file descriptor.
    """
    doc = xml.dom.minidom.Document()
    root = doc.createElement('manifest')
    doc.appendChild(root)

    d = self.default
    sort_remotes = list(self.remotes.keys())
    sort_remotes.sort()

    for r in sort_remotes:
      self._RemoteToXml(self.remotes[r], doc, root)
    if self.remotes:
      root.appendChild(doc.createTextNode(''))

    have_default = False
    e = doc.createElement('default')
    if d.remote:
      have_default = True
      e.setAttribute('remote', d.remote.name)
    if d.revision:
      have_default = True
      e.setAttribute('revision', d.revision)
    if have_default:
      root.appendChild(e)
      root.appendChild(doc.createTextNode(''))

    sort_projects = list(self.projects.keys())
    sort_projects.sort()

    for p in sort_projects:
      p = self.projects[p]
      e = doc.createElement('project')
      root.appendChild(e)
      e.setAttribute('name', p.name)
      if p.relpath != p.name:
        e.setAttribute('path', p.relpath)
      if not d.remote or p.remote.name != d.remote.name:
        e.setAttribute('remote', p.remote.name)
      if peg_rev:
        if self.IsMirror:
          e.setAttribute('revision',
                         p.bare_git.rev_parse(p.revision + '^0'))
        else:
          e.setAttribute('revision',
                         p.work_git.rev_parse(HEAD + '^0'))
      elif not d.revision or p.revision != d.revision:
        e.setAttribute('revision', p.revision)

      for r in p.extraRemotes:
        self._RemoteToXml(p.extraRemotes[r], doc, e)
      for c in p.copyfiles:
        ce = doc.createElement('copyfile')
        ce.setAttribute('src', c.src)
        ce.setAttribute('dest', c.dest)
        e.appendChild(ce)

    doc.writexml(fd, '', '  ', '\n', 'UTF-8')

  @property
  def projects(self):
    self._Load()
    return self._projects

  @property
  def remotes(self):
    self._Load()
    return self._remotes

  @property
  def default(self):
    self._Load()
    return self._default

  @property
  def IsMirror(self):
    return self.manifestProject.config.GetBoolean('repo.mirror')

  def _Unload(self):
    self._loaded = False
    self._projects = {}
    self._remotes = {}
    self._default = None
    self.branch = None

  def _Load(self):
    if not self._loaded:
      m = self.manifestProject
      b = m.GetBranch(m.CurrentBranch).merge
      if b.startswith(R_HEADS):
        b = b[len(R_HEADS):]
      self.branch = b

      self._ParseManifest(True)

      local = os.path.join(self.repodir, LOCAL_MANIFEST_NAME)
      if os.path.exists(local):
        try:
          real = self.manifestFile
          self.manifestFile = local
          self._ParseManifest(False)
        finally:
          self.manifestFile = real

      if self.IsMirror:
        self._AddMetaProjectMirror(self.repoProject)
        self._AddMetaProjectMirror(self.manifestProject)

      self._loaded = True

  def _ParseManifest(self, is_root_file):
    root = xml.dom.minidom.parse(self.manifestFile)
    if not root or not root.childNodes:
      raise ManifestParseError, \
            "no root node in %s" % \
            self.manifestFile

    config = root.childNodes[0]
    if config.nodeName != 'manifest':
      raise ManifestParseError, \
            "no <manifest> in %s" % \
            self.manifestFile

    for node in config.childNodes:
      if node.nodeName == 'remove-project':
        name = self._reqatt(node, 'name')
        try:
          del self._projects[name]
        except KeyError:
          raise ManifestParseError, \
                'project %s not found' % \
                (name)

    for node in config.childNodes:
      if node.nodeName == 'remote':
        remote = self._ParseRemote(node)
        if self._remotes.get(remote.name):
          raise ManifestParseError, \
                'duplicate remote %s in %s' % \
                (remote.name, self.manifestFile)
        self._remotes[remote.name] = remote

    for node in config.childNodes:
      if node.nodeName == 'default':
        if self._default is not None:
          raise ManifestParseError, \
                'duplicate default in %s' % \
                (self.manifestFile)
        self._default = self._ParseDefault(node)
    if self._default is None:
      self._default = _Default()

    for node in config.childNodes:
      if node.nodeName == 'project':
        project = self._ParseProject(node)
        if self._projects.get(project.name):
          raise ManifestParseError, \
                'duplicate project %s in %s' % \
                (project.name, self.manifestFile)
        self._projects[project.name] = project

    for node in config.childNodes:
      if node.nodeName == 'add-remote':
        pn = self._reqatt(node, 'to-project')
        project = self._projects.get(pn)
        if not project:
          raise ManifestParseError, \
                'project %s not defined in %s' % \
                (pn, self.manifestFile)
        self._ParseProjectExtraRemote(project, node)

  def _AddMetaProjectMirror(self, m):
    name = None
    m_url = m.GetRemote(m.remote.name).url
    if m_url.endswith('/.git'):
      raise ManifestParseError, 'refusing to mirror %s' % m_url

    if self._default and self._default.remote:
      url = self._default.remote.fetchUrl
      if not url.endswith('/'):
        url += '/'
      if m_url.startswith(url):
        remote = self._default.remote
        name = m_url[len(url):]

    if name is None:
      s = m_url.rindex('/') + 1
      remote = Remote('origin', fetch = m_url[:s])
      name = m_url[s:]

    if name.endswith('.git'):
      name = name[:-4]

    if name not in self._projects:
      m.PreSync()
      gitdir = os.path.join(self.topdir, '%s.git' % name)
      project = Project(manifest = self,
                        name = name,
                        remote = remote,
                        gitdir = gitdir,
                        worktree = None,
                        relpath = None,
                        revision = m.revision)
      self._projects[project.name] = project

  def _ParseRemote(self, node):
    """
    reads a <remote> element from the manifest file
    """
    name = self._reqatt(node, 'name')
    fetch = self._reqatt(node, 'fetch')
    review = node.getAttribute('review')
    if review == '':
      review = None

    projectName = node.getAttribute('project-name')
    if projectName == '':
      projectName = None

    r = Remote(name=name,
               fetch=fetch,
               review=review,
               projectName=projectName)

    for n in node.childNodes:
      if n.nodeName == 'require':
        r.requiredCommits.append(self._reqatt(n, 'commit'))

    return r

  def _ParseDefault(self, node):
    """
    reads a <default> element from the manifest file
    """
    d = _Default()
    d.remote = self._get_remote(node)
    d.revision = node.getAttribute('revision')
    if d.revision == '':
      d.revision = None
    return d

  def _ParseProject(self, node):
    """
    reads a <project> element from the manifest file
    """ 
    name = self._reqatt(node, 'name')

    remote = self._get_remote(node)
    if remote is None:
      remote = self._default.remote
    if remote is None:
      raise ManifestParseError, \
            "no remote for project %s within %s" % \
            (name, self.manifestFile)

    revision = node.getAttribute('revision')
    if not revision:
      revision = self._default.revision
    if not revision:
      raise ManifestParseError, \
            "no revision for project %s within %s" % \
            (name, self.manifestFile)

    path = node.getAttribute('path')
    if not path:
      path = name
    if path.startswith('/'):
      raise ManifestParseError, \
            "project %s path cannot be absolute in %s" % \
            (name, self.manifestFile)

    if self.IsMirror:
      relpath = None
      worktree = None
      gitdir = os.path.join(self.topdir, '%s.git' % name)
    else:
      worktree = os.path.join(self.topdir, path)
      gitdir = os.path.join(self.repodir, 'projects/%s.git' % path)

    project = Project(manifest = self,
                      name = name,
                      remote = remote,
                      gitdir = gitdir,
                      worktree = worktree,
                      relpath = path,
                      revision = revision)

    for n in node.childNodes:
      if n.nodeName == 'remote':
        self._ParseProjectExtraRemote(project, n)
      elif n.nodeName == 'copyfile':
        self._ParseCopyFile(project, n)

    return project

  def _ParseProjectExtraRemote(self, project, n):
    r = self._ParseRemote(n)
    if project.extraRemotes.get(r.name) \
       or project.remote.name == r.name:
      raise ManifestParseError, \
            'duplicate remote %s in project %s in %s' % \
            (r.name, project.name, self.manifestFile)
    project.extraRemotes[r.name] = r

  def _ParseCopyFile(self, project, node):
    src = self._reqatt(node, 'src')
    dest = self._reqatt(node, 'dest')
    if not self.IsMirror:
      # src is project relative;
      # dest is relative to the top of the tree
      project.AddCopyFile(src, dest, os.path.join(self.topdir, dest))

  def _get_remote(self, node):
    name = node.getAttribute('remote')
    if not name:
      return None

    v = self._remotes.get(name)
    if not v:
      raise ManifestParseError, \
            "remote %s not defined in %s" % \
            (name, self.manifestFile)
    return v

  def _reqatt(self, node, attname):
    """
    reads a required attribute from the node.
    """
    v = node.getAttribute(attname)
    if not v:
      raise ManifestParseError, \
            "no %s in <%s> within %s" % \
            (attname, node.nodeName, self.manifestFile)
    return v
