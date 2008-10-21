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

from editor import Editor
from git_config import GitConfig, IsId
from import_tar import ImportTar
from import_zip import ImportZip
from project import Project, MetaProject, R_TAGS
from remote import Remote
from error import ManifestParseError

MANIFEST_FILE_NAME = 'manifest.xml'

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
    Editor.globalConfig = self.globalConfig

    self.repoProject = MetaProject(self, 'repo',
      gitdir   = os.path.join(repodir, 'repo/.git'),
      worktree = os.path.join(repodir, 'repo'))

    wt     = os.path.join(repodir, 'manifests')
    gd_new = os.path.join(repodir, 'manifests.git')
    gd_old = os.path.join(wt, '.git')
    if os.path.exists(gd_new) or not os.path.exists(gd_old):
      gd = gd_new
    else:
      gd = gd_old
    self.manifestProject = MetaProject(self, 'manifests',
      gitdir   = gd,
      worktree = wt)

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

  def _Unload(self):
    self._loaded = False
    self._projects = {}
    self._remotes = {}
    self._default = None
    self.branch = None

  def _Load(self):
    if not self._loaded:
      self._ParseManifest()
      self._loaded = True

  def _ParseManifest(self):
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

    self.branch = config.getAttribute('branch')
    if not self.branch:
      self.branch = 'default'

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

  def _ParseRemote(self, node):
    """
    reads a <remote> element from the manifest file
    """
    name = self._reqatt(node, 'name')
    fetch = self._reqatt(node, 'fetch')
    review = node.getAttribute('review')

    r = Remote(name=name,
               fetch=fetch,
               review=review)

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
        r = self._ParseRemote(n)
        if project.extraRemotes.get(r.name) \
           or project.remote.name == r.name:
          raise ManifestParseError, \
                'duplicate remote %s in project %s in %s' % \
                (r.name, project.name, self.manifestFile)
        project.extraRemotes[r.name] = r
      elif n.nodeName == 'copyfile':
        self._ParseCopyFile(project, n)

    to_resolve = []
    by_version = {}

    for n in node.childNodes:
      if n.nodeName == 'import':
        self._ParseImport(project, n, to_resolve, by_version)

    for pair in to_resolve:
      sn, pr = pair
      try:
        sn.SetParent(by_version[pr].commit)
      except KeyError:
        raise ManifestParseError, \
              'snapshot %s not in project %s in %s' % \
              (pr, project.name, self.manifestFile)

    return project

  def _ParseImport(self, project, import_node, to_resolve, by_version):
    first_url = None
    for node in import_node.childNodes:
      if node.nodeName == 'mirror':
        first_url = self._reqatt(node, 'url')
        break
    if not first_url:
      raise ManifestParseError, \
            'mirror url required for project %s in %s' % \
            (project.name, self.manifestFile)

    imp = None
    for cls in [ImportTar, ImportZip]:
      if cls.CanAccept(first_url):
        imp = cls()
        break
    if not imp:
      raise ManifestParseError, \
            'snapshot %s unsupported for project %s in %s' % \
            (first_url, project.name, self.manifestFile)

    imp.SetProject(project)

    for node in import_node.childNodes:
      if node.nodeName == 'remap':
        old = node.getAttribute('strip')
        new = node.getAttribute('insert')
        imp.RemapPath(old, new)

      elif node.nodeName == 'mirror':
        imp.AddUrl(self._reqatt(node, 'url'))

    for node in import_node.childNodes:
      if node.nodeName == 'snapshot':
        sn = imp.Clone()
        sn.SetVersion(self._reqatt(node, 'version'))
        sn.SetCommit(node.getAttribute('check'))

        pr = node.getAttribute('prior')
        if pr:
          if IsId(pr):
            sn.SetParent(pr)
          else:
            to_resolve.append((sn, pr))

        rev = R_TAGS + sn.TagName

        if rev in project.snapshots:
          raise ManifestParseError, \
                'duplicate snapshot %s for project %s in %s' % \
                (sn.version, project.name, self.manifestFile)
        project.snapshots[rev] = sn
        by_version[sn.version] = sn

  def _ParseCopyFile(self, project, node):
    src = self._reqatt(node, 'src')
    dest = self._reqatt(node, 'dest')
    # src is project relative, and dest is relative to the top of the tree
    project.AddCopyFile(src, os.path.join(self.topdir, dest))

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
