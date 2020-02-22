# -*- coding:utf-8 -*-
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

from __future__ import print_function
import itertools
import os
import re
import sys
import xml.dom.minidom

from pyversion import is_python3
if is_python3():
  import urllib.parse
else:
  import imp
  import urlparse
  urllib = imp.new_module('urllib')
  urllib.parse = urlparse

import gitc_utils
from git_config import GitConfig
from git_refs import R_HEADS, HEAD
import platform_utils
from project import RemoteSpec, Project, MetaProject
from error import (ManifestParseError, ManifestInvalidPathError,
                   ManifestInvalidRevisionError)

MANIFEST_FILE_NAME = 'manifest.xml'
LOCAL_MANIFEST_NAME = 'local_manifest.xml'
LOCAL_MANIFESTS_DIR_NAME = 'local_manifests'

# urljoin gets confused if the scheme is not known.
urllib.parse.uses_relative.extend([
    'ssh',
    'git',
    'persistent-https',
    'sso',
    'rpc'])
urllib.parse.uses_netloc.extend([
    'ssh',
    'git',
    'persistent-https',
    'sso',
    'rpc'])


def XmlBool(node, attr, default=None):
  """Determine boolean value of |node|'s |attr|.

  Invalid values will issue a non-fatal warning.

  Args:
    node: XML node whose attributes we access.
    attr: The attribute to access.
    default: If the attribute is not set (value is empty), then use this.

  Returns:
    True if the attribute is a valid string representing true.
    False if the attribute is a valid string representing false.
    |default| otherwise.
  """
  value = node.getAttribute(attr)
  s = value.lower()
  if s == '':
    return default
  elif s in {'yes', 'true', '1'}:
    return True
  elif s in {'no', 'false', '0'}:
    return False
  else:
    print('warning: manifest: %s="%s": ignoring invalid XML boolean' %
          (attr, value), file=sys.stderr)
    return default


def XmlInt(node, attr, default=None):
  """Determine integer value of |node|'s |attr|.

  Args:
    node: XML node whose attributes we access.
    attr: The attribute to access.
    default: If the attribute is not set (value is empty), then use this.

  Returns:
    The number if the attribute is a valid number.

  Raises:
    ManifestParseError: The number is invalid.
  """
  value = node.getAttribute(attr)
  if not value:
    return default

  try:
    return int(value)
  except ValueError:
    raise ManifestParseError('manifest: invalid %s="%s" integer' %
                             (attr, value))


class _Default(object):
  """Project defaults within the manifest."""

  revisionExpr = None
  destBranchExpr = None
  upstreamExpr = None
  remote = None
  sync_j = 1
  sync_c = False
  sync_s = False
  sync_tags = True

  def __eq__(self, other):
    return self.__dict__ == other.__dict__

  def __ne__(self, other):
    return self.__dict__ != other.__dict__


class _XmlRemote(object):
  def __init__(self,
               name,
               alias=None,
               fetch=None,
               pushUrl=None,
               manifestUrl=None,
               review=None,
               revision=None):
    self.name = name
    self.fetchUrl = fetch
    self.pushUrl = pushUrl
    self.manifestUrl = manifestUrl
    self.remoteAlias = alias
    self.reviewUrl = review
    self.revision = revision
    self.resolvedFetchUrl = self._resolveFetchUrl()

  def __eq__(self, other):
    return self.__dict__ == other.__dict__

  def __ne__(self, other):
    return self.__dict__ != other.__dict__

  def _resolveFetchUrl(self):
    url = self.fetchUrl.rstrip('/')
    manifestUrl = self.manifestUrl.rstrip('/')
    # urljoin will gets confused over quite a few things.  The ones we care
    # about here are:
    # * no scheme in the base url, like <hostname:port>
    # We handle no scheme by replacing it with an obscure protocol, gopher
    # and then replacing it with the original when we are done.

    if manifestUrl.find(':') != manifestUrl.find('/') - 1:
      url = urllib.parse.urljoin('gopher://' + manifestUrl, url)
      url = re.sub(r'^gopher://', '', url)
    else:
      url = urllib.parse.urljoin(manifestUrl, url)
    return url

  def ToRemoteSpec(self, projectName):
    fetchUrl = self.resolvedFetchUrl.rstrip('/')
    url = fetchUrl + '/' + projectName
    remoteName = self.name
    if self.remoteAlias:
      remoteName = self.remoteAlias
    return RemoteSpec(remoteName,
                      url=url,
                      pushUrl=self.pushUrl,
                      review=self.reviewUrl,
                      orig_name=self.name,
                      fetchUrl=self.fetchUrl)


class XmlManifest(object):
  """manages the repo configuration file"""

  def __init__(self, repodir):
    self.repodir = os.path.abspath(repodir)
    self.topdir = os.path.dirname(self.repodir)
    self.manifestFile = os.path.join(self.repodir, MANIFEST_FILE_NAME)
    self.globalConfig = GitConfig.ForUser()
    self.localManifestWarning = False
    self.isGitcClient = False
    self._load_local_manifests = True

    self.repoProject = MetaProject(self, 'repo',
                                   gitdir=os.path.join(repodir, 'repo/.git'),
                                   worktree=os.path.join(repodir, 'repo'))

    mp = MetaProject(self, 'manifests',
                     gitdir=os.path.join(repodir, 'manifests.git'),
                     worktree=os.path.join(repodir, 'manifests'))
    self.manifestProject = mp

    # This is a bit hacky, but we're in a chicken & egg situation: all the
    # normal repo settings live in the manifestProject which we just setup
    # above, so we couldn't easily query before that.  We assume Project()
    # init doesn't care if this changes afterwards.
    if os.path.exists(mp.gitdir) and mp.config.GetBoolean('repo.worktree'):
      mp.use_git_worktrees = True

    self._Unload()

  def Override(self, name, load_local_manifests=True):
    """Use a different manifest, just for the current instantiation.
    """
    path = None

    # Look for a manifest by path in the filesystem (including the cwd).
    if not load_local_manifests:
      local_path = os.path.abspath(name)
      if os.path.isfile(local_path):
        path = local_path

    # Look for manifests by name from the manifests repo.
    if path is None:
      path = os.path.join(self.manifestProject.worktree, name)
      if not os.path.isfile(path):
        raise ManifestParseError('manifest %s not found' % name)

    old = self.manifestFile
    try:
      self._load_local_manifests = load_local_manifests
      self.manifestFile = path
      self._Unload()
      self._Load()
    finally:
      self.manifestFile = old

  def Link(self, name):
    """Update the repo metadata to use a different manifest.
    """
    self.Override(name)

    # Old versions of repo would generate symlinks we need to clean up.
    if os.path.lexists(self.manifestFile):
      platform_utils.remove(self.manifestFile)
    # This file is interpreted as if it existed inside the manifest repo.
    # That allows us to use <include> with the relative file name.
    with open(self.manifestFile, 'w') as fp:
      fp.write("""<?xml version="1.0" encoding="UTF-8"?>
<!--
DO NOT EDIT THIS FILE!  It is generated by repo and changes will be discarded.
If you want to use a different manifest, use `repo init -m <file>` instead.

If you want to customize your checkout by overriding manifest settings, use
the local_manifests/ directory instead.

For more information on repo manifests, check out:
https://gerrit.googlesource.com/git-repo/+/HEAD/docs/manifest-format.md
-->
<manifest>
  <include name="%s" />
</manifest>
""" % (name,))

  def _RemoteToXml(self, r, doc, root):
    e = doc.createElement('remote')
    root.appendChild(e)
    e.setAttribute('name', r.name)
    e.setAttribute('fetch', r.fetchUrl)
    if r.pushUrl is not None:
      e.setAttribute('pushurl', r.pushUrl)
    if r.remoteAlias is not None:
      e.setAttribute('alias', r.remoteAlias)
    if r.reviewUrl is not None:
      e.setAttribute('review', r.reviewUrl)
    if r.revision is not None:
      e.setAttribute('revision', r.revision)

  def _ParseGroups(self, groups):
    return [x for x in re.split(r'[,\s]+', groups) if x]

  def Save(self, fd, peg_rev=False, peg_rev_upstream=True, groups=None):
    """Write the current manifest out to the given file descriptor.
    """
    mp = self.manifestProject

    if groups is None:
      groups = mp.config.GetString('manifest.groups')
    if groups:
      groups = self._ParseGroups(groups)

    doc = xml.dom.minidom.Document()
    root = doc.createElement('manifest')
    doc.appendChild(root)

    # Save out the notice.  There's a little bit of work here to give it the
    # right whitespace, which assumes that the notice is automatically indented
    # by 4 by minidom.
    if self.notice:
      notice_element = root.appendChild(doc.createElement('notice'))
      notice_lines = self.notice.splitlines()
      indented_notice = ('\n'.join(" " * 4 + line for line in notice_lines))[4:]
      notice_element.appendChild(doc.createTextNode(indented_notice))

    d = self.default

    for r in sorted(self.remotes):
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
    if d.destBranchExpr:
      have_default = True
      e.setAttribute('dest-branch', d.destBranchExpr)
    if d.upstreamExpr:
      have_default = True
      e.setAttribute('upstream', d.upstreamExpr)
    if d.sync_j > 1:
      have_default = True
      e.setAttribute('sync-j', '%d' % d.sync_j)
    if d.sync_c:
      have_default = True
      e.setAttribute('sync-c', 'true')
    if d.sync_s:
      have_default = True
      e.setAttribute('sync-s', 'true')
    if not d.sync_tags:
      have_default = True
      e.setAttribute('sync-tags', 'false')
    if have_default:
      root.appendChild(e)
      root.appendChild(doc.createTextNode(''))

    if self._manifest_server:
      e = doc.createElement('manifest-server')
      e.setAttribute('url', self._manifest_server)
      root.appendChild(e)
      root.appendChild(doc.createTextNode(''))

    def output_projects(parent, parent_node, projects):
      for project_name in projects:
        for project in self._projects[project_name]:
          output_project(parent, parent_node, project)

    def output_project(parent, parent_node, p):
      if not p.MatchesGroups(groups):
        return

      name = p.name
      relpath = p.relpath
      if parent:
        name = self._UnjoinName(parent.name, name)
        relpath = self._UnjoinRelpath(parent.relpath, relpath)

      e = doc.createElement('project')
      parent_node.appendChild(e)
      e.setAttribute('name', name)
      if relpath != name:
        e.setAttribute('path', relpath)
      remoteName = None
      if d.remote:
        remoteName = d.remote.name
      if not d.remote or p.remote.orig_name != remoteName:
        remoteName = p.remote.orig_name
        e.setAttribute('remote', remoteName)
      if peg_rev:
        if self.IsMirror:
          value = p.bare_git.rev_parse(p.revisionExpr + '^0')
        else:
          value = p.work_git.rev_parse(HEAD + '^0')
        e.setAttribute('revision', value)
        if peg_rev_upstream:
          if p.upstream:
            e.setAttribute('upstream', p.upstream)
          elif value != p.revisionExpr:
            # Only save the origin if the origin is not a sha1, and the default
            # isn't our value
            e.setAttribute('upstream', p.revisionExpr)
      else:
        revision = self.remotes[p.remote.orig_name].revision or d.revisionExpr
        if not revision or revision != p.revisionExpr:
          e.setAttribute('revision', p.revisionExpr)
        if (p.upstream and (p.upstream != p.revisionExpr or
                            p.upstream != d.upstreamExpr)):
          e.setAttribute('upstream', p.upstream)

      if p.dest_branch and p.dest_branch != d.destBranchExpr:
        e.setAttribute('dest-branch', p.dest_branch)

      for c in p.copyfiles:
        ce = doc.createElement('copyfile')
        ce.setAttribute('src', c.src)
        ce.setAttribute('dest', c.dest)
        e.appendChild(ce)

      for l in p.linkfiles:
        le = doc.createElement('linkfile')
        le.setAttribute('src', l.src)
        le.setAttribute('dest', l.dest)
        e.appendChild(le)

      default_groups = ['all', 'name:%s' % p.name, 'path:%s' % p.relpath]
      egroups = [g for g in p.groups if g not in default_groups]
      if egroups:
        e.setAttribute('groups', ','.join(egroups))

      for a in p.annotations:
        if a.keep == "true":
          ae = doc.createElement('annotation')
          ae.setAttribute('name', a.name)
          ae.setAttribute('value', a.value)
          e.appendChild(ae)

      if p.sync_c:
        e.setAttribute('sync-c', 'true')

      if p.sync_s:
        e.setAttribute('sync-s', 'true')

      if not p.sync_tags:
        e.setAttribute('sync-tags', 'false')

      if p.clone_depth:
        e.setAttribute('clone-depth', str(p.clone_depth))

      self._output_manifest_project_extras(p, e)

      if p.subprojects:
        subprojects = set(subp.name for subp in p.subprojects)
        output_projects(p, e, list(sorted(subprojects)))

    projects = set(p.name for p in self._paths.values() if not p.parent)
    output_projects(None, root, list(sorted(projects)))

    if self._repo_hooks_project:
      root.appendChild(doc.createTextNode(''))
      e = doc.createElement('repo-hooks')
      e.setAttribute('in-project', self._repo_hooks_project.name)
      e.setAttribute('enabled-list',
                     ' '.join(self._repo_hooks_project.enabled_repo_hooks))
      root.appendChild(e)

    doc.writexml(fd, '', '  ', '\n', 'UTF-8')

  def _output_manifest_project_extras(self, p, e):
    """Manifests can modify e if they support extra project attributes."""
    pass

  @property
  def paths(self):
    self._Load()
    return self._paths

  @property
  def projects(self):
    self._Load()
    return list(self._paths.values())

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
  def CloneFilter(self):
    if self.manifestProject.config.GetBoolean('repo.partialclone'):
      return self.manifestProject.config.GetString('repo.clonefilter')
    return None

  @property
  def IsMirror(self):
    return self.manifestProject.config.GetBoolean('repo.mirror')

  @property
  def UseGitWorktrees(self):
    return self.manifestProject.config.GetBoolean('repo.worktree')

  @property
  def IsArchive(self):
    return self.manifestProject.config.GetBoolean('repo.archive')

  @property
  def HasSubmodules(self):
    return self.manifestProject.config.GetBoolean('repo.submodules')

  def _Unload(self):
    self._loaded = False
    self._projects = {}
    self._paths = {}
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

      nodes = []
      nodes.append(self._ParseManifestXml(self.manifestFile,
                                          self.manifestProject.worktree))

      if self._load_local_manifests:
        local = os.path.join(self.repodir, LOCAL_MANIFEST_NAME)
        if os.path.exists(local):
          if not self.localManifestWarning:
            self.localManifestWarning = True
            print('warning: %s is deprecated; put local manifests '
                  'in `%s` instead' % (LOCAL_MANIFEST_NAME,
                                       os.path.join(self.repodir, LOCAL_MANIFESTS_DIR_NAME)),
                  file=sys.stderr)
          nodes.append(self._ParseManifestXml(local, self.repodir))

        local_dir = os.path.abspath(os.path.join(self.repodir,
                                                 LOCAL_MANIFESTS_DIR_NAME))
        try:
          for local_file in sorted(platform_utils.listdir(local_dir)):
            if local_file.endswith('.xml'):
              local = os.path.join(local_dir, local_file)
              nodes.append(self._ParseManifestXml(local, self.repodir))
        except OSError:
          pass

      try:
        self._ParseManifest(nodes)
      except ManifestParseError as e:
        # There was a problem parsing, unload ourselves in case they catch
        # this error and try again later, we will show the correct error
        self._Unload()
        raise e

      if self.IsMirror:
        self._AddMetaProjectMirror(self.repoProject)
        self._AddMetaProjectMirror(self.manifestProject)

      self._loaded = True

  def _ParseManifestXml(self, path, include_root):
    try:
      root = xml.dom.minidom.parse(path)
    except (OSError, xml.parsers.expat.ExpatError) as e:
      raise ManifestParseError("error parsing manifest %s: %s" % (path, e))

    if not root or not root.childNodes:
      raise ManifestParseError("no root node in %s" % (path,))

    for manifest in root.childNodes:
      if manifest.nodeName == 'manifest':
        break
    else:
      raise ManifestParseError("no <manifest> in %s" % (path,))

    nodes = []
    for node in manifest.childNodes:
      if node.nodeName == 'include':
        name = self._reqatt(node, 'name')
        fp = os.path.join(include_root, name)
        if not os.path.isfile(fp):
          raise ManifestParseError("include %s doesn't exist or isn't a file"
                                   % (name,))
        try:
          nodes.extend(self._ParseManifestXml(fp, include_root))
        # should isolate this to the exact exception, but that's
        # tricky.  actual parsing implementation may vary.
        except (KeyboardInterrupt, RuntimeError, SystemExit):
          raise
        except Exception as e:
          raise ManifestParseError(
              "failed parsing included manifest %s: %s" % (name, e))
      else:
        nodes.append(node)
    return nodes

  def _ParseManifest(self, node_list):
    for node in itertools.chain(*node_list):
      if node.nodeName == 'remote':
        remote = self._ParseRemote(node)
        if remote:
          if remote.name in self._remotes:
            if remote != self._remotes[remote.name]:
              raise ManifestParseError(
                  'remote %s already exists with different attributes' %
                  (remote.name))
          else:
            self._remotes[remote.name] = remote

    for node in itertools.chain(*node_list):
      if node.nodeName == 'default':
        new_default = self._ParseDefault(node)
        if self._default is None:
          self._default = new_default
        elif new_default != self._default:
          raise ManifestParseError('duplicate default in %s' %
                                   (self.manifestFile))

    if self._default is None:
      self._default = _Default()

    for node in itertools.chain(*node_list):
      if node.nodeName == 'notice':
        if self._notice is not None:
          raise ManifestParseError(
              'duplicate notice in %s' %
              (self.manifestFile))
        self._notice = self._ParseNotice(node)

    for node in itertools.chain(*node_list):
      if node.nodeName == 'manifest-server':
        url = self._reqatt(node, 'url')
        if self._manifest_server is not None:
          raise ManifestParseError(
              'duplicate manifest-server in %s' %
              (self.manifestFile))
        self._manifest_server = url

    def recursively_add_projects(project):
      projects = self._projects.setdefault(project.name, [])
      if project.relpath is None:
        raise ManifestParseError(
            'missing path for %s in %s' %
            (project.name, self.manifestFile))
      if project.relpath in self._paths:
        raise ManifestParseError(
            'duplicate path %s in %s' %
            (project.relpath, self.manifestFile))
      self._paths[project.relpath] = project
      projects.append(project)
      for subproject in project.subprojects:
        recursively_add_projects(subproject)

    for node in itertools.chain(*node_list):
      if node.nodeName == 'project':
        project = self._ParseProject(node)
        recursively_add_projects(project)
      if node.nodeName == 'extend-project':
        name = self._reqatt(node, 'name')

        if name not in self._projects:
          raise ManifestParseError('extend-project element specifies non-existent '
                                   'project: %s' % name)

        path = node.getAttribute('path')
        groups = node.getAttribute('groups')
        if groups:
          groups = self._ParseGroups(groups)
        revision = node.getAttribute('revision')
        remote = node.getAttribute('remote')
        if remote:
          remote = self._get_remote(node)

        for p in self._projects[name]:
          if path and p.relpath != path:
            continue
          if groups:
            p.groups.extend(groups)
          if revision:
            p.revisionExpr = revision
          if remote:
            p.remote = remote.ToRemoteSpec(name)
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
          repo_hooks_projects = self._projects[repo_hooks_project]
        except KeyError:
          raise ManifestParseError(
              'project %s not found for repo-hooks' %
              (repo_hooks_project))

        if len(repo_hooks_projects) != 1:
          raise ManifestParseError(
              'internal error parsing repo-hooks in %s' %
              (self.manifestFile))
        self._repo_hooks_project = repo_hooks_projects[0]

        # Store the enabled hooks in the Project object.
        self._repo_hooks_project.enabled_repo_hooks = enabled_repo_hooks
      if node.nodeName == 'remove-project':
        name = self._reqatt(node, 'name')

        if name not in self._projects:
          raise ManifestParseError('remove-project element specifies non-existent '
                                   'project: %s' % name)

        for p in self._projects[name]:
          del self._paths[p.relpath]
        del self._projects[name]

        # If the manifest removes the hooks project, treat it as if it deleted
        # the repo-hooks element too.
        if self._repo_hooks_project and (self._repo_hooks_project.name == name):
          self._repo_hooks_project = None

  def _AddMetaProjectMirror(self, m):
    name = None
    m_url = m.GetRemote(m.remote.name).url
    if m_url.endswith('/.git'):
      raise ManifestParseError('refusing to mirror %s' % m_url)

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
      remote = _XmlRemote('origin', fetch=m_url[:s], manifestUrl=manifestUrl)
      name = m_url[s:]

    if name.endswith('.git'):
      name = name[:-4]

    if name not in self._projects:
      m.PreSync()
      gitdir = os.path.join(self.topdir, '%s.git' % name)
      project = Project(manifest=self,
                        name=name,
                        remote=remote.ToRemoteSpec(name),
                        gitdir=gitdir,
                        objdir=gitdir,
                        worktree=None,
                        relpath=name or None,
                        revisionExpr=m.revisionExpr,
                        revisionId=None)
      self._projects[project.name] = [project]
      self._paths[project.relpath] = project

  def _ParseRemote(self, node):
    """
    reads a <remote> element from the manifest file
    """
    name = self._reqatt(node, 'name')
    alias = node.getAttribute('alias')
    if alias == '':
      alias = None
    fetch = self._reqatt(node, 'fetch')
    pushUrl = node.getAttribute('pushurl')
    if pushUrl == '':
      pushUrl = None
    review = node.getAttribute('review')
    if review == '':
      review = None
    revision = node.getAttribute('revision')
    if revision == '':
      revision = None
    manifestUrl = self.manifestProject.config.GetString('remote.origin.url')
    return _XmlRemote(name, alias, fetch, pushUrl, manifestUrl, review, revision)

  def _ParseDefault(self, node):
    """
    reads a <default> element from the manifest file
    """
    d = _Default()
    d.remote = self._get_remote(node)
    d.revisionExpr = node.getAttribute('revision')
    if d.revisionExpr == '':
      d.revisionExpr = None

    d.destBranchExpr = node.getAttribute('dest-branch') or None
    d.upstreamExpr = node.getAttribute('upstream') or None

    d.sync_j = XmlInt(node, 'sync-j', 1)
    if d.sync_j <= 0:
      raise ManifestParseError('%s: sync-j must be greater than 0, not "%s"' %
                               (self.manifestFile, d.sync_j))

    d.sync_c = XmlBool(node, 'sync-c', False)
    d.sync_s = XmlBool(node, 'sync-s', False)
    d.sync_tags = XmlBool(node, 'sync-tags', True)
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
    minIndent = sys.maxsize
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

  def _JoinName(self, parent_name, name):
    return os.path.join(parent_name, name)

  def _UnjoinName(self, parent_name, name):
    return os.path.relpath(name, parent_name)

  def _ParseProject(self, node, parent=None, **extra_proj_attrs):
    """
    reads a <project> element from the manifest file
    """
    name = self._reqatt(node, 'name')
    if parent:
      name = self._JoinName(parent.name, name)

    remote = self._get_remote(node)
    if remote is None:
      remote = self._default.remote
    if remote is None:
      raise ManifestParseError("no remote for project %s within %s" %
                               (name, self.manifestFile))

    revisionExpr = node.getAttribute('revision') or remote.revision
    if not revisionExpr:
      revisionExpr = self._default.revisionExpr
    if not revisionExpr:
      raise ManifestParseError("no revision for project %s within %s" %
                               (name, self.manifestFile))

    path = node.getAttribute('path')
    if not path:
      path = name
    if path.startswith('/'):
      raise ManifestParseError("project %s path cannot be absolute in %s" %
                               (name, self.manifestFile))

    rebase = XmlBool(node, 'rebase', True)
    sync_c = XmlBool(node, 'sync-c', False)
    sync_s = XmlBool(node, 'sync-s', self._default.sync_s)
    sync_tags = XmlBool(node, 'sync-tags', self._default.sync_tags)

    clone_depth = XmlInt(node, 'clone-depth')
    if clone_depth is not None and clone_depth <= 0:
      raise ManifestParseError('%s: clone-depth must be greater than 0, not "%s"' %
                               (self.manifestFile, clone_depth))

    dest_branch = node.getAttribute('dest-branch') or self._default.destBranchExpr

    upstream = node.getAttribute('upstream') or self._default.upstreamExpr

    groups = ''
    if node.hasAttribute('groups'):
      groups = node.getAttribute('groups')
    groups = self._ParseGroups(groups)

    if parent is None:
      relpath, worktree, gitdir, objdir, use_git_worktrees = \
          self.GetProjectPaths(name, path)
    else:
      use_git_worktrees = False
      relpath, worktree, gitdir, objdir = \
          self.GetSubprojectPaths(parent, name, path)

    default_groups = ['all', 'name:%s' % name, 'path:%s' % relpath]
    groups.extend(set(default_groups).difference(groups))

    if self.IsMirror and node.hasAttribute('force-path'):
      if XmlBool(node, 'force-path', False):
        gitdir = os.path.join(self.topdir, '%s.git' % path)

    project = Project(manifest=self,
                      name=name,
                      remote=remote.ToRemoteSpec(name),
                      gitdir=gitdir,
                      objdir=objdir,
                      worktree=worktree,
                      relpath=relpath,
                      revisionExpr=revisionExpr,
                      revisionId=None,
                      rebase=rebase,
                      groups=groups,
                      sync_c=sync_c,
                      sync_s=sync_s,
                      sync_tags=sync_tags,
                      clone_depth=clone_depth,
                      upstream=upstream,
                      parent=parent,
                      dest_branch=dest_branch,
                      use_git_worktrees=use_git_worktrees,
                      **extra_proj_attrs)

    for n in node.childNodes:
      if n.nodeName == 'copyfile':
        self._ParseCopyFile(project, n)
      if n.nodeName == 'linkfile':
        self._ParseLinkFile(project, n)
      if n.nodeName == 'annotation':
        self._ParseAnnotation(project, n)
      if n.nodeName == 'project':
        project.subprojects.append(self._ParseProject(n, parent=project))

    return project

  def GetProjectPaths(self, name, path):
    use_git_worktrees = False
    relpath = path
    if self.IsMirror:
      worktree = None
      gitdir = os.path.join(self.topdir, '%s.git' % name)
      objdir = gitdir
    else:
      worktree = os.path.join(self.topdir, path).replace('\\', '/')
      gitdir = os.path.join(self.repodir, 'projects', '%s.git' % path)
      # We allow people to mix git worktrees & non-git worktrees for now.
      # This allows for in situ migration of repo clients.
      if os.path.exists(gitdir) or not self.UseGitWorktrees:
        objdir = os.path.join(self.repodir, 'project-objects', '%s.git' % name)
      else:
        use_git_worktrees = True
        gitdir = os.path.join(self.repodir, 'worktrees', '%s.git' % name)
        objdir = gitdir
    return relpath, worktree, gitdir, objdir, use_git_worktrees

  def GetProjectsWithName(self, name):
    return self._projects.get(name, [])

  def GetSubprojectName(self, parent, submodule_path):
    return os.path.join(parent.name, submodule_path)

  def _JoinRelpath(self, parent_relpath, relpath):
    return os.path.join(parent_relpath, relpath)

  def _UnjoinRelpath(self, parent_relpath, relpath):
    return os.path.relpath(relpath, parent_relpath)

  def GetSubprojectPaths(self, parent, name, path):
    relpath = self._JoinRelpath(parent.relpath, path)
    gitdir = os.path.join(parent.gitdir, 'subprojects', '%s.git' % path)
    objdir = os.path.join(parent.gitdir, 'subproject-objects', '%s.git' % name)
    if self.IsMirror:
      worktree = None
    else:
      worktree = os.path.join(parent.worktree, path).replace('\\', '/')
    return relpath, worktree, gitdir, objdir

  @staticmethod
  def _CheckLocalPath(path, symlink=False):
    """Verify |path| is reasonable for use in <copyfile> & <linkfile>."""
    if '~' in path:
      return '~ not allowed (due to 8.3 filenames on Windows filesystems)'

    # Some filesystems (like Apple's HFS+) try to normalize Unicode codepoints
    # which means there are alternative names for ".git".  Reject paths with
    # these in it as there shouldn't be any reasonable need for them here.
    # The set of codepoints here was cribbed from jgit's implementation:
    # https://eclipse.googlesource.com/jgit/jgit/+/9110037e3e9461ff4dac22fee84ef3694ed57648/org.eclipse.jgit/src/org/eclipse/jgit/lib/ObjectChecker.java#884
    BAD_CODEPOINTS = {
        u'\u200C',  # ZERO WIDTH NON-JOINER
        u'\u200D',  # ZERO WIDTH JOINER
        u'\u200E',  # LEFT-TO-RIGHT MARK
        u'\u200F',  # RIGHT-TO-LEFT MARK
        u'\u202A',  # LEFT-TO-RIGHT EMBEDDING
        u'\u202B',  # RIGHT-TO-LEFT EMBEDDING
        u'\u202C',  # POP DIRECTIONAL FORMATTING
        u'\u202D',  # LEFT-TO-RIGHT OVERRIDE
        u'\u202E',  # RIGHT-TO-LEFT OVERRIDE
        u'\u206A',  # INHIBIT SYMMETRIC SWAPPING
        u'\u206B',  # ACTIVATE SYMMETRIC SWAPPING
        u'\u206C',  # INHIBIT ARABIC FORM SHAPING
        u'\u206D',  # ACTIVATE ARABIC FORM SHAPING
        u'\u206E',  # NATIONAL DIGIT SHAPES
        u'\u206F',  # NOMINAL DIGIT SHAPES
        u'\uFEFF',  # ZERO WIDTH NO-BREAK SPACE
    }
    if BAD_CODEPOINTS & set(path):
      # This message is more expansive than reality, but should be fine.
      return 'Unicode combining characters not allowed'

    # Assume paths might be used on case-insensitive filesystems.
    path = path.lower()

    # Split up the path by its components.  We can't use os.path.sep exclusively
    # as some platforms (like Windows) will convert / to \ and that bypasses all
    # our constructed logic here.  Especially since manifest authors only use
    # / in their paths.
    resep = re.compile(r'[/%s]' % re.escape(os.path.sep))
    parts = resep.split(path)

    # Some people use src="." to create stable links to projects.  Lets allow
    # that but reject all other uses of "." to keep things simple.
    if parts != ['.']:
      for part in set(parts):
        if part in {'.', '..', '.git'} or part.startswith('.repo'):
          return 'bad component: %s' % (part,)

    if not symlink and resep.match(path[-1]):
      return 'dirs not allowed'

    # NB: The two abspath checks here are to handle platforms with multiple
    # filesystem path styles (e.g. Windows).
    norm = os.path.normpath(path)
    if (norm == '..' or
        (len(norm) >= 3 and norm.startswith('..') and resep.match(norm[0])) or
        os.path.isabs(norm) or
        norm.startswith('/')):
      return 'path cannot be outside'

  @classmethod
  def _ValidateFilePaths(cls, element, src, dest):
    """Verify |src| & |dest| are reasonable for <copyfile> & <linkfile>.

    We verify the path independent of any filesystem state as we won't have a
    checkout available to compare to.  i.e. This is for parsing validation
    purposes only.

    We'll do full/live sanity checking before we do the actual filesystem
    modifications in _CopyFile/_LinkFile/etc...
    """
    # |dest| is the file we write to or symlink we create.
    # It is relative to the top of the repo client checkout.
    msg = cls._CheckLocalPath(dest)
    if msg:
      raise ManifestInvalidPathError(
          '<%s> invalid "dest": %s: %s' % (element, dest, msg))

    # |src| is the file we read from or path we point to for symlinks.
    # It is relative to the top of the git project checkout.
    msg = cls._CheckLocalPath(src, symlink=element == 'linkfile')
    if msg:
      raise ManifestInvalidPathError(
          '<%s> invalid "src": %s: %s' % (element, src, msg))

  def _ParseCopyFile(self, project, node):
    src = self._reqatt(node, 'src')
    dest = self._reqatt(node, 'dest')
    if not self.IsMirror:
      # src is project relative;
      # dest is relative to the top of the tree.
      # We only validate paths if we actually plan to process them.
      self._ValidateFilePaths('copyfile', src, dest)
      project.AddCopyFile(src, dest, self.topdir)

  def _ParseLinkFile(self, project, node):
    src = self._reqatt(node, 'src')
    dest = self._reqatt(node, 'dest')
    if not self.IsMirror:
      # src is project relative;
      # dest is relative to the top of the tree.
      # We only validate paths if we actually plan to process them.
      self._ValidateFilePaths('linkfile', src, dest)
      project.AddLinkFile(src, dest, self.topdir)

  def _ParseAnnotation(self, project, node):
    name = self._reqatt(node, 'name')
    value = self._reqatt(node, 'value')
    try:
      keep = self._reqatt(node, 'keep').lower()
    except ManifestParseError:
      keep = "true"
    if keep != "true" and keep != "false":
      raise ManifestParseError('optional "keep" attribute must be '
                               '"true" or "false"')
    project.AddAnnotation(name, value, keep)

  def _get_remote(self, node):
    name = node.getAttribute('remote')
    if not name:
      return None

    v = self._remotes.get(name)
    if not v:
      raise ManifestParseError("remote %s not defined in %s" %
                               (name, self.manifestFile))
    return v

  def _reqatt(self, node, attname):
    """
    reads a required attribute from the node.
    """
    v = node.getAttribute(attname)
    if not v:
      raise ManifestParseError("no %s in <%s> within %s" %
                               (attname, node.nodeName, self.manifestFile))
    return v

  def projectsDiff(self, manifest):
    """return the projects differences between two manifests.

    The diff will be from self to given manifest.

    """
    fromProjects = self.paths
    toProjects = manifest.paths

    fromKeys = sorted(fromProjects.keys())
    toKeys = sorted(toProjects.keys())

    diff = {'added': [], 'removed': [], 'changed': [], 'unreachable': []}

    for proj in fromKeys:
      if proj not in toKeys:
        diff['removed'].append(fromProjects[proj])
      else:
        fromProj = fromProjects[proj]
        toProj = toProjects[proj]
        try:
          fromRevId = fromProj.GetCommitRevisionId()
          toRevId = toProj.GetCommitRevisionId()
        except ManifestInvalidRevisionError:
          diff['unreachable'].append((fromProj, toProj))
        else:
          if fromRevId != toRevId:
            diff['changed'].append((fromProj, toProj))
        toKeys.remove(proj)

    for proj in toKeys:
      diff['added'].append(toProjects[proj])

    return diff


class GitcManifest(XmlManifest):

  def __init__(self, repodir, gitc_client_name):
    """Initialize the GitcManifest object."""
    super(GitcManifest, self).__init__(repodir)
    self.isGitcClient = True
    self.gitc_client_name = gitc_client_name
    self.gitc_client_dir = os.path.join(gitc_utils.get_gitc_manifest_dir(),
                                        gitc_client_name)
    self.manifestFile = os.path.join(self.gitc_client_dir, '.manifest')

  def _ParseProject(self, node, parent=None):
    """Override _ParseProject and add support for GITC specific attributes."""
    return super(GitcManifest, self)._ParseProject(
        node, parent=parent, old_revision=node.getAttribute('old-revision'))

  def _output_manifest_project_extras(self, p, e):
    """Output GITC Specific Project attributes"""
    if p.old_revision:
      e.setAttribute('old-revision', str(p.old_revision))
