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

import collections
import itertools
import os
import platform
import re
import sys
import xml.dom.minidom
import urllib.parse

import gitc_utils
from git_config import GitConfig, IsId
from git_refs import R_HEADS, HEAD
from git_superproject import Superproject
import platform_utils
from project import (Annotation, RemoteSpec, Project, RepoProject,
                     ManifestProject)
from error import (ManifestParseError, ManifestInvalidPathError,
                   ManifestInvalidRevisionError)
from wrapper import Wrapper

MANIFEST_FILE_NAME = 'manifest.xml'
LOCAL_MANIFEST_NAME = 'local_manifest.xml'
LOCAL_MANIFESTS_DIR_NAME = 'local_manifests'
SUBMANIFEST_DIR = 'submanifests'
# Limit submanifests to an arbitrary depth for loop detection.
MAX_SUBMANIFEST_DEPTH = 8
# Add all projects from sub manifest into a group.
SUBMANIFEST_GROUP_PREFIX = 'submanifest:'

# Add all projects from local manifest into a group.
LOCAL_MANIFEST_GROUP_PREFIX = 'local:'

# ContactInfo has the self-registered bug url, supplied by the manifest authors.
ContactInfo = collections.namedtuple('ContactInfo', 'bugurl')

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
  sync_j = None
  sync_c = False
  sync_s = False
  sync_tags = True

  def __eq__(self, other):
    if not isinstance(other, _Default):
      return False
    return self.__dict__ == other.__dict__

  def __ne__(self, other):
    if not isinstance(other, _Default):
      return True
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
    self.annotations = []

  def __eq__(self, other):
    if not isinstance(other, _XmlRemote):
      return False
    return (sorted(self.annotations) == sorted(other.annotations) and
      self.name == other.name and self.fetchUrl == other.fetchUrl and
      self.pushUrl == other.pushUrl and self.remoteAlias == other.remoteAlias
      and self.reviewUrl == other.reviewUrl and self.revision == other.revision)

  def __ne__(self, other):
    return not self.__eq__(other)

  def _resolveFetchUrl(self):
    if self.fetchUrl is None:
      return ''
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

  def AddAnnotation(self, name, value, keep):
    self.annotations.append(Annotation(name, value, keep))


class _XmlSubmanifest:
  """Manage the <submanifest> element specified in the manifest.

  Attributes:
    name: a string, the name for this submanifest.
    remote: a string, the remote.name for this submanifest.
    project: a string, the name of the manifest project.
    revision: a string, the commitish.
    manifestName: a string, the submanifest file name.
    groups: a list of strings, the groups to add to all projects in the submanifest.
    default_groups: a list of strings, the default groups to sync.
    path: a string, the relative path for the submanifest checkout.
    parent: an XmlManifest, the parent manifest.
    annotations: (derived) a list of annotations.
    present: (derived) a boolean, whether the sub manifest file is present.
  """
  def __init__(self,
               name,
               remote=None,
               project=None,
               revision=None,
               manifestName=None,
               groups=None,
               default_groups=None,
               path=None,
               parent=None):
    self.name = name
    self.remote = remote
    self.project = project
    self.revision = revision
    self.manifestName = manifestName
    self.groups = groups
    self.default_groups = default_groups
    self.path = path
    self.parent = parent
    self.annotations = []
    outer_client = parent._outer_client or parent
    if self.remote and not self.project:
      raise ManifestParseError(
          f'Submanifest {name}: must specify project when remote is given.')
    # Construct the absolute path to the manifest file using the parent's
    # method, so that we can correctly create our repo_client.
    manifestFile = parent.SubmanifestInfoDir(
        os.path.join(parent.path_prefix, self.relpath),
        os.path.join('manifests', manifestName or 'default.xml'))
    linkFile = parent.SubmanifestInfoDir(
        os.path.join(parent.path_prefix, self.relpath), MANIFEST_FILE_NAME)
    rc = self.repo_client = RepoClient(
        parent.repodir, linkFile, parent_groups=','.join(groups) or '',
        submanifest_path=self.relpath, outer_client=outer_client,
        default_groups=default_groups)

    self.present = os.path.exists(manifestFile)

  def __eq__(self, other):
    if not isinstance(other, _XmlSubmanifest):
      return False
    return (
        self.name == other.name and
        self.remote == other.remote and
        self.project == other.project and
        self.revision == other.revision and
        self.manifestName == other.manifestName and
        self.groups == other.groups and
        self.default_groups == other.default_groups and
        self.path == other.path and
        sorted(self.annotations) == sorted(other.annotations))

  def __ne__(self, other):
    return not self.__eq__(other)

  def ToSubmanifestSpec(self):
    """Return a SubmanifestSpec object, populating attributes"""
    mp = self.parent.manifestProject
    remote = self.parent.remotes[self.remote or self.parent.default.remote.name]
    # If a project was given, generate the url from the remote and project.
    # If not, use this manifestProject's url.
    if self.project:
      manifestUrl = remote.ToRemoteSpec(self.project).url
    else:
      manifestUrl = mp.GetRemote().url
    manifestName = self.manifestName or 'default.xml'
    revision = self.revision or self.name
    path = self.path or revision.split('/')[-1]
    groups = self.groups or []
    default_groups = self.default_groups or []

    return SubmanifestSpec(self.name, manifestUrl, manifestName, revision, path,
                           groups)

  @property
  def relpath(self):
    """The path of this submanifest relative to the parent manifest."""
    revision = self.revision or self.name
    return self.path or revision.split('/')[-1]

  def GetGroupsStr(self):
    """Returns the `groups` given for this submanifest."""
    if self.groups:
      return ','.join(self.groups)
    return ''

  def GetDefaultGroupsStr(self):
    """Returns the `default-groups` given for this submanifest."""
    return ','.join(self.default_groups or [])

  def AddAnnotation(self, name, value, keep):
    """Add annotations to the submanifest."""
    self.annotations.append(Annotation(name, value, keep))


class SubmanifestSpec:
  """The submanifest element, with all fields expanded."""

  def __init__(self,
               name,
               manifestUrl,
               manifestName,
               revision,
               path,
               groups):
    self.name = name
    self.manifestUrl = manifestUrl
    self.manifestName = manifestName
    self.revision = revision
    self.path = path
    self.groups = groups or []


class XmlManifest(object):
  """manages the repo configuration file"""

  def __init__(self, repodir, manifest_file, local_manifests=None,
               outer_client=None, parent_groups='', submanifest_path='',
               default_groups=None):
    """Initialize.

    Args:
      repodir: Path to the .repo/ dir for holding all internal checkout state.
          It must be in the top directory of the repo client checkout.
      manifest_file: Full path to the manifest file to parse.  This will usually
          be |repodir|/|MANIFEST_FILE_NAME|.
      local_manifests: Full path to the directory of local override manifests.
          This will usually be |repodir|/|LOCAL_MANIFESTS_DIR_NAME|.
      outer_client: RepoClient of the outer manifest.
      parent_groups: a string, the groups to apply to this projects.
      submanifest_path: The submanifest root relative to the repo root.
      default_groups: a string, the default manifest groups to use.
    """
    # TODO(vapier): Move this out of this class.
    self.globalConfig = GitConfig.ForUser()

    self.repodir = os.path.abspath(repodir)
    self._CheckLocalPath(submanifest_path)
    self.topdir = os.path.dirname(self.repodir)
    if submanifest_path:
      # This avoids a trailing os.path.sep when submanifest_path is empty.
      self.topdir = os.path.join(self.topdir, submanifest_path)
    if manifest_file != os.path.abspath(manifest_file):
      raise ManifestParseError('manifest_file must be abspath')
    self.manifestFile = manifest_file
    if not outer_client or outer_client == self:
      # manifestFileOverrides only exists in the outer_client's manifest, since
      # that is the only instance left when Unload() is called on the outer
      # manifest.
      self.manifestFileOverrides = {}
    self.local_manifests = local_manifests
    self._load_local_manifests = True
    self.parent_groups = parent_groups
    self.default_groups = default_groups

    if outer_client and self.isGitcClient:
      raise ManifestParseError('Multi-manifest is incompatible with `gitc-init`')

    if submanifest_path and not outer_client:
      # If passing a submanifest_path, there must be an outer_client.
      raise ManifestParseError(f'Bad call to {self.__class__.__name__}')

    # If self._outer_client is None, this is not a checkout that supports
    # multi-tree.
    self._outer_client = outer_client or self

    self.repoProject = RepoProject(self, 'repo',
                                   gitdir=os.path.join(repodir, 'repo/.git'),
                                   worktree=os.path.join(repodir, 'repo'))

    mp = self.SubmanifestProject(self.path_prefix)
    self.manifestProject = mp

    # This is a bit hacky, but we're in a chicken & egg situation: all the
    # normal repo settings live in the manifestProject which we just setup
    # above, so we couldn't easily query before that.  We assume Project()
    # init doesn't care if this changes afterwards.
    if os.path.exists(mp.gitdir) and mp.use_worktree:
      mp.use_git_worktrees = True

    self.Unload()

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

    self._load_local_manifests = load_local_manifests
    self._outer_client.manifestFileOverrides[self.path_prefix] = path
    self.Unload()
    self._Load()

  def Link(self, name):
    """Update the repo metadata to use a different manifest.
    """
    self.Override(name)

    # Old versions of repo would generate symlinks we need to clean up.
    platform_utils.remove(self.manifestFile, missing_ok=True)
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

    for a in r.annotations:
      if a.keep == 'true':
        ae = doc.createElement('annotation')
        ae.setAttribute('name', a.name)
        ae.setAttribute('value', a.value)
        e.appendChild(ae)

  def _SubmanifestToXml(self, r, doc, root):
    """Generate XML <submanifest/> node."""
    e = doc.createElement('submanifest')
    root.appendChild(e)
    e.setAttribute('name', r.name)
    if r.remote is not None:
      e.setAttribute('remote', r.remote)
    if r.project is not None:
      e.setAttribute('project', r.project)
    if r.manifestName is not None:
      e.setAttribute('manifest-name', r.manifestName)
    if r.revision is not None:
      e.setAttribute('revision', r.revision)
    if r.path is not None:
      e.setAttribute('path', r.path)
    if r.groups:
      e.setAttribute('groups', r.GetGroupsStr())
    if r.default_groups:
      e.setAttribute('default-groups', r.GetDefaultGroupsStr())

    for a in r.annotations:
      if a.keep == 'true':
        ae = doc.createElement('annotation')
        ae.setAttribute('name', a.name)
        ae.setAttribute('value', a.value)
        e.appendChild(ae)

  def _ParseList(self, field):
    """Parse fields that contain flattened lists.

    These are whitespace & comma separated.  Empty elements will be discarded.
    """
    return [x for x in re.split(r'[,\s]+', field) if x]

  def ToXml(self, peg_rev=False, peg_rev_upstream=True,
            peg_rev_dest_branch=True, groups=None, omit_local=False):
    """Return the current manifest XML."""
    mp = self.manifestProject

    if groups is None:
      groups = mp.manifest_groups
    if groups:
      groups = self._ParseList(groups)

    doc = xml.dom.minidom.Document()
    root = doc.createElement('manifest')
    if self.is_submanifest:
      root.setAttribute('path', self.path_prefix)
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
    if d.sync_j is not None:
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

    for r in sorted(self.submanifests):
      self._SubmanifestToXml(self.submanifests[r], doc, root)
    if self.submanifests:
      root.appendChild(doc.createTextNode(''))

    def output_projects(parent, parent_node, projects):
      for project_name in projects:
        for project in self._projects[project_name]:
          output_project(parent, parent_node, project)

    def output_project(parent, parent_node, p):
      if not p.MatchesGroups(groups):
        return

      if omit_local and self.IsFromLocalManifest(p):
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

        if peg_rev_dest_branch:
          if p.dest_branch:
            e.setAttribute('dest-branch', p.dest_branch)
          elif value != p.revisionExpr:
            e.setAttribute('dest-branch', p.revisionExpr)

      else:
        revision = self.remotes[p.remote.orig_name].revision or d.revisionExpr
        if not revision or revision != p.revisionExpr:
          e.setAttribute('revision', p.revisionExpr)
        elif p.revisionId:
          e.setAttribute('revision', p.revisionId)
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

    if self._superproject:
      root.appendChild(doc.createTextNode(''))
      e = doc.createElement('superproject')
      e.setAttribute('name', self._superproject.name)
      remoteName = None
      if d.remote:
        remoteName = d.remote.name
      remote = self._superproject.remote
      if not d.remote or remote.orig_name != remoteName:
        remoteName = remote.orig_name
        e.setAttribute('remote', remoteName)
      revision = remote.revision or d.revisionExpr
      if not revision or revision != self._superproject.revision:
        e.setAttribute('revision', self._superproject.revision)
      root.appendChild(e)

    if self._contactinfo.bugurl != Wrapper().BUG_URL:
      root.appendChild(doc.createTextNode(''))
      e = doc.createElement('contactinfo')
      e.setAttribute('bugurl', self._contactinfo.bugurl)
      root.appendChild(e)

    return doc

  def ToDict(self, **kwargs):
    """Return the current manifest as a dictionary."""
    # Elements that may only appear once.
    SINGLE_ELEMENTS = {
        'notice',
        'default',
        'manifest-server',
        'repo-hooks',
        'superproject',
        'contactinfo',
    }
    # Elements that may be repeated.
    MULTI_ELEMENTS = {
        'remote',
        'remove-project',
        'project',
        'extend-project',
        'include',
        'submanifest',
        # These are children of 'project' nodes.
        'annotation',
        'project',
        'copyfile',
        'linkfile',
    }

    doc = self.ToXml(**kwargs)
    ret = {}

    def append_children(ret, node):
      for child in node.childNodes:
        if child.nodeType == xml.dom.Node.ELEMENT_NODE:
          attrs = child.attributes
          element = dict((attrs.item(i).localName, attrs.item(i).value)
                         for i in range(attrs.length))
          if child.nodeName in SINGLE_ELEMENTS:
            ret[child.nodeName] = element
          elif child.nodeName in MULTI_ELEMENTS:
            ret.setdefault(child.nodeName, []).append(element)
          else:
            raise ManifestParseError('Unhandled element "%s"' % (child.nodeName,))

          append_children(element, child)

    append_children(ret, doc.firstChild)

    return ret

  def Save(self, fd, **kwargs):
    """Write the current manifest out to the given file descriptor."""
    doc = self.ToXml(**kwargs)
    doc.writexml(fd, '', '  ', '\n', 'UTF-8')

  def _output_manifest_project_extras(self, p, e):
    """Manifests can modify e if they support extra project attributes."""

  @property
  def is_multimanifest(self):
    """Whether this is a multimanifest checkout.

    This is safe to use as long as the outermost manifest XML has been parsed.
    """
    return bool(self._outer_client._submanifests)

  @property
  def is_submanifest(self):
    """Whether this manifest is a submanifest.

    This is safe to use as long as the outermost manifest XML has been parsed.
    """
    return self._outer_client and self._outer_client != self

  @property
  def outer_client(self):
    """The instance of the outermost manifest client."""
    self._Load()
    return self._outer_client

  @property
  def all_manifests(self):
    """Generator yielding all (sub)manifests, in depth-first order."""
    self._Load()
    outer = self._outer_client
    yield outer
    for tree in outer.all_children:
      yield tree

  @property
  def all_children(self):
    """Generator yielding all (present) child submanifests."""
    self._Load()
    for child in self._submanifests.values():
      if child.repo_client:
        yield child.repo_client
        for tree in child.repo_client.all_children:
          yield tree

  @property
  def path_prefix(self):
    """The path of this submanifest, relative to the outermost manifest."""
    if not self._outer_client or self == self._outer_client:
      return ''
    return os.path.relpath(self.topdir, self._outer_client.topdir)

  @property
  def all_paths(self):
    """All project paths for all (sub)manifests.

    See also `paths`.

    Returns:
      A dictionary of {path: Project()}.  `path` is relative to the outer
      manifest.
    """
    ret = {}
    for tree in self.all_manifests:
      prefix = tree.path_prefix
      ret.update({os.path.join(prefix, k): v for k, v in tree.paths.items()})
    return ret

  @property
  def all_projects(self):
    """All projects for all (sub)manifests.  See `projects`."""
    return list(itertools.chain.from_iterable(x._paths.values() for x in self.all_manifests))

  @property
  def paths(self):
    """Return all paths for this manifest.

    Returns:
      A dictionary of {path: Project()}.  `path` is relative to this manifest.
    """
    self._Load()
    return self._paths

  @property
  def projects(self):
    """Return a list of all Projects in this manifest."""
    self._Load()
    return list(self._paths.values())

  @property
  def remotes(self):
    """Return a list of remotes for this manifest."""
    self._Load()
    return self._remotes

  @property
  def default(self):
    """Return default values for this manifest."""
    self._Load()
    return self._default

  @property
  def submanifests(self):
    """All submanifests in this manifest."""
    self._Load()
    return self._submanifests

  @property
  def repo_hooks_project(self):
    self._Load()
    return self._repo_hooks_project

  @property
  def superproject(self):
    self._Load()
    return self._superproject

  @property
  def contactinfo(self):
    self._Load()
    return self._contactinfo

  @property
  def notice(self):
    self._Load()
    return self._notice

  @property
  def manifest_server(self):
    self._Load()
    return self._manifest_server

  @property
  def CloneBundle(self):
    clone_bundle = self.manifestProject.clone_bundle
    if clone_bundle is None:
      return False if self.manifestProject.partial_clone else True
    else:
      return clone_bundle

  @property
  def CloneFilter(self):
    if self.manifestProject.partial_clone:
      return self.manifestProject.clone_filter
    return None

  @property
  def PartialCloneExclude(self):
    exclude = self.manifest.manifestProject.partial_clone_exclude or ''
    return set(x.strip() for x in exclude.split(','))

  def SetManifestOverride(self, path):
    """Override manifestFile.  The caller must call Unload()"""
    self._outer_client.manifest.manifestFileOverrides[self.path_prefix] = path

  @property
  def UseLocalManifests(self):
    return self._load_local_manifests

  def SetUseLocalManifests(self, value):
    self._load_local_manifests = value

  @property
  def HasLocalManifests(self):
    return self._load_local_manifests and self.local_manifests

  def IsFromLocalManifest(self, project):
    """Is the project from a local manifest?"""
    return any(x.startswith(LOCAL_MANIFEST_GROUP_PREFIX)
               for x in project.groups)

  @property
  def IsMirror(self):
    return self.manifestProject.mirror

  @property
  def UseGitWorktrees(self):
    return self.manifestProject.use_worktree

  @property
  def IsArchive(self):
    return self.manifestProject.archive

  @property
  def HasSubmodules(self):
    return self.manifestProject.submodules

  @property
  def EnableGitLfs(self):
    return self.manifestProject.git_lfs

  def FindManifestByPath(self, path):
    """Returns the manifest containing path."""
    path = os.path.abspath(path)
    manifest = self._outer_client or self
    old = None
    while manifest._submanifests and manifest != old:
      old = manifest
      for name in manifest._submanifests:
        tree = manifest._submanifests[name]
        if path.startswith(tree.repo_client.manifest.topdir):
          manifest = tree.repo_client
          break
    return manifest

  @property
  def subdir(self):
    """Returns the path for per-submanifest objects for this manifest."""
    return self.SubmanifestInfoDir(self.path_prefix)

  def SubmanifestInfoDir(self, submanifest_path, object_path=''):
    """Return the path to submanifest-specific info for a submanifest.

    Return the full path of the directory in which to put per-manifest objects.

    Args:
      submanifest_path: a string, the path of the submanifest, relative to the
                        outermost topdir.  If empty, then repodir is returned.
      object_path: a string, relative path to append to the submanifest info
                   directory path.
    """
    if submanifest_path:
      return os.path.join(self.repodir, SUBMANIFEST_DIR, submanifest_path,
                          object_path)
    else:
      return os.path.join(self.repodir, object_path)

  def SubmanifestProject(self, submanifest_path):
    """Return a manifestProject for a submanifest."""
    subdir = self.SubmanifestInfoDir(submanifest_path)
    mp = ManifestProject(self, 'manifests',
                         gitdir=os.path.join(subdir, 'manifests.git'),
                         worktree=os.path.join(subdir, 'manifests'))
    return mp

  def GetDefaultGroupsStr(self, with_platform=True):
    """Returns the default group string to use.

    Args:
      with_platform: a boolean, whether to include the group for the
                     underlying platform.
    """
    groups = ','.join(self.default_groups or ['default'])
    if with_platform:
      groups += f',platform-{platform.system().lower()}'
    return groups

  def GetGroupsStr(self):
    """Returns the manifest group string that should be synced."""
    return self.manifestProject.manifest_groups or self.GetDefaultGroupsStr()

  def Unload(self):
    """Unload the manifest.

    If the manifest files have been changed since Load() was called, this will
    cause the new/updated manifest to be used.

    """
    self._loaded = False
    self._projects = {}
    self._paths = {}
    self._remotes = {}
    self._default = None
    self._submanifests = {}
    self._repo_hooks_project = None
    self._superproject = None
    self._contactinfo = ContactInfo(Wrapper().BUG_URL)
    self._notice = None
    self.branch = None
    self._manifest_server = None

  def Load(self):
    """Read the manifest into memory."""
    # Do not expose internal arguments.
    self._Load()

  def _Load(self, initial_client=None, submanifest_depth=0):
    if submanifest_depth > MAX_SUBMANIFEST_DEPTH:
      raise ManifestParseError('maximum submanifest depth %d exceeded.' %
                               MAX_SUBMANIFEST_DEPTH)
    if not self._loaded:
      if self._outer_client and self._outer_client != self:
        # This will load all clients.
        self._outer_client._Load(initial_client=self)

      savedManifestFile = self.manifestFile
      override = self._outer_client.manifestFileOverrides.get(self.path_prefix)
      if override:
        self.manifestFile = override

      try:
        m = self.manifestProject
        b = m.GetBranch(m.CurrentBranch).merge
        if b is not None and b.startswith(R_HEADS):
          b = b[len(R_HEADS):]
        self.branch = b

        parent_groups = self.parent_groups
        if self.path_prefix:
          parent_groups = f'{SUBMANIFEST_GROUP_PREFIX}:path:{self.path_prefix},{parent_groups}'

        # The manifestFile was specified by the user which is why we allow include
        # paths to point anywhere.
        nodes = []
        nodes.append(self._ParseManifestXml(
            self.manifestFile, self.manifestProject.worktree,
            parent_groups=parent_groups, restrict_includes=False))

        if self._load_local_manifests and self.local_manifests:
          try:
            for local_file in sorted(platform_utils.listdir(self.local_manifests)):
              if local_file.endswith('.xml'):
                local = os.path.join(self.local_manifests, local_file)
                # Since local manifests are entirely managed by the user, allow
                # them to point anywhere the user wants.
                local_group = f'{LOCAL_MANIFEST_GROUP_PREFIX}:{local_file[:-4]}'
                nodes.append(self._ParseManifestXml(
                    local, self.subdir,
                    parent_groups=f'{local_group},{parent_groups}',
                    restrict_includes=False))
          except OSError:
            pass

        try:
          self._ParseManifest(nodes)
        except ManifestParseError as e:
          # There was a problem parsing, unload ourselves in case they catch
          # this error and try again later, we will show the correct error
          self.Unload()
          raise e

        if self.IsMirror:
          self._AddMetaProjectMirror(self.repoProject)
          self._AddMetaProjectMirror(self.manifestProject)

        self._loaded = True
      finally:
        if override:
          self.manifestFile = savedManifestFile

      # Now that we have loaded this manifest, load any submanifests as well.
      # We need to do this after self._loaded is set to avoid looping.
      for name in self._submanifests:
        tree = self._submanifests[name]
        spec = tree.ToSubmanifestSpec()
        present = os.path.exists(os.path.join(self.subdir, MANIFEST_FILE_NAME))
        if present and tree.present and not tree.repo_client:
          if initial_client and initial_client.topdir == self.topdir:
            tree.repo_client = self
            tree.present = present
          elif not os.path.exists(self.subdir):
            tree.present = False
        if present and tree.present:
          tree.repo_client._Load(initial_client=initial_client,
                                 submanifest_depth=submanifest_depth + 1)

  def _ParseManifestXml(self, path, include_root, parent_groups='',
                        restrict_includes=True):
    """Parse a manifest XML and return the computed nodes.

    Args:
      path: The XML file to read & parse.
      include_root: The path to interpret include "name"s relative to.
      parent_groups: The groups to apply to this projects.
      restrict_includes: Whether to constrain the "name" attribute of includes.

    Returns:
      List of XML nodes.
    """
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
        if restrict_includes:
          msg = self._CheckLocalPath(name)
          if msg:
            raise ManifestInvalidPathError(
                '<include> invalid "name": %s: %s' % (name, msg))
        include_groups = ''
        if parent_groups:
          include_groups = parent_groups
        if node.hasAttribute('groups'):
          include_groups = node.getAttribute('groups') + ',' + include_groups
        fp = os.path.join(include_root, name)
        if not os.path.isfile(fp):
          raise ManifestParseError("include [%s/]%s doesn't exist or isn't a file"
                                   % (include_root, name))
        try:
          nodes.extend(self._ParseManifestXml(fp, include_root, include_groups))
        # should isolate this to the exact exception, but that's
        # tricky.  actual parsing implementation may vary.
        except (KeyboardInterrupt, RuntimeError, SystemExit, ManifestParseError):
          raise
        except Exception as e:
          raise ManifestParseError(
              "failed parsing included manifest %s: %s" % (name, e))
      else:
        if parent_groups and node.nodeName == 'project':
          nodeGroups = parent_groups
          if node.hasAttribute('groups'):
            nodeGroups = node.getAttribute('groups') + ',' + nodeGroups
          node.setAttribute('groups', nodeGroups)
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
        emptyDefault = not node.hasAttributes() and not node.hasChildNodes()
        if self._default is None:
          self._default = new_default
        elif not emptyDefault and new_default != self._default:
          raise ManifestParseError('duplicate default in %s' %
                                   (self.manifestFile))

    if self._default is None:
      self._default = _Default()

    submanifest_paths = set()
    for node in itertools.chain(*node_list):
      if node.nodeName == 'submanifest':
        submanifest = self._ParseSubmanifest(node)
        if submanifest:
          if submanifest.name in self._submanifests:
            if submanifest != self._submanifests[submanifest.name]:
              raise ManifestParseError(
                  'submanifest %s already exists with different attributes' %
                  (submanifest.name))
          else:
            self._submanifests[submanifest.name] = submanifest
            submanifest_paths.add(submanifest.relpath)

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
      for tree in submanifest_paths:
        if project.relpath.startswith(tree):
          raise ManifestParseError(
              'project %s conflicts with submanifest path %s' %
              (project.relpath, tree))
      self._paths[project.relpath] = project
      projects.append(project)
      for subproject in project.subprojects:
        recursively_add_projects(subproject)

    repo_hooks_project = None
    enabled_repo_hooks = None
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
        dest_path = node.getAttribute('dest-path')
        groups = node.getAttribute('groups')
        if groups:
          groups = self._ParseList(groups)
        revision = node.getAttribute('revision')
        remote_name = node.getAttribute('remote')
        if not remote_name:
          remote = self._default.remote
        else:
          remote = self._get_remote(node)
        dest_branch = node.getAttribute('dest-branch')
        upstream = node.getAttribute('upstream')

        named_projects = self._projects[name]
        if dest_path and not path and len(named_projects) > 1:
          raise ManifestParseError('extend-project cannot use dest-path when '
                                   'matching multiple projects: %s' % name)
        for p in self._projects[name]:
          if path and p.relpath != path:
            continue
          if groups:
            p.groups.extend(groups)
          if revision:
            p.SetRevision(revision)

          if remote_name:
            p.remote = remote.ToRemoteSpec(name)
          if dest_branch:
            p.dest_branch = dest_branch
          if upstream:
            p.upstream = upstream

          if dest_path:
            del self._paths[p.relpath]
            relpath, worktree, gitdir, objdir, _ = self.GetProjectPaths(
                name, dest_path, remote.name)
            p.UpdatePaths(relpath, worktree, gitdir, objdir)
            self._paths[p.relpath] = p

      if node.nodeName == 'repo-hooks':
        # Only one project can be the hooks project
        if repo_hooks_project is not None:
          raise ManifestParseError(
              'duplicate repo-hooks in %s' %
              (self.manifestFile))

        # Get the name of the project and the (space-separated) list of enabled.
        repo_hooks_project = self._reqatt(node, 'in-project')
        enabled_repo_hooks = self._ParseList(self._reqatt(node, 'enabled-list'))
      if node.nodeName == 'superproject':
        name = self._reqatt(node, 'name')
        # There can only be one superproject.
        if self._superproject:
          raise ManifestParseError(
              'duplicate superproject in %s' %
              (self.manifestFile))
        remote_name = node.getAttribute('remote')
        if not remote_name:
          remote = self._default.remote
        else:
          remote = self._get_remote(node)
        if remote is None:
          raise ManifestParseError("no remote for superproject %s within %s" %
                                   (name, self.manifestFile))
        revision = node.getAttribute('revision') or remote.revision
        if not revision:
          revision = self._default.revisionExpr
        if not revision:
          raise ManifestParseError('no revision for superproject %s within %s' %
                                   (name, self.manifestFile))
        self._superproject = Superproject(self,
                                          name=name,
                                          remote=remote.ToRemoteSpec(name),
                                          revision=revision)
      if node.nodeName == 'contactinfo':
        bugurl = self._reqatt(node, 'bugurl')
        # This element can be repeated, later entries will clobber earlier ones.
        self._contactinfo = ContactInfo(bugurl)

      if node.nodeName == 'remove-project':
        name = self._reqatt(node, 'name')

        if name in self._projects:
          for p in self._projects[name]:
            del self._paths[p.relpath]
          del self._projects[name]

          # If the manifest removes the hooks project, treat it as if it deleted
          # the repo-hooks element too.
          if repo_hooks_project == name:
            repo_hooks_project = None
        elif not XmlBool(node, 'optional', False):
          raise ManifestParseError('remove-project element specifies non-existent '
                                   'project: %s' % name)

    # Store repo hooks project information.
    if repo_hooks_project:
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

  def _AddMetaProjectMirror(self, m):
    name = None
    m_url = m.GetRemote().url
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

    remote = _XmlRemote(name, alias, fetch, pushUrl, manifestUrl, review, revision)

    for n in node.childNodes:
      if n.nodeName == 'annotation':
        self._ParseAnnotation(remote, n)

    return remote

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

    d.sync_j = XmlInt(node, 'sync-j', None)
    if d.sync_j is not None and d.sync_j <= 0:
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

  def _ParseSubmanifest(self, node):
    """Reads a <submanifest> element from the manifest file."""
    name = self._reqatt(node, 'name')
    remote = node.getAttribute('remote')
    if remote == '':
      remote = None
    project = node.getAttribute('project')
    if project == '':
      project = None
    revision = node.getAttribute('revision')
    if revision == '':
      revision = None
    manifestName = node.getAttribute('manifest-name')
    if manifestName == '':
      manifestName = None
    groups = ''
    if node.hasAttribute('groups'):
      groups = node.getAttribute('groups')
    groups = self._ParseList(groups)
    default_groups = self._ParseList(node.getAttribute('default-groups'))
    path = node.getAttribute('path')
    if path == '':
      path = None
      if revision:
        msg = self._CheckLocalPath(revision.split('/')[-1])
        if msg:
          raise ManifestInvalidPathError(
              '<submanifest> invalid "revision": %s: %s' % (revision, msg))
      else:
        msg = self._CheckLocalPath(name)
        if msg:
          raise ManifestInvalidPathError(
              '<submanifest> invalid "name": %s: %s' % (name, msg))
    else:
      msg = self._CheckLocalPath(path)
      if msg:
        raise ManifestInvalidPathError(
            '<submanifest> invalid "path": %s: %s' % (path, msg))

    submanifest = _XmlSubmanifest(name, remote, project, revision, manifestName,
                                  groups, default_groups, path, self)

    for n in node.childNodes:
      if n.nodeName == 'annotation':
        self._ParseAnnotation(submanifest, n)

    return submanifest

  def _JoinName(self, parent_name, name):
    return os.path.join(parent_name, name)

  def _UnjoinName(self, parent_name, name):
    return os.path.relpath(name, parent_name)

  def _ParseProject(self, node, parent=None, **extra_proj_attrs):
    """
    reads a <project> element from the manifest file
    """
    name = self._reqatt(node, 'name')
    msg = self._CheckLocalPath(name, dir_ok=True)
    if msg:
      raise ManifestInvalidPathError(
          '<project> invalid "name": %s: %s' % (name, msg))
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
    else:
      # NB: The "." project is handled specially in Project.Sync_LocalHalf.
      msg = self._CheckLocalPath(path, dir_ok=True, cwd_dot_ok=True)
      if msg:
        raise ManifestInvalidPathError(
            '<project> invalid "path": %s: %s' % (path, msg))

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
    groups = self._ParseList(groups)

    if parent is None:
      relpath, worktree, gitdir, objdir, use_git_worktrees = \
          self.GetProjectPaths(name, path, remote.name)
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

  def GetProjectPaths(self, name, path, remote):
    """Return the paths for a project.

    Args:
      name: a string, the name of the project.
      path: a string, the path of the project.
      remote: a string, the remote.name of the project.

    Returns:
      A tuple of (relpath, worktree, gitdir, objdir, use_git_worktrees) for the
      project with |name| and |path|.
    """
    # The manifest entries might have trailing slashes.  Normalize them to avoid
    # unexpected filesystem behavior since we do string concatenation below.
    path = path.rstrip('/')
    name = name.rstrip('/')
    remote = remote.rstrip('/')
    use_git_worktrees = False
    use_remote_name = self.is_multimanifest
    relpath = path
    if self.IsMirror:
      worktree = None
      gitdir = os.path.join(self.topdir, '%s.git' % name)
      objdir = gitdir
    else:
      if use_remote_name:
        namepath = os.path.join(remote, f'{name}.git')
      else:
        namepath = f'{name}.git'
      worktree = os.path.join(self.topdir, path).replace('\\', '/')
      gitdir = os.path.join(self.subdir, 'projects', '%s.git' % path)
      # We allow people to mix git worktrees & non-git worktrees for now.
      # This allows for in situ migration of repo clients.
      if os.path.exists(gitdir) or not self.UseGitWorktrees:
        objdir = os.path.join(self.repodir, 'project-objects', namepath)
      else:
        use_git_worktrees = True
        gitdir = os.path.join(self.repodir, 'worktrees', namepath)
        objdir = gitdir
    return relpath, worktree, gitdir, objdir, use_git_worktrees

  def GetProjectsWithName(self, name, all_manifests=False):
    """All projects with |name|.

    Args:
      name: a string, the name of the project.
      all_manifests: a boolean, if True, then all manifests are searched. If
                     False, then only this manifest is searched.

    Returns:
      A list of Project instances with name |name|.
    """
    if all_manifests:
      return list(itertools.chain.from_iterable(
          x._projects.get(name, []) for x in self.all_manifests))
    return self._projects.get(name, [])

  def GetSubprojectName(self, parent, submodule_path):
    return os.path.join(parent.name, submodule_path)

  def _JoinRelpath(self, parent_relpath, relpath):
    return os.path.join(parent_relpath, relpath)

  def _UnjoinRelpath(self, parent_relpath, relpath):
    return os.path.relpath(relpath, parent_relpath)

  def GetSubprojectPaths(self, parent, name, path):
    # The manifest entries might have trailing slashes.  Normalize them to avoid
    # unexpected filesystem behavior since we do string concatenation below.
    path = path.rstrip('/')
    name = name.rstrip('/')
    relpath = self._JoinRelpath(parent.relpath, path)
    gitdir = os.path.join(parent.gitdir, 'subprojects', '%s.git' % path)
    objdir = os.path.join(parent.gitdir, 'subproject-objects', '%s.git' % name)
    if self.IsMirror:
      worktree = None
    else:
      worktree = os.path.join(parent.worktree, path).replace('\\', '/')
    return relpath, worktree, gitdir, objdir

  @staticmethod
  def _CheckLocalPath(path, dir_ok=False, cwd_dot_ok=False):
    """Verify |path| is reasonable for use in filesystem paths.

    Used with <copyfile> & <linkfile> & <project> elements.

    This only validates the |path| in isolation: it does not check against the
    current filesystem state.  Thus it is suitable as a first-past in a parser.

    It enforces a number of constraints:
    * No empty paths.
    * No "~" in paths.
    * No Unicode codepoints that filesystems might elide when normalizing.
    * No relative path components like "." or "..".
    * No absolute paths.
    * No ".git" or ".repo*" path components.

    Args:
      path: The path name to validate.
      dir_ok: Whether |path| may force a directory (e.g. end in a /).
      cwd_dot_ok: Whether |path| may be just ".".

    Returns:
      None if |path| is OK, a failure message otherwise.
    """
    if not path:
      return 'empty paths not allowed'

    if '~' in path:
      return '~ not allowed (due to 8.3 filenames on Windows filesystems)'

    path_codepoints = set(path)

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
    if BAD_CODEPOINTS & path_codepoints:
      # This message is more expansive than reality, but should be fine.
      return 'Unicode combining characters not allowed'

    # Reject newlines as there shouldn't be any legitmate use for them, they'll
    # be confusing to users, and they can easily break tools that expect to be
    # able to iterate over newline delimited lists.  This even applies to our
    # own code like .repo/project.list.
    if {'\r', '\n'} & path_codepoints:
      return 'Newlines not allowed'

    # Assume paths might be used on case-insensitive filesystems.
    path = path.lower()

    # Split up the path by its components.  We can't use os.path.sep exclusively
    # as some platforms (like Windows) will convert / to \ and that bypasses all
    # our constructed logic here.  Especially since manifest authors only use
    # / in their paths.
    resep = re.compile(r'[/%s]' % re.escape(os.path.sep))
    # Strip off trailing slashes as those only produce '' elements, and we use
    # parts to look for individual bad components.
    parts = resep.split(path.rstrip('/'))

    # Some people use src="." to create stable links to projects.  Lets allow
    # that but reject all other uses of "." to keep things simple.
    if not cwd_dot_ok or parts != ['.']:
      for part in set(parts):
        if part in {'.', '..', '.git'} or part.startswith('.repo'):
          return 'bad component: %s' % (part,)

    if not dir_ok and resep.match(path[-1]):
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
    is_linkfile = element == 'linkfile'
    msg = cls._CheckLocalPath(src, dir_ok=is_linkfile, cwd_dot_ok=is_linkfile)
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

  def _ParseAnnotation(self, element, node):
    name = self._reqatt(node, 'name')
    value = self._reqatt(node, 'value')
    try:
      keep = self._reqatt(node, 'keep').lower()
    except ManifestParseError:
      keep = "true"
    if keep != "true" and keep != "false":
      raise ManifestParseError('optional "keep" attribute must be '
                               '"true" or "false"')
    element.AddAnnotation(name, value, keep)

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

    diff = {'added': [], 'removed': [], 'missing': [], 'changed': [], 'unreachable': []}

    for proj in fromKeys:
      if proj not in toKeys:
        diff['removed'].append(fromProjects[proj])
      elif not fromProjects[proj].Exists:
        diff['missing'].append(toProjects[proj])
        toKeys.remove(proj)
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
  """Parser for GitC (git-in-the-cloud) manifests."""

  def _ParseProject(self, node, parent=None):
    """Override _ParseProject and add support for GITC specific attributes."""
    return super()._ParseProject(
        node, parent=parent, old_revision=node.getAttribute('old-revision'))

  def _output_manifest_project_extras(self, p, e):
    """Output GITC Specific Project attributes"""
    if p.old_revision:
      e.setAttribute('old-revision', str(p.old_revision))


class RepoClient(XmlManifest):
  """Manages a repo client checkout."""

  def __init__(self, repodir, manifest_file=None, submanifest_path='', **kwargs):
    """Initialize.

    Args:
      repodir: Path to the .repo/ dir for holding all internal checkout state.
          It must be in the top directory of the repo client checkout.
      manifest_file: Full path to the manifest file to parse.  This will usually
          be |repodir|/|MANIFEST_FILE_NAME|.
      submanifest_path: The submanifest root relative to the repo root.
      **kwargs: Additional keyword arguments, passed to XmlManifest.
    """
    self.isGitcClient = False
    submanifest_path = submanifest_path or ''
    if submanifest_path:
      self._CheckLocalPath(submanifest_path)
      prefix = os.path.join(repodir, SUBMANIFEST_DIR, submanifest_path)
    else:
      prefix = repodir

    if os.path.exists(os.path.join(prefix, LOCAL_MANIFEST_NAME)):
      print('error: %s is not supported; put local manifests in `%s` instead' %
            (LOCAL_MANIFEST_NAME, os.path.join(prefix, LOCAL_MANIFESTS_DIR_NAME)),
            file=sys.stderr)
      sys.exit(1)

    if manifest_file is None:
        manifest_file = os.path.join(prefix, MANIFEST_FILE_NAME)
    local_manifests = os.path.abspath(os.path.join(prefix, LOCAL_MANIFESTS_DIR_NAME))
    super().__init__(repodir, manifest_file, local_manifests,
                     submanifest_path=submanifest_path, **kwargs)

    # TODO: Completely separate manifest logic out of the client.
    self.manifest = self


class GitcClient(RepoClient, GitcManifest):
  """Manages a GitC client checkout."""

  def __init__(self, repodir, gitc_client_name):
    """Initialize the GitcManifest object."""
    self.gitc_client_name = gitc_client_name
    self.gitc_client_dir = os.path.join(gitc_utils.get_gitc_manifest_dir(),
                                        gitc_client_name)

    super().__init__(repodir, os.path.join(self.gitc_client_dir, '.manifest'))
    self.isGitcClient = True
