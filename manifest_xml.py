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
import re
import sys
import urlparse
import xml.dom.minidom

from git_config import GitConfig, IsId
from project import RemoteSpec, Project, MetaProject, R_HEADS, HEAD
from error import ManifestParseError

MANIFEST_FILE_NAME = 'manifest.xml'
LOCAL_MANIFEST_NAME = 'local_manifest.xml'

urlparse.uses_relative.extend(['ssh', 'git'])
urlparse.uses_netloc.extend(['ssh', 'git'])

class _Default(object):
  """Project defaults within the manifest."""

  revisionExpr = None
  remote = None
  sync_j = 1

class _XmlRemote(object):
  def __init__(self,
               name,
               fetch=None,
               manifestUrl=None,
               review=None):
    self.name = name
    self.fetchUrl = fetch
    self.manifestUrl = manifestUrl
    self.reviewUrl = review
    self.resolvedFetchUrl = self._resolveFetchUrl()

  def _resolveFetchUrl(self):
    url = self.fetchUrl.rstrip('/')
    manifestUrl = self.manifestUrl.rstrip('/')
    # urljoin will get confused if there is no scheme in the base url
    # ie, if manifestUrl is of the form <hostname:port>
    if manifestUrl.find(':') != manifestUrl.find('/') - 1:
        manifestUrl = 'gopher://' + manifestUrl
    url = urlparse.urljoin(manifestUrl, url)
    return re.sub(r'^gopher://', '', url)

  def ToRemoteSpec(self, projectName):
    url = self.resolvedFetchUrl.rstrip('/') + '/' + projectName
    return RemoteSpec(self.name, url, self.reviewUrl)

class XmlManifest(object):
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

  def Override(self, name):
    """Use a different manifest, just for the current instantiation.
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

  def Link(self, name):
    """Update the repo metadata to use a different manifest.
    """
    self.Override(name)

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

  def Save(self, fd, peg_rev=False):
    """Write the current manifest out to the given file descriptor.
    """
    doc = xml.dom.minidom.Document()
    root = doc.createElement('manifest')
    doc.appendChild(root)

    # Save out the notice.  There's a little bit of work here to give it the
    # right whitespace, which assumes that the notice is automatically indented
    # by 4 by minidom.
    if self.notice:
      notice_element = root.appendChild(doc.createElement('notice'))
      notice_lines = self.notice.splitlines()
      indented_notice = ('\n'.join(" "*4 + line for line in notice_lines))[4:]
      notice_element.appendChild(doc.createTextNode(indented_notice))

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
    if d.revisionExpr:
      have_default = True
      e.setAttribute('revision', d.revisionExpr)
    if d.sync_j > 1:
      have_default = True
      e.setAttribute('sync-j', '%d' % d.sync_j)
    if have_default:
      root.appendChild(e)
      root.appendChild(doc.createTextNode(''))

    if self._manifest_server:
      e = doc.createElement('manifest-server')
      e.setAttribute('url', self._manifest_server)
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
                         p.bare_git.rev_parse(p.revisionExpr + '^0'))
        else:
          e.setAttribute('revision',
                         p.work_git.rev_parse(HEAD + '^0'))
      elif not d.revisionExpr or p.revisionExpr != d.revisionExpr:
        e.setAttribute('revision', p.revisionExpr)

      for c in p.copyfiles:
        ce = doc.createElement('copyfile')
        ce.setAttribute('src', c.src)
        ce.setAttribute('dest', c.dest)
        e.appendChild(ce)

    if self._repo_hooks_project:
      root.appendChild(doc.createTextNode(''))
      e = doc.createElement('repo-hooks')
      e.setAttribute('in-project', self._repo_hooks_project.name)
      e.setAttribute('enabled-list',
                     ' '.join(self._repo_hooks_project.enabled_repo_hooks))
      root.appendChild(e)

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
  def repo_hooks_project(self):
    self._Load()
    return self._repo_hooks_project

  @property
  def notice(self):
    self._Load()
    return self._notice

  @property
  def manifest_server(self):
    self._Load()
    return self._manifest_server

  @property
  def IsMirror(self):
    return self.manifestProject.config.GetBoolean('repo.mirror')

  def _Unload(self):
    self._loaded = False
    self._projects = {}
    self._remotes = {}
    self._default = None
    self._repo_hooks_project = None
    self._notice = None
    self.branch = None
    self._manifest_server = None

  def _Load(self):
    if not self._loaded:
      m = self.manifestProject
      b = m.GetBranch(m.CurrentBranch).merge
      if b is not None and b.startswith(R_HEADS):
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
      raise ManifestParseError(
          "no root node in %s" %
          self.manifestFile)

    config = root.childNodes[0]
    if config.nodeName != 'manifest':
      raise ManifestParseError(
          "no <manifest> in %s" %
          self.manifestFile)

    for node in config.childNodes:
      if node.nodeName == 'remove-project':
        name = self._reqatt(node, 'name')
        try:
          del self._projects[name]
        except KeyError:
          raise ManifestParseError(
              'project %s not found' %
              (name))

        # If the manifest removes the hooks project, treat it as if it deleted
        # the repo-hooks element too.
        if self._repo_hooks_project and (self._repo_hooks_project.name == name):
          self._repo_hooks_project = None

    for node in config.childNodes:
      if node.nodeName == 'remote':
        remote = self._ParseRemote(node)
        if self._remotes.get(remote.name):
          raise ManifestParseError(
              'duplicate remote %s in %s' %
              (remote.name, self.manifestFile))
        self._remotes[remote.name] = remote

    for node in config.childNodes:
      if node.nodeName == 'default':
        if self._default is not None:
          raise ManifestParseError(
              'duplicate default in %s' %
              (self.manifestFile))
        self._default = self._ParseDefault(node)
    if self._default is None:
      self._default = _Default()

    for node in config.childNodes:
      if node.nodeName == 'notice':
        if self._notice is not None:
          raise ManifestParseError(
              'duplicate notice in %s' %
              (self.manifestFile))
        self._notice = self._ParseNotice(node)

    for node in config.childNodes:
      if node.nodeName == 'manifest-server':
        url = self._reqatt(node, 'url')
        if self._manifest_server is not None:
            raise ManifestParseError(
                'duplicate manifest-server in %s' %
                (self.manifestFile))
        self._manifest_server = url

    for node in config.childNodes:
      if node.nodeName == 'project':
        project = self._ParseProject(node)
        if self._projects.get(project.name):
          raise ManifestParseError(
              'duplicate project %s in %s' %
              (project.name, self.manifestFile))
        self._projects[project.name] = project

    for node in config.childNodes:
      if node.nodeName == 'repo-hooks':
        # Get the name of the project and the (space-separated) list of enabled.
        repo_hooks_project = self._reqatt(node, 'in-project')
        enabled_repo_hooks = self._reqatt(node, 'enabled-list').split()

        # Only one project can be the hooks project
        if self._repo_hooks_project is not None:
          raise ManifestParseError(
              'duplicate repo-hooks in %s' %
              (self.manifestFile))

        # Store a reference to the Project.
        try:
          self._repo_hooks_project = self._projects[repo_hooks_project]
        except KeyError:
          raise ManifestParseError(
              'project %s not found for repo-hooks' %
              (repo_hooks_project))

        # Store the enabled hooks in the Project object.
        self._repo_hooks_project.enabled_repo_hooks = enabled_repo_hooks

  def _AddMetaProjectMirror(self, m):
    name = None
    m_url = m.GetRemote(m.remote.name).url
    if m_url.endswith('/.git'):
      raise ManifestParseError, 'refusing to mirror %s' % m_url

    if self._default and self._default.remote:
      url = self._default.remote.resolvedFetchUrl
      if not url.endswith('/'):
        url += '/'
      if m_url.startswith(url):
        remote = self._default.remote
        name = m_url[len(url):]

    if name is None:
      s = m_url.rindex('/') + 1
      manifestUrl = self.manifestProject.config.GetString('remote.origin.url')
      remote = _XmlRemote('origin', m_url[:s], manifestUrl)
      name = m_url[s:]

    if name.endswith('.git'):
      name = name[:-4]

    if name not in self._projects:
      m.PreSync()
      gitdir = os.path.join(self.topdir, '%s.git' % name)
      project = Project(manifest = self,
                        name = name,
                        remote = remote.ToRemoteSpec(name),
                        gitdir = gitdir,
                        worktree = None,
                        relpath = None,
                        revisionExpr = m.revisionExpr,
                        revisionId = None)
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
    manifestUrl = self.manifestProject.config.GetString('remote.origin.url')
    return _XmlRemote(name, fetch, manifestUrl, review)

  def _ParseDefault(self, node):
    """
    reads a <default> element from the manifest file
    """
    d = _Default()
    d.remote = self._get_remote(node)
    d.revisionExpr = node.getAttribute('revision')
    if d.revisionExpr == '':
      d.revisionExpr = None
    sync_j = node.getAttribute('sync-j')
    if sync_j == '' or sync_j is None:
      d.sync_j = 1
    else:
      d.sync_j = int(sync_j)
    return d

  def _ParseNotice(self, node):
    """
    reads a <notice> element from the manifest file

    The <notice> element is distinct from other tags in the XML in that the
    data is conveyed between the start and end tag (it's not an empty-element
    tag).

    The white space (carriage returns, indentation) for the notice element is
    relevant and is parsed in a way that is based on how python docstrings work.
    In fact, the code is remarkably similar to here:
      http://www.python.org/dev/peps/pep-0257/
    """
    # Get the data out of the node...
    notice = node.childNodes[0].data

    # Figure out minimum indentation, skipping the first line (the same line
    # as the <notice> tag)...
    minIndent = sys.maxint
    lines = notice.splitlines()
    for line in lines[1:]:
      lstrippedLine = line.lstrip()
      if lstrippedLine:
        indent = len(line) - len(lstrippedLine)
        minIndent = min(indent, minIndent)

    # Strip leading / trailing blank lines and also indentation.
    cleanLines = [lines[0].strip()]
    for line in lines[1:]:
      cleanLines.append(line[minIndent:].rstrip())

    # Clear completely blank lines from front and back...
    while cleanLines and not cleanLines[0]:
      del cleanLines[0]
    while cleanLines and not cleanLines[-1]:
      del cleanLines[-1]

    return '\n'.join(cleanLines)

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

    revisionExpr = node.getAttribute('revision')
    if not revisionExpr:
      revisionExpr = self._default.revisionExpr
    if not revisionExpr:
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

    rebase = node.getAttribute('rebase')
    if not rebase:
      rebase = True
    else:
      rebase = rebase.lower() in ("yes", "true", "1")

    if self.IsMirror:
      relpath = None
      worktree = None
      gitdir = os.path.join(self.topdir, '%s.git' % name)
    else:
      worktree = os.path.join(self.topdir, path).replace('\\', '/')
      gitdir = os.path.join(self.repodir, 'projects/%s.git' % path)

    project = Project(manifest = self,
                      name = name,
                      remote = remote.ToRemoteSpec(name),
                      gitdir = gitdir,
                      worktree = worktree,
                      relpath = path,
                      revisionExpr = revisionExpr,
                      revisionId = None,
                      rebase = rebase)

    for n in node.childNodes:
      if n.nodeName == 'copyfile':
        self._ParseCopyFile(project, n)

    return project

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
