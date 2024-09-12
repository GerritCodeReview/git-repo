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
import glob
import os
import platform
import random
import re
import shutil
import stat
import string
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import List, NamedTuple
import urllib.parse

from color import Coloring
from error import DownloadError
from error import GitError
from error import ManifestInvalidPathError
from error import ManifestInvalidRevisionError
from error import ManifestParseError
from error import NoManifestException
from error import RepoError
from error import UploadError
import fetch
from git_command import git_require
from git_command import GitCommand
from git_config import GetSchemeFromUrl
from git_config import GetUrlCookieFile
from git_config import GitConfig
from git_config import IsId
from git_refs import GitRefs
from git_refs import HEAD
from git_refs import R_HEADS
from git_refs import R_M
from git_refs import R_PUB
from git_refs import R_TAGS
from git_refs import R_WORKTREE_M
import git_superproject
from git_trace2_event_log import EventLog
import platform_utils
import progress
from repo_logging import RepoLogger
from repo_trace import Trace


logger = RepoLogger(__file__)


class SyncNetworkHalfResult(NamedTuple):
    """Sync_NetworkHalf return value."""

    # Did we query the remote? False when optimized_fetch is True and we have
    # the commit already present.
    remote_fetched: bool
    # Error from SyncNetworkHalf
    error: Exception = None

    @property
    def success(self) -> bool:
        return not self.error


class SyncNetworkHalfError(RepoError):
    """Failure trying to sync."""


class DeleteWorktreeError(RepoError):
    """Failure to delete worktree."""

    def __init__(
        self, *args, aggregate_errors: List[Exception] = None, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.aggregate_errors = aggregate_errors or []


class DeleteDirtyWorktreeError(DeleteWorktreeError):
    """Failure to delete worktree due to uncommitted changes."""


# Maximum sleep time allowed during retries.
MAXIMUM_RETRY_SLEEP_SEC = 3600.0
# +-10% random jitter is added to each Fetches retry sleep duration.
RETRY_JITTER_PERCENT = 0.1

# Whether to use alternates.  Switching back and forth is *NOT* supported.
# TODO(vapier): Remove knob once behavior is verified.
_ALTERNATES = os.environ.get("REPO_USE_ALTERNATES") == "1"


def _lwrite(path, content):
    lock = "%s.lock" % path

    # Maintain Unix line endings on all OS's to match git behavior.
    with open(lock, "w", newline="\n") as fd:
        fd.write(content)

    try:
        platform_utils.rename(lock, path)
    except OSError:
        platform_utils.remove(lock)
        raise


def not_rev(r):
    return "^" + r


def sq(r):
    return "'" + r.replace("'", "'''") + "'"


_project_hook_list = None


def _ProjectHooks():
    """List the hooks present in the 'hooks' directory.

    These hooks are project hooks and are copied to the '.git/hooks' directory
    of all subprojects.

    This function caches the list of hooks (based on the contents of the
    'repo/hooks' directory) on the first call.

    Returns:
        A list of absolute paths to all of the files in the hooks directory.
    """
    global _project_hook_list
    if _project_hook_list is None:
        d = os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
        d = os.path.join(d, "hooks")
        _project_hook_list = [
            os.path.join(d, x) for x in platform_utils.listdir(d)
        ]
    return _project_hook_list


class DownloadedChange:
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
                "--abbrev=8",
                "--abbrev-commit",
                "--pretty=oneline",
                "--reverse",
                "--date-order",
                not_rev(self.base),
                self.commit,
                "--",
            )
        return self._commit_cache


class ReviewableBranch:
    _commit_cache = None
    _base_exists = None

    def __init__(self, project, branch, base):
        self.project = project
        self.branch = branch
        self.base = base

    @property
    def name(self):
        return self.branch.name

    @property
    def commits(self):
        if self._commit_cache is None:
            args = (
                "--abbrev=8",
                "--abbrev-commit",
                "--pretty=oneline",
                "--reverse",
                "--date-order",
                not_rev(self.base),
                R_HEADS + self.name,
                "--",
            )
            try:
                self._commit_cache = self.project.bare_git.rev_list(
                    *args, log_as_error=self.base_exists
                )
            except GitError:
                # We weren't able to probe the commits for this branch.  Was it
                # tracking a branch that no longer exists?  If so, return no
                # commits.  Otherwise, rethrow the error as we don't know what's
                # going on.
                if self.base_exists:
                    raise

                self._commit_cache = []

        return self._commit_cache

    @property
    def unabbrev_commits(self):
        r = dict()
        for commit in self.project.bare_git.rev_list(
            not_rev(self.base), R_HEADS + self.name, "--"
        ):
            r[commit[0:8]] = commit
        return r

    @property
    def date(self):
        return self.project.bare_git.log(
            "--pretty=format:%cd", "-n", "1", R_HEADS + self.name, "--"
        )

    @property
    def base_exists(self):
        """Whether the branch we're tracking exists.

        Normally it should, but sometimes branches we track can get deleted.
        """
        if self._base_exists is None:
            try:
                self.project.bare_git.rev_parse("--verify", not_rev(self.base))
                # If we're still here, the base branch exists.
                self._base_exists = True
            except GitError:
                # If we failed to verify, the base branch doesn't exist.
                self._base_exists = False

        return self._base_exists

    def UploadForReview(
        self,
        people,
        dryrun=False,
        topic=None,
        hashtags=(),
        labels=(),
        private=False,
        notify=None,
        wip=False,
        ready=False,
        dest_branch=None,
        validate_certs=True,
        push_options=None,
        patchset_description=None,
    ):
        self.project.UploadForReview(
            branch=self.name,
            people=people,
            dryrun=dryrun,
            topic=topic,
            hashtags=hashtags,
            labels=labels,
            private=private,
            notify=notify,
            wip=wip,
            ready=ready,
            dest_branch=dest_branch,
            validate_certs=validate_certs,
            push_options=push_options,
            patchset_description=patchset_description,
        )

    def GetPublishedRefs(self):
        refs = {}
        output = self.project.bare_git.ls_remote(
            self.branch.remote.SshReviewUrl(self.project.UserEmail),
            "refs/changes/*",
        )
        for line in output.split("\n"):
            try:
                (sha, ref) = line.split()
                refs[sha] = ref
            except ValueError:
                pass

        return refs


class StatusColoring(Coloring):
    def __init__(self, config):
        super().__init__(config, "status")
        self.project = self.printer("header", attr="bold")
        self.branch = self.printer("header", attr="bold")
        self.nobranch = self.printer("nobranch", fg="red")
        self.important = self.printer("important", fg="red")

        self.added = self.printer("added", fg="green")
        self.changed = self.printer("changed", fg="red")
        self.untracked = self.printer("untracked", fg="red")


class DiffColoring(Coloring):
    def __init__(self, config):
        super().__init__(config, "diff")
        self.project = self.printer("header", attr="bold")
        self.fail = self.printer("fail", fg="red")


class Annotation:
    def __init__(self, name, value, keep):
        self.name = name
        self.value = value
        self.keep = keep

    def __eq__(self, other):
        if not isinstance(other, Annotation):
            return False
        return self.__dict__ == other.__dict__

    def __lt__(self, other):
        # This exists just so that lists of Annotation objects can be sorted,
        # for use in comparisons.
        if not isinstance(other, Annotation):
            raise ValueError("comparison is not between two Annotation objects")
        if self.name == other.name:
            if self.value == other.value:
                return self.keep < other.keep
            return self.value < other.value
        return self.name < other.name


def _SafeExpandPath(base, subpath, skipfinal=False):
    """Make sure |subpath| is completely safe under |base|.

    We make sure no intermediate symlinks are traversed, and that the final path
    is not a special file (e.g. not a socket or fifo).

    NB: We rely on a number of paths already being filtered out while parsing
    the manifest.  See the validation logic in manifest_xml.py for more details.
    """
    # Split up the path by its components.  We can't use os.path.sep exclusively
    # as some platforms (like Windows) will convert / to \ and that bypasses all
    # our constructed logic here.  Especially since manifest authors only use
    # / in their paths.
    resep = re.compile(r"[/%s]" % re.escape(os.path.sep))
    components = resep.split(subpath)
    if skipfinal:
        # Whether the caller handles the final component itself.
        finalpart = components.pop()

    path = base
    for part in components:
        if part in {".", ".."}:
            raise ManifestInvalidPathError(
                f'{subpath}: "{part}" not allowed in paths'
            )

        path = os.path.join(path, part)
        if platform_utils.islink(path):
            raise ManifestInvalidPathError(
                f"{path}: traversing symlinks not allow"
            )

        if os.path.exists(path):
            if not os.path.isfile(path) and not platform_utils.isdir(path):
                raise ManifestInvalidPathError(
                    f"{path}: only regular files & directories allowed"
                )

    if skipfinal:
        path = os.path.join(path, finalpart)

    return path


class _CopyFile:
    """Container for <copyfile> manifest element."""

    def __init__(self, git_worktree, src, topdir, dest):
        """Register a <copyfile> request.

        Args:
            git_worktree: Absolute path to the git project checkout.
            src: Relative path under |git_worktree| of file to read.
            topdir: Absolute path to the top of the repo client checkout.
            dest: Relative path under |topdir| of file to write.
        """
        self.git_worktree = git_worktree
        self.topdir = topdir
        self.src = src
        self.dest = dest

    def _Copy(self):
        src = _SafeExpandPath(self.git_worktree, self.src)
        dest = _SafeExpandPath(self.topdir, self.dest)

        if platform_utils.isdir(src):
            raise ManifestInvalidPathError(
                f"{self.src}: copying from directory not supported"
            )
        if platform_utils.isdir(dest):
            raise ManifestInvalidPathError(
                f"{self.dest}: copying to directory not allowed"
            )

        # Copy file if it does not exist or is out of date.
        if not os.path.exists(dest) or not filecmp.cmp(src, dest):
            try:
                # Remove existing file first, since it might be read-only.
                if os.path.exists(dest):
                    platform_utils.remove(dest)
                else:
                    dest_dir = os.path.dirname(dest)
                    if not platform_utils.isdir(dest_dir):
                        os.makedirs(dest_dir)
                shutil.copy(src, dest)
                # Make the file read-only.
                mode = os.stat(dest)[stat.ST_MODE]
                mode = mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
                os.chmod(dest, mode)
            except OSError:
                logger.error("error: Cannot copy file %s to %s", src, dest)


class _LinkFile:
    """Container for <linkfile> manifest element."""

    def __init__(self, git_worktree, src, topdir, dest):
        """Register a <linkfile> request.

        Args:
            git_worktree: Absolute path to the git project checkout.
            src: Target of symlink relative to path under |git_worktree|.
            topdir: Absolute path to the top of the repo client checkout.
            dest: Relative path under |topdir| of symlink to create.
        """
        self.git_worktree = git_worktree
        self.topdir = topdir
        self.src = src
        self.dest = dest

    def __linkIt(self, relSrc, absDest):
        # Link file if it does not exist or is out of date.
        if not platform_utils.islink(absDest) or (
            platform_utils.readlink(absDest) != relSrc
        ):
            try:
                # Remove existing file first, since it might be read-only.
                if os.path.lexists(absDest):
                    platform_utils.remove(absDest)
                else:
                    dest_dir = os.path.dirname(absDest)
                    if not platform_utils.isdir(dest_dir):
                        os.makedirs(dest_dir)
                platform_utils.symlink(relSrc, absDest)
            except OSError:
                logger.error(
                    "error: Cannot link file %s to %s", relSrc, absDest
                )

    def _Link(self):
        """Link the self.src & self.dest paths.

        Handles wild cards on the src linking all of the files in the source in
        to the destination directory.
        """
        # Some people use src="." to create stable links to projects.  Let's
        # allow that but reject all other uses of "." to keep things simple.
        if self.src == ".":
            src = self.git_worktree
        else:
            src = _SafeExpandPath(self.git_worktree, self.src)

        if not glob.has_magic(src):
            # Entity does not contain a wild card so just a simple one to one
            # link operation.
            dest = _SafeExpandPath(self.topdir, self.dest, skipfinal=True)
            # dest & src are absolute paths at this point.  Make sure the target
            # of the symlink is relative in the context of the repo client
            # checkout.
            relpath = os.path.relpath(src, os.path.dirname(dest))
            self.__linkIt(relpath, dest)
        else:
            dest = _SafeExpandPath(self.topdir, self.dest)
            # Entity contains a wild card.
            if os.path.exists(dest) and not platform_utils.isdir(dest):
                logger.error(
                    "Link error: src with wildcard, %s must be a directory",
                    dest,
                )
            else:
                for absSrcFile in glob.glob(src):
                    # Create a releative path from source dir to destination
                    # dir.
                    absSrcDir = os.path.dirname(absSrcFile)
                    relSrcDir = os.path.relpath(absSrcDir, dest)

                    # Get the source file name.
                    srcFile = os.path.basename(absSrcFile)

                    # Now form the final full paths to srcFile. They will be
                    # absolute for the desintaiton and relative for the source.
                    absDest = os.path.join(dest, srcFile)
                    relSrc = os.path.join(relSrcDir, srcFile)
                    self.__linkIt(relSrc, absDest)


class RemoteSpec:
    def __init__(
        self,
        name,
        url=None,
        pushUrl=None,
        review=None,
        revision=None,
        orig_name=None,
        fetchUrl=None,
    ):
        self.name = name
        self.url = url
        self.pushUrl = pushUrl
        self.review = review
        self.revision = revision
        self.orig_name = orig_name
        self.fetchUrl = fetchUrl


class Project:
    # These objects can be shared between several working trees.
    @property
    def shareable_dirs(self):
        """Return the shareable directories"""
        if self.UseAlternates:
            return ["hooks", "rr-cache"]
        else:
            return ["hooks", "objects", "rr-cache"]

    def __init__(
        self,
        manifest,
        name,
        remote,
        gitdir,
        objdir,
        worktree,
        relpath,
        revisionExpr,
        revisionId,
        rebase=True,
        groups=None,
        sync_c=False,
        sync_s=False,
        sync_tags=True,
        clone_depth=None,
        upstream=None,
        parent=None,
        use_git_worktrees=False,
        is_derived=False,
        dest_branch=None,
        optimized_fetch=False,
        retry_fetches=0,
        old_revision=None,
    ):
        """Init a Project object.

        Args:
            manifest: The XmlManifest object.
            name: The `name` attribute of manifest.xml's project element.
            remote: RemoteSpec object specifying its remote's properties.
            gitdir: Absolute path of git directory.
            objdir: Absolute path of directory to store git objects.
            worktree: Absolute path of git working tree.
            relpath: Relative path of git working tree to repo's top directory.
            revisionExpr: The `revision` attribute of manifest.xml's project
                element.
            revisionId: git commit id for checking out.
            rebase: The `rebase` attribute of manifest.xml's project element.
            groups: The `groups` attribute of manifest.xml's project element.
            sync_c: The `sync-c` attribute of manifest.xml's project element.
            sync_s: The `sync-s` attribute of manifest.xml's project element.
            sync_tags: The `sync-tags` attribute of manifest.xml's project
                element.
            upstream: The `upstream` attribute of manifest.xml's project
                element.
            parent: The parent Project object.
            use_git_worktrees: Whether to use `git worktree` for this project.
            is_derived: False if the project was explicitly defined in the
                manifest; True if the project is a discovered submodule.
            dest_branch: The branch to which to push changes for review by
                default.
            optimized_fetch: If True, when a project is set to a sha1 revision,
                only fetch from the remote if the sha1 is not present locally.
            retry_fetches: Retry remote fetches n times upon receiving transient
                error with exponential backoff and jitter.
            old_revision: saved git commit id for open GITC projects.
        """
        self.client = self.manifest = manifest
        self.name = name
        self.remote = remote
        self.UpdatePaths(relpath, worktree, gitdir, objdir)
        self.SetRevision(revisionExpr, revisionId=revisionId)

        self.rebase = rebase
        self.groups = groups
        self.sync_c = sync_c
        self.sync_s = sync_s
        self.sync_tags = sync_tags
        self.clone_depth = clone_depth
        self.upstream = upstream
        self.parent = parent
        # NB: Do not use this setting in __init__ to change behavior so that the
        # manifest.git checkout can inspect & change it after instantiating.
        # See the XmlManifest init code for more info.
        self.use_git_worktrees = use_git_worktrees
        self.is_derived = is_derived
        self.optimized_fetch = optimized_fetch
        self.retry_fetches = max(0, retry_fetches)
        self.subprojects = []

        self.snapshots = {}
        self.copyfiles = []
        self.linkfiles = []
        self.annotations = []
        self.dest_branch = dest_branch
        self.old_revision = old_revision

        # This will be filled in if a project is later identified to be the
        # project containing repo hooks.
        self.enabled_repo_hooks = []

    def RelPath(self, local=True):
        """Return the path for the project relative to a manifest.

        Args:
            local: a boolean, if True, the path is relative to the local
                (sub)manifest.  If false, the path is relative to the outermost
                manifest.
        """
        if local:
            return self.relpath
        return os.path.join(self.manifest.path_prefix, self.relpath)

    def SetRevision(self, revisionExpr, revisionId=None):
        """Set revisionId based on revision expression and id"""
        self.revisionExpr = revisionExpr
        if revisionId is None and revisionExpr and IsId(revisionExpr):
            self.revisionId = self.revisionExpr
        else:
            self.revisionId = revisionId

    def UpdatePaths(self, relpath, worktree, gitdir, objdir):
        """Update paths used by this project"""
        self.gitdir = gitdir.replace("\\", "/")
        self.objdir = objdir.replace("\\", "/")
        if worktree:
            self.worktree = os.path.normpath(worktree).replace("\\", "/")
        else:
            self.worktree = None
        self.relpath = relpath

        self.config = GitConfig.ForRepository(
            gitdir=self.gitdir, defaults=self.manifest.globalConfig
        )

        if self.worktree:
            self.work_git = self._GitGetByExec(
                self, bare=False, gitdir=self.gitdir
            )
        else:
            self.work_git = None
        self.bare_git = self._GitGetByExec(self, bare=True, gitdir=self.gitdir)
        self.bare_ref = GitRefs(self.gitdir)
        self.bare_objdir = self._GitGetByExec(
            self, bare=True, gitdir=self.objdir
        )

    @property
    def UseAlternates(self):
        """Whether git alternates are in use.

        This will be removed once migration to alternates is complete.
        """
        return _ALTERNATES or self.manifest.is_multimanifest

    @property
    def Derived(self):
        return self.is_derived

    @property
    def Exists(self):
        return platform_utils.isdir(self.gitdir) and platform_utils.isdir(
            self.objdir
        )

    @property
    def CurrentBranch(self):
        """Obtain the name of the currently checked out branch.

        The branch name omits the 'refs/heads/' prefix.
        None is returned if the project is on a detached HEAD, or if the
        work_git is otheriwse inaccessible (e.g. an incomplete sync).
        """
        try:
            b = self.work_git.GetHead()
        except NoManifestException:
            # If the local checkout is in a bad state, don't barf.  Let the
            # callers process this like the head is unreadable.
            return None
        if b.startswith(R_HEADS):
            return b[len(R_HEADS) :]
        return None

    def IsRebaseInProgress(self):
        """Returns true if a rebase or "am" is in progress"""
        # "rebase-apply" is used for "git rebase".
        # "rebase-merge" is used for "git am".
        return (
            os.path.exists(self.work_git.GetDotgitPath("rebase-apply"))
            or os.path.exists(self.work_git.GetDotgitPath("rebase-merge"))
            or os.path.exists(os.path.join(self.worktree, ".dotest"))
        )

    def IsCherryPickInProgress(self):
        """Returns True if a cherry-pick is in progress."""
        return os.path.exists(self.work_git.GetDotgitPath("CHERRY_PICK_HEAD"))

    def _AbortRebase(self):
        """Abort ongoing rebase, cherry-pick or patch apply (am).

        If no rebase, cherry-pick or patch apply was in progress, this method
        ignores the status and continues.
        """

        def _git(*args):
            # Ignore return code, in case there was no rebase in progress.
            GitCommand(self, args, log_as_error=False).Wait()

        _git("cherry-pick", "--abort")
        _git("rebase", "--abort")
        _git("am", "--abort")

    def IsDirty(self, consider_untracked=True):
        """Is the working directory modified in some way?"""
        self.work_git.update_index(
            "-q", "--unmerged", "--ignore-missing", "--refresh"
        )
        if self.work_git.DiffZ("diff-index", "-M", "--cached", HEAD):
            return True
        if self.work_git.DiffZ("diff-files"):
            return True
        if consider_untracked and self.UntrackedFiles():
            return True
        return False

    _userident_name = None
    _userident_email = None

    @property
    def UserName(self):
        """Obtain the user's personal name."""
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
        u = self.bare_git.var("GIT_COMMITTER_IDENT")
        m = re.compile("^(.*) <([^>]*)> ").match(u)
        if m:
            self._userident_name = m.group(1)
            self._userident_email = m.group(2)
        else:
            self._userident_name = ""
            self._userident_email = ""

    def GetRemote(self, name=None):
        """Get the configuration for a single remote.

        Defaults to the current project's remote.
        """
        if name is None:
            name = self.remote.name
        return self.config.GetRemote(name)

    def GetBranch(self, name):
        """Get the configuration for a single branch."""
        return self.config.GetBranch(name)

    def GetBranches(self):
        """Get all existing local branches."""
        current = self.CurrentBranch
        all_refs = self._allrefs
        heads = {}

        for name, ref_id in all_refs.items():
            if name.startswith(R_HEADS):
                name = name[len(R_HEADS) :]
                b = self.GetBranch(name)
                b.current = name == current
                b.published = None
                b.revision = ref_id
                heads[name] = b

        for name, ref_id in all_refs.items():
            if name.startswith(R_PUB):
                name = name[len(R_PUB) :]
                b = heads.get(name)
                if b:
                    b.published = ref_id

        return heads

    def MatchesGroups(self, manifest_groups):
        """Returns true if the manifest groups specified at init should cause
        this project to be synced.
        Prefixing a manifest group with "-" inverts the meaning of a group.
        All projects are implicitly labelled with "all".

        labels are resolved in order.  In the example case of
        project_groups: "all,group1,group2"
        manifest_groups: "-group1,group2"
        the project will be matched.

        The special manifest group "default" will match any project that
        does not have the special project group "notdefault"
        """
        default_groups = self.manifest.default_groups or ["default"]
        expanded_manifest_groups = manifest_groups or default_groups
        expanded_project_groups = ["all"] + (self.groups or [])
        if "notdefault" not in expanded_project_groups:
            expanded_project_groups += ["default"]

        matched = False
        for group in expanded_manifest_groups:
            if group.startswith("-") and group[1:] in expanded_project_groups:
                matched = False
            elif group in expanded_project_groups:
                matched = True

        return matched

    def UncommitedFiles(self, get_all=True):
        """Returns a list of strings, uncommitted files in the git tree.

        Args:
            get_all: a boolean, if True - get information about all different
                uncommitted files. If False - return as soon as any kind of
                uncommitted files is detected.
        """
        details = []
        self.work_git.update_index(
            "-q", "--unmerged", "--ignore-missing", "--refresh"
        )
        if self.IsRebaseInProgress():
            details.append("rebase in progress")
            if not get_all:
                return details

        changes = self.work_git.DiffZ("diff-index", "--cached", HEAD).keys()
        if changes:
            details.extend(changes)
            if not get_all:
                return details

        changes = self.work_git.DiffZ("diff-files").keys()
        if changes:
            details.extend(changes)
            if not get_all:
                return details

        changes = self.UntrackedFiles()
        if changes:
            details.extend(changes)

        return details

    def UntrackedFiles(self):
        """Returns a list of strings, untracked files in the git tree."""
        return self.work_git.LsOthers()

    def HasChanges(self):
        """Returns true if there are uncommitted changes."""
        return bool(self.UncommitedFiles(get_all=False))

    def PrintWorkTreeStatus(self, output_redir=None, quiet=False, local=False):
        """Prints the status of the repository to stdout.

        Args:
            output_redir: If specified, redirect the output to this object.
            quiet:  If True then only print the project name.  Do not print
                the modified files, branch name, etc.
            local: a boolean, if True, the path is relative to the local
                (sub)manifest.  If false, the path is relative to the outermost
                manifest.
        """
        if not platform_utils.isdir(self.worktree):
            if output_redir is None:
                output_redir = sys.stdout
            print(file=output_redir)
            print("project %s/" % self.RelPath(local), file=output_redir)
            print('  missing (run "repo sync")', file=output_redir)
            return

        self.work_git.update_index(
            "-q", "--unmerged", "--ignore-missing", "--refresh"
        )
        rb = self.IsRebaseInProgress()
        di = self.work_git.DiffZ("diff-index", "-M", "--cached", HEAD)
        df = self.work_git.DiffZ("diff-files")
        do = self.work_git.LsOthers()
        if not rb and not di and not df and not do and not self.CurrentBranch:
            return "CLEAN"

        out = StatusColoring(self.config)
        if output_redir is not None:
            out.redirect(output_redir)
        out.project("project %-40s", self.RelPath(local) + "/ ")

        if quiet:
            out.nl()
            return "DIRTY"

        branch = self.CurrentBranch
        if branch is None:
            out.nobranch("(*** NO BRANCH ***)")
        else:
            out.branch("branch %s", branch)
        out.nl()

        if rb:
            out.important("prior sync failed; rebase still in progress")
            out.nl()

        paths = list()
        paths.extend(di.keys())
        paths.extend(df.keys())
        paths.extend(do)

        for p in sorted(set(paths)):
            try:
                i = di[p]
            except KeyError:
                i = None

            try:
                f = df[p]
            except KeyError:
                f = None

            if i:
                i_status = i.status.upper()
            else:
                i_status = "-"

            if f:
                f_status = f.status.lower()
            else:
                f_status = "-"

            if i and i.src_path:
                line = (
                    f" {i_status}{f_status}\t{i.src_path} => {p} ({i.level}%)"
                )
            else:
                line = f" {i_status}{f_status}\t{p}"

            if i and not f:
                out.added("%s", line)
            elif (i and f) or (not i and f):
                out.changed("%s", line)
            elif not i and not f:
                out.untracked("%s", line)
            else:
                out.write("%s", line)
            out.nl()

        return "DIRTY"

    def PrintWorkTreeDiff(
        self, absolute_paths=False, output_redir=None, local=False
    ):
        """Prints the status of the repository to stdout."""
        out = DiffColoring(self.config)
        if output_redir:
            out.redirect(output_redir)
        cmd = ["diff"]
        if out.is_on:
            cmd.append("--color")
        cmd.append(HEAD)
        if absolute_paths:
            cmd.append("--src-prefix=a/%s/" % self.RelPath(local))
            cmd.append("--dst-prefix=b/%s/" % self.RelPath(local))
        cmd.append("--")
        try:
            p = GitCommand(self, cmd, capture_stdout=True, capture_stderr=True)
            p.Wait()
        except GitError as e:
            out.nl()
            out.project("project %s/" % self.RelPath(local))
            out.nl()
            out.fail("%s", str(e))
            out.nl()
            return False
        if p.stdout:
            out.nl()
            out.project("project %s/" % self.RelPath(local))
            out.nl()
            out.write("%s", p.stdout)
        return p.Wait() == 0

    def WasPublished(self, branch, all_refs=None):
        """Was the branch published (uploaded) for code review?
        If so, returns the SHA-1 hash of the last published
        state for the branch.
        """
        key = R_PUB + branch
        if all_refs is None:
            try:
                return self.bare_git.rev_parse(key)
            except GitError:
                return None
        else:
            try:
                return all_refs[key]
            except KeyError:
                return None

    def CleanPublishedCache(self, all_refs=None):
        """Prunes any stale published refs."""
        if all_refs is None:
            all_refs = self._allrefs
        heads = set()
        canrm = {}
        for name, ref_id in all_refs.items():
            if name.startswith(R_HEADS):
                heads.add(name)
            elif name.startswith(R_PUB):
                canrm[name] = ref_id

        for name, ref_id in canrm.items():
            n = name[len(R_PUB) :]
            if R_HEADS + n not in heads:
                self.bare_git.DeleteRef(name, ref_id)

    def GetUploadableBranches(self, selected_branch=None):
        """List any branches which can be uploaded for review."""
        heads = {}
        pubed = {}

        for name, ref_id in self._allrefs.items():
            if name.startswith(R_HEADS):
                heads[name[len(R_HEADS) :]] = ref_id
            elif name.startswith(R_PUB):
                pubed[name[len(R_PUB) :]] = ref_id

        ready = []
        for branch, ref_id in heads.items():
            if branch in pubed and pubed[branch] == ref_id:
                continue
            if selected_branch and branch != selected_branch:
                continue

            rb = self.GetUploadableBranch(branch)
            if rb:
                ready.append(rb)
        return ready

    def GetUploadableBranch(self, branch_name):
        """Get a single uploadable branch, or None."""
        branch = self.GetBranch(branch_name)
        base = branch.LocalMerge
        if branch.LocalMerge:
            rb = ReviewableBranch(self, branch, base)
            if rb.commits:
                return rb
        return None

    def UploadForReview(
        self,
        branch=None,
        people=([], []),
        dryrun=False,
        topic=None,
        hashtags=(),
        labels=(),
        private=False,
        notify=None,
        wip=False,
        ready=False,
        dest_branch=None,
        validate_certs=True,
        push_options=None,
        patchset_description=None,
    ):
        """Uploads the named branch for code review."""
        if branch is None:
            branch = self.CurrentBranch
        if branch is None:
            raise GitError("not currently on a branch", project=self.name)

        branch = self.GetBranch(branch)
        if not branch.LocalMerge:
            raise GitError(
                "branch %s does not track a remote" % branch.name,
                project=self.name,
            )
        if not branch.remote.review:
            raise GitError(
                "remote %s has no review url" % branch.remote.name,
                project=self.name,
            )

        # Basic validity check on label syntax.
        for label in labels:
            if not re.match(r"^.+[+-][0-9]+$", label):
                raise UploadError(
                    f'invalid label syntax "{label}": labels use forms like '
                    "CodeReview+1 or Verified-1",
                    project=self.name,
                )

        if dest_branch is None:
            dest_branch = self.dest_branch
        if dest_branch is None:
            dest_branch = branch.merge
        if not dest_branch.startswith(R_HEADS):
            dest_branch = R_HEADS + dest_branch

        if not branch.remote.projectname:
            branch.remote.projectname = self.name
            branch.remote.Save()

        url = branch.remote.ReviewUrl(self.UserEmail, validate_certs)
        if url is None:
            raise UploadError("review not configured", project=self.name)
        cmd = ["push", "--progress"]
        if dryrun:
            cmd.append("-n")

        if url.startswith("ssh://"):
            cmd.append("--receive-pack=gerrit receive-pack")

        # This stops git from pushing all reachable annotated tags when
        # push.followTags is configured. Gerrit does not accept any tags
        # pushed to a CL.
        cmd.append("--no-follow-tags")

        for push_option in push_options or []:
            cmd.append("-o")
            cmd.append(push_option)

        cmd.append(url)

        if dest_branch.startswith(R_HEADS):
            dest_branch = dest_branch[len(R_HEADS) :]

        ref_spec = f"{R_HEADS + branch.name}:refs/for/{dest_branch}"
        opts = []
        if topic is not None:
            opts += [f"topic={topic}"]
        opts += ["t=%s" % p for p in hashtags]
        # NB: No need to encode labels as they've been validated above.
        opts += ["l=%s" % p for p in labels]

        opts += ["r=%s" % p for p in people[0]]
        opts += ["cc=%s" % p for p in people[1]]
        if notify:
            opts += ["notify=" + notify]
        if private:
            opts += ["private"]
        if wip:
            opts += ["wip"]
        if ready:
            opts += ["ready"]
        if patchset_description:
            opts += [
                f"m={self._encode_patchset_description(patchset_description)}"
            ]
        if opts:
            ref_spec = ref_spec + "%" + ",".join(opts)
        cmd.append(ref_spec)

        GitCommand(self, cmd, bare=True, verify_command=True).Wait()

        if not dryrun:
            msg = f"posted to {branch.remote.review} for {dest_branch}"
            self.bare_git.UpdateRef(
                R_PUB + branch.name, R_HEADS + branch.name, message=msg
            )

    @staticmethod
    def _encode_patchset_description(original):
        """Applies percent-encoding for strings sent as patchset description.

        The encoding used is based on but stricter than URL encoding (Section
        2.1 of RFC 3986). The only non-escaped characters are alphanumerics, and
        'SPACE' (U+0020) can be represented as 'LOW LINE' (U+005F) or
        'PLUS SIGN' (U+002B).

        For more information, see the Gerrit docs here:
        https://gerrit-review.googlesource.com/Documentation/user-upload.html#patch_set_description
        """
        SAFE = {ord(x) for x in string.ascii_letters + string.digits}

        def _enc(b):
            if b in SAFE:
                return chr(b)
            elif b == ord(" "):
                return "_"
            else:
                return f"%{b:02x}"

        return "".join(_enc(x) for x in original.encode("utf-8"))

    def _ExtractArchive(self, tarpath, path=None):
        """Extract the given tar on its current location

        Args:
            tarpath: The path to the actual tar file

        """
        try:
            with tarfile.open(tarpath, "r") as tar:
                tar.extractall(path=path)
                return True
        except (OSError, tarfile.TarError) as e:
            logger.error("error: Cannot extract archive %s: %s", tarpath, e)
        return False

    def Sync_NetworkHalf(
        self,
        quiet=False,
        verbose=False,
        output_redir=None,
        is_new=None,
        current_branch_only=None,
        force_sync=False,
        clone_bundle=True,
        tags=None,
        archive=False,
        optimized_fetch=False,
        retry_fetches=0,
        prune=False,
        submodules=False,
        ssh_proxy=None,
        clone_filter=None,
        partial_clone_exclude=set(),
        clone_filter_for_depth=None,
    ):
        """Perform only the network IO portion of the sync process.
        Local working directory/branch state is not affected.
        """
        if archive and not isinstance(self, MetaProject):
            if self.remote.url.startswith(("http://", "https://")):
                msg_template = (
                    "%s: Cannot fetch archives from http/https remotes."
                )
                msg_args = self.name
                msg = msg_template % msg_args
                logger.error(msg_template, msg_args)
                return SyncNetworkHalfResult(
                    False, SyncNetworkHalfError(msg, project=self.name)
                )

            name = self.relpath.replace("\\", "/")
            name = name.replace("/", "_")
            tarpath = "%s.tar" % name
            topdir = self.manifest.topdir

            try:
                self._FetchArchive(tarpath, cwd=topdir)
            except GitError as e:
                logger.error("error: %s", e)
                return SyncNetworkHalfResult(False, e)

            # From now on, we only need absolute tarpath.
            tarpath = os.path.join(topdir, tarpath)

            if not self._ExtractArchive(tarpath, path=topdir):
                return SyncNetworkHalfResult(
                    True,
                    SyncNetworkHalfError(
                        f"Unable to Extract Archive {tarpath}",
                        project=self.name,
                    ),
                )
            try:
                platform_utils.remove(tarpath)
            except OSError as e:
                logger.warning("warn: Cannot remove archive %s: %s", tarpath, e)
            self._CopyAndLinkFiles()
            return SyncNetworkHalfResult(True)

        # If the shared object dir already exists, don't try to rebootstrap with
        # a clone bundle download.  We should have the majority of objects
        # already.
        if clone_bundle and os.path.exists(self.objdir):
            clone_bundle = False

        if self.name in partial_clone_exclude:
            clone_bundle = True
            clone_filter = None

        if is_new is None:
            is_new = not self.Exists
        if is_new:
            self._InitGitDir(force_sync=force_sync, quiet=quiet)
        else:
            try:
                # At this point, it's possible that gitdir points to an old
                # objdir (e.g. name changed, but objdir exists). Check
                # references to ensure that's not the case. See
                # https://issues.gerritcodereview.com/40013418 for more
                # details.
                self._CheckDirReference(self.objdir, self.gitdir)

                self._UpdateHooks(quiet=quiet)
            except GitError as e:
                if not force_sync:
                    raise e
                # Let _InitGitDir fix the issue, force_sync is always True here.
                self._InitGitDir(force_sync=True, quiet=quiet)
        self._InitRemote()

        if self.UseAlternates:
            # If gitdir/objects is a symlink, migrate it from the old layout.
            gitdir_objects = os.path.join(self.gitdir, "objects")
            if platform_utils.islink(gitdir_objects):
                platform_utils.remove(gitdir_objects, missing_ok=True)
            gitdir_alt = os.path.join(self.gitdir, "objects/info/alternates")
            if not os.path.exists(gitdir_alt):
                os.makedirs(os.path.dirname(gitdir_alt), exist_ok=True)
                _lwrite(
                    gitdir_alt,
                    os.path.join(
                        os.path.relpath(self.objdir, gitdir_objects), "objects"
                    )
                    + "\n",
                )

        if is_new:
            alt = os.path.join(self.objdir, "objects/info/alternates")
            try:
                with open(alt) as fd:
                    # This works for both absolute and relative alternate
                    # directories.
                    alt_dir = os.path.join(
                        self.objdir, "objects", fd.readline().rstrip()
                    )
            except OSError:
                alt_dir = None
        else:
            alt_dir = None

        if (
            clone_bundle
            and alt_dir is None
            and self._ApplyCloneBundle(
                initial=is_new, quiet=quiet, verbose=verbose
            )
        ):
            is_new = False

        if current_branch_only is None:
            if self.sync_c:
                current_branch_only = True
            elif not self.manifest._loaded:
                # Manifest cannot check defaults until it syncs.
                current_branch_only = False
            elif self.manifest.default.sync_c:
                current_branch_only = True

        if tags is None:
            tags = self.sync_tags

        if self.clone_depth:
            depth = self.clone_depth
        else:
            depth = self.manifest.manifestProject.depth

        if depth and clone_filter_for_depth:
            depth = None
            clone_filter = clone_filter_for_depth

        # See if we can skip the network fetch entirely.
        remote_fetched = False
        if not (
            optimized_fetch
            and IsId(self.revisionExpr)
            and self._CheckForImmutableRevision()
        ):
            remote_fetched = True
            try:
                if not self._RemoteFetch(
                    initial=is_new,
                    quiet=quiet,
                    verbose=verbose,
                    output_redir=output_redir,
                    alt_dir=alt_dir,
                    current_branch_only=current_branch_only,
                    tags=tags,
                    prune=prune,
                    depth=depth,
                    submodules=submodules,
                    force_sync=force_sync,
                    ssh_proxy=ssh_proxy,
                    clone_filter=clone_filter,
                    retry_fetches=retry_fetches,
                ):
                    return SyncNetworkHalfResult(
                        remote_fetched,
                        SyncNetworkHalfError(
                            f"Unable to remote fetch project {self.name}",
                            project=self.name,
                        ),
                    )
            except RepoError as e:
                return SyncNetworkHalfResult(
                    remote_fetched,
                    e,
                )

        mp = self.manifest.manifestProject
        dissociate = mp.dissociate
        if dissociate:
            alternates_file = os.path.join(
                self.objdir, "objects/info/alternates"
            )
            if os.path.exists(alternates_file):
                cmd = ["repack", "-a", "-d"]
                p = GitCommand(
                    self,
                    cmd,
                    bare=True,
                    capture_stdout=bool(output_redir),
                    merge_output=bool(output_redir),
                )
                if p.stdout and output_redir:
                    output_redir.write(p.stdout)
                if p.Wait() != 0:
                    return SyncNetworkHalfResult(
                        remote_fetched,
                        GitError(
                            "Unable to repack alternates", project=self.name
                        ),
                    )
                platform_utils.remove(alternates_file)

        if self.worktree:
            self._InitMRef()
        else:
            self._InitMirrorHead()
            platform_utils.remove(
                os.path.join(self.gitdir, "FETCH_HEAD"), missing_ok=True
            )
        return SyncNetworkHalfResult(remote_fetched)

    def PostRepoUpgrade(self):
        self._InitHooks()

    def _CopyAndLinkFiles(self):
        for copyfile in self.copyfiles:
            copyfile._Copy()
        for linkfile in self.linkfiles:
            linkfile._Link()

    def GetCommitRevisionId(self):
        """Get revisionId of a commit.

        Use this method instead of GetRevisionId to get the id of the commit
        rather than the id of the current git object (for example, a tag)

        """
        if self.revisionId:
            return self.revisionId
        if not self.revisionExpr.startswith(R_TAGS):
            return self.GetRevisionId(self._allrefs)

        try:
            return self.bare_git.rev_list(self.revisionExpr, "-1")[0]
        except GitError:
            raise ManifestInvalidRevisionError(
                f"revision {self.revisionExpr} in {self.name} not found"
            )

    def GetRevisionId(self, all_refs=None):
        if self.revisionId:
            return self.revisionId

        rem = self.GetRemote()
        rev = rem.ToLocal(self.revisionExpr)

        if all_refs is not None and rev in all_refs:
            return all_refs[rev]

        try:
            return self.bare_git.rev_parse("--verify", "%s^0" % rev)
        except GitError:
            raise ManifestInvalidRevisionError(
                f"revision {self.revisionExpr} in {self.name} not found"
            )

    def SetRevisionId(self, revisionId):
        if self.revisionExpr:
            self.upstream = self.revisionExpr

        self.revisionId = revisionId

    def Sync_LocalHalf(
        self,
        syncbuf,
        force_sync=False,
        force_checkout=False,
        force_rebase=False,
        submodules=False,
        errors=None,
        verbose=False,
    ):
        """Perform only the local IO portion of the sync process.

        Network access is not required.
        """
        if errors is None:
            errors = []

        def fail(error: Exception):
            errors.append(error)
            syncbuf.fail(self, error)

        if not os.path.exists(self.gitdir):
            fail(
                LocalSyncFail(
                    "Cannot checkout %s due to missing network sync; Run "
                    "`repo sync -n %s` first." % (self.name, self.name),
                    project=self.name,
                )
            )
            return

        self._InitWorkTree(force_sync=force_sync, submodules=submodules)
        all_refs = self.bare_ref.all
        self.CleanPublishedCache(all_refs)
        revid = self.GetRevisionId(all_refs)

        # Special case the root of the repo client checkout.  Make sure it
        # doesn't contain files being checked out to dirs we don't allow.
        if self.relpath == ".":
            PROTECTED_PATHS = {".repo"}
            paths = set(
                self.work_git.ls_tree("-z", "--name-only", "--", revid).split(
                    "\0"
                )
            )
            bad_paths = paths & PROTECTED_PATHS
            if bad_paths:
                fail(
                    LocalSyncFail(
                        "Refusing to checkout project that writes to protected "
                        "paths: %s" % (", ".join(bad_paths),),
                        project=self.name,
                    )
                )
                return

        def _doff():
            self._FastForward(revid)
            self._CopyAndLinkFiles()

        def _dosubmodules():
            self._SyncSubmodules(quiet=True)

        head = self.work_git.GetHead()
        if head.startswith(R_HEADS):
            branch = head[len(R_HEADS) :]
            try:
                head = all_refs[head]
            except KeyError:
                head = None
        else:
            branch = None

        if branch is None or syncbuf.detach_head:
            # Currently on a detached HEAD.  The user is assumed to
            # not have any local modifications worth worrying about.
            rebase_in_progress = (
                self.IsRebaseInProgress() or self.IsCherryPickInProgress()
            )
            if rebase_in_progress and force_checkout:
                self._AbortRebase()
                rebase_in_progress = (
                    self.IsRebaseInProgress() or self.IsCherryPickInProgress()
                )
            if rebase_in_progress:
                fail(_PriorSyncFailedError(project=self.name))
                return

            if head == revid:
                # No changes; don't do anything further.
                # Except if the head needs to be detached.
                if not syncbuf.detach_head:
                    # The copy/linkfile config may have changed.
                    self._CopyAndLinkFiles()
                    return
            else:
                lost = self._revlist(not_rev(revid), HEAD)
                if lost and verbose:
                    syncbuf.info(self, "discarding %d commits", len(lost))

            try:
                self._Checkout(revid, force_checkout=force_checkout, quiet=True)
                if submodules:
                    self._SyncSubmodules(quiet=True)
            except GitError as e:
                fail(e)
                return
            self._CopyAndLinkFiles()
            return

        if head == revid:
            # No changes; don't do anything further.
            #
            # The copy/linkfile config may have changed.
            self._CopyAndLinkFiles()
            return

        branch = self.GetBranch(branch)

        if not branch.LocalMerge:
            # The current branch has no tracking configuration.
            # Jump off it to a detached HEAD.
            syncbuf.info(
                self, "leaving %s; does not track upstream", branch.name
            )
            try:
                self._Checkout(revid, quiet=True)
                if submodules:
                    self._SyncSubmodules(quiet=True)
            except GitError as e:
                fail(e)
                return
            self._CopyAndLinkFiles()
            return

        upstream_gain = self._revlist(not_rev(HEAD), revid)

        # See if we can perform a fast forward merge.  This can happen if our
        # branch isn't in the exact same state as we last published.
        try:
            self.work_git.merge_base(
                "--is-ancestor", HEAD, revid, log_as_error=False
            )
            # Skip the published logic.
            pub = False
        except GitError:
            pub = self.WasPublished(branch.name, all_refs)

        if pub:
            not_merged = self._revlist(not_rev(revid), pub)
            if not_merged:
                if upstream_gain and not force_rebase:
                    # The user has published this branch and some of those
                    # commits are not yet merged upstream.  We do not want
                    # to rewrite the published commits so we punt.
                    fail(
                        LocalSyncFail(
                            "branch %s is published (but not merged) and is "
                            "now %d commits behind. Fix this manually or rerun "
                            "with the --rebase option to force a rebase."
                            % (branch.name, len(upstream_gain)),
                            project=self.name,
                        )
                    )
                return
            elif pub == head:
                # All published commits are merged, and thus we are a
                # strict subset.  We can fast-forward safely.
                syncbuf.later1(self, _doff, not verbose)
                if submodules:
                    syncbuf.later1(self, _dosubmodules, not verbose)
                return

        # Examine the local commits not in the remote.  Find the
        # last one attributed to this user, if any.
        local_changes = self._revlist(not_rev(revid), HEAD, format="%H %ce")
        last_mine = None
        cnt_mine = 0
        for commit in local_changes:
            commit_id, committer_email = commit.split(" ", 1)
            if committer_email == self.UserEmail:
                last_mine = commit_id
                cnt_mine += 1

        if not upstream_gain and cnt_mine == len(local_changes):
            # The copy/linkfile config may have changed.
            self._CopyAndLinkFiles()
            return

        if self.IsDirty(consider_untracked=False):
            fail(_DirtyError(project=self.name))
            return

        # If the upstream switched on us, warn the user.
        if branch.merge != self.revisionExpr:
            if branch.merge and self.revisionExpr:
                syncbuf.info(
                    self,
                    "manifest switched %s...%s",
                    branch.merge,
                    self.revisionExpr,
                )
            elif branch.merge:
                syncbuf.info(self, "manifest no longer tracks %s", branch.merge)

        if cnt_mine < len(local_changes):
            # Upstream rebased. Not everything in HEAD was created by this user.
            syncbuf.info(
                self,
                "discarding %d commits removed from upstream",
                len(local_changes) - cnt_mine,
            )

        branch.remote = self.GetRemote()
        if not IsId(self.revisionExpr):
            # In case of manifest sync the revisionExpr might be a SHA1.
            branch.merge = self.revisionExpr
            if not branch.merge.startswith("refs/"):
                branch.merge = R_HEADS + branch.merge
        branch.Save()

        if cnt_mine > 0 and self.rebase:

            def _docopyandlink():
                self._CopyAndLinkFiles()

            def _dorebase():
                self._Rebase(upstream="%s^1" % last_mine, onto=revid)

            syncbuf.later2(self, _dorebase, not verbose)
            if submodules:
                syncbuf.later2(self, _dosubmodules, not verbose)
            syncbuf.later2(self, _docopyandlink, not verbose)
        elif local_changes:
            try:
                self._ResetHard(revid)
                if submodules:
                    self._SyncSubmodules(quiet=True)
                self._CopyAndLinkFiles()
            except GitError as e:
                fail(e)
                return
        else:
            syncbuf.later1(self, _doff, not verbose)
            if submodules:
                syncbuf.later1(self, _dosubmodules, not verbose)

    def AddCopyFile(self, src, dest, topdir):
        """Mark |src| for copying to |dest| (relative to |topdir|).

        No filesystem changes occur here.  Actual copying happens later on.

        Paths should have basic validation run on them before being queued.
        Further checking will be handled when the actual copy happens.
        """
        self.copyfiles.append(_CopyFile(self.worktree, src, topdir, dest))

    def AddLinkFile(self, src, dest, topdir):
        """Mark |dest| to create a symlink (relative to |topdir|) pointing to
        |src|.

        No filesystem changes occur here.  Actual linking happens later on.

        Paths should have basic validation run on them before being queued.
        Further checking will be handled when the actual link happens.
        """
        self.linkfiles.append(_LinkFile(self.worktree, src, topdir, dest))

    def AddAnnotation(self, name, value, keep):
        self.annotations.append(Annotation(name, value, keep))

    def DownloadPatchSet(self, change_id, patch_id):
        """Download a single patch set of a single change to FETCH_HEAD."""
        remote = self.GetRemote()

        cmd = ["fetch", remote.name]
        cmd.append(
            "refs/changes/%2.2d/%d/%d" % (change_id % 100, change_id, patch_id)
        )
        GitCommand(self, cmd, bare=True, verify_command=True).Wait()
        return DownloadedChange(
            self,
            self.GetRevisionId(),
            change_id,
            patch_id,
            self.bare_git.rev_parse("FETCH_HEAD"),
        )

    def DeleteWorktree(self, verbose=False, force=False):
        """Delete the source checkout and any other housekeeping tasks.

        This currently leaves behind the internal .repo/ cache state.  This
        helps when switching branches or manifest changes get reverted as we
        don't have to redownload all the git objects.  But we should do some GC
        at some point.

        Args:
            verbose: Whether to show verbose messages.
            force: Always delete tree even if dirty.

        Returns:
            True if the worktree was completely cleaned out.
        """
        if self.IsDirty():
            if force:
                logger.warning(
                    "warning: %s: Removing dirty project: uncommitted changes "
                    "lost.",
                    self.RelPath(local=False),
                )
            else:
                msg = (
                    "error: %s: Cannot remove project: uncommitted "
                    "changes are present.\n" % self.RelPath(local=False)
                )
                logger.error(msg)
                raise DeleteDirtyWorktreeError(msg, project=self.name)

        if verbose:
            print(f"{self.RelPath(local=False)}: Deleting obsolete checkout.")

        # Unlock and delink from the main worktree.  We don't use git's worktree
        # remove because it will recursively delete projects -- we handle that
        # ourselves below.  https://crbug.com/git/48
        if self.use_git_worktrees:
            needle = os.path.realpath(self.gitdir)
            # Find the git worktree commondir under .repo/worktrees/.
            output = self.bare_git.worktree("list", "--porcelain").splitlines()[
                0
            ]
            assert output.startswith("worktree "), output
            commondir = output[9:]
            # Walk each of the git worktrees to see where they point.
            configs = os.path.join(commondir, "worktrees")
            for name in os.listdir(configs):
                gitdir = os.path.join(configs, name, "gitdir")
                with open(gitdir) as fp:
                    relpath = fp.read().strip()
                # Resolve the checkout path and see if it matches this project.
                fullpath = os.path.realpath(
                    os.path.join(configs, name, relpath)
                )
                if fullpath == needle:
                    platform_utils.rmtree(os.path.join(configs, name))

        # Delete the .git directory first, so we're less likely to have a
        # partially working git repository around. There shouldn't be any git
        # projects here, so rmtree works.

        # Try to remove plain files first in case of git worktrees.  If this
        # fails for any reason, we'll fall back to rmtree, and that'll display
        # errors if it can't remove things either.
        try:
            platform_utils.remove(self.gitdir)
        except OSError:
            pass
        try:
            platform_utils.rmtree(self.gitdir)
        except OSError as e:
            if e.errno != errno.ENOENT:
                logger.error("error: %s: %s", self.gitdir, e)
                logger.error(
                    "error: %s: Failed to delete obsolete checkout; remove "
                    "manually, then run `repo sync -l`.",
                    self.RelPath(local=False),
                )
                raise DeleteWorktreeError(aggregate_errors=[e])

        # Delete everything under the worktree, except for directories that
        # contain another git project.
        dirs_to_remove = []
        failed = False
        errors = []
        for root, dirs, files in platform_utils.walk(self.worktree):
            for f in files:
                path = os.path.join(root, f)
                try:
                    platform_utils.remove(path)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        logger.warning("%s: Failed to remove: %s", path, e)
                        failed = True
                        errors.append(e)
            dirs[:] = [
                d
                for d in dirs
                if not os.path.lexists(os.path.join(root, d, ".git"))
            ]
            dirs_to_remove += [
                os.path.join(root, d)
                for d in dirs
                if os.path.join(root, d) not in dirs_to_remove
            ]
        for d in reversed(dirs_to_remove):
            if platform_utils.islink(d):
                try:
                    platform_utils.remove(d)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        logger.warning("%s: Failed to remove: %s", d, e)
                        failed = True
                        errors.append(e)
            elif not platform_utils.listdir(d):
                try:
                    platform_utils.rmdir(d)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        logger.warning("%s: Failed to remove: %s", d, e)
                        failed = True
                        errors.append(e)
        if failed:
            rename_path = (
                f"{self.worktree}_repo_to_be_deleted_{int(time.time())}"
            )
            try:
                platform_utils.rename(self.worktree, rename_path)
                logger.warning(
                    "warning: renamed %s to %s. You can delete it, but you "
                    "might need elevated permissions (e.g. root)",
                    self.worktree,
                    rename_path,
                )
                # Rename successful! Clear the errors.
                errors = []
            except OSError:
                logger.error(
                    "%s: Failed to delete obsolete checkout.\n",
                    "       Remove manually, then run `repo sync -l`.",
                    self.RelPath(local=False),
                )
                raise DeleteWorktreeError(aggregate_errors=errors)

        # Try deleting parent dirs if they are empty.
        path = self.worktree
        while path != self.manifest.topdir:
            try:
                platform_utils.rmdir(path)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    break
            path = os.path.dirname(path)

        return True

    def StartBranch(self, name, branch_merge="", revision=None):
        """Create a new branch off the manifest's revision."""
        if not branch_merge:
            branch_merge = self.revisionExpr
        head = self.work_git.GetHead()
        if head == (R_HEADS + name):
            return True

        all_refs = self.bare_ref.all
        if R_HEADS + name in all_refs:
            GitCommand(
                self, ["checkout", "-q", name, "--"], verify_command=True
            ).Wait()
            return True

        branch = self.GetBranch(name)
        branch.remote = self.GetRemote()
        branch.merge = branch_merge
        if not branch.merge.startswith("refs/") and not IsId(branch_merge):
            branch.merge = R_HEADS + branch_merge

        if revision is None:
            revid = self.GetRevisionId(all_refs)
        else:
            revid = self.work_git.rev_parse(revision)

        if head.startswith(R_HEADS):
            try:
                head = all_refs[head]
            except KeyError:
                head = None
        if revid and head and revid == head:
            ref = R_HEADS + name
            self.work_git.update_ref(ref, revid)
            self.work_git.symbolic_ref(HEAD, ref)
            branch.Save()
            return True

        GitCommand(
            self,
            ["checkout", "-q", "-b", branch.name, revid],
            verify_command=True,
        ).Wait()
        branch.Save()
        return True

    def CheckoutBranch(self, name):
        """Checkout a local topic branch.

        Args:
            name: The name of the branch to checkout.

        Returns:
            True if the checkout succeeded; False if the
            branch doesn't exist.
        """
        rev = R_HEADS + name
        head = self.work_git.GetHead()
        if head == rev:
            # Already on the branch.
            return True

        all_refs = self.bare_ref.all
        try:
            revid = all_refs[rev]
        except KeyError:
            # Branch does not exist in this project.
            return False

        if head.startswith(R_HEADS):
            try:
                head = all_refs[head]
            except KeyError:
                head = None

        if head == revid:
            # Same revision; just update HEAD to point to the new
            # target branch, but otherwise take no other action.
            _lwrite(
                self.work_git.GetDotgitPath(subpath=HEAD),
                f"ref: {R_HEADS}{name}\n",
            )
            return True

        GitCommand(
            self,
            ["checkout", name, "--"],
            capture_stdout=True,
            capture_stderr=True,
            verify_command=True,
        ).Wait()
        return True

    def AbandonBranch(self, name):
        """Destroy a local topic branch.

        Args:
            name: The name of the branch to abandon.

        Returns:
            True if the abandon succeeded; Raises GitCommandError if it didn't;
            None if the branch didn't exist.
        """
        rev = R_HEADS + name
        all_refs = self.bare_ref.all
        if rev not in all_refs:
            # Doesn't exist
            return None

        head = self.work_git.GetHead()
        if head == rev:
            # We can't destroy the branch while we are sitting
            # on it.  Switch to a detached HEAD.
            head = all_refs[head]

            revid = self.GetRevisionId(all_refs)
            if head == revid:
                _lwrite(
                    self.work_git.GetDotgitPath(subpath=HEAD), "%s\n" % revid
                )
            else:
                self._Checkout(revid, quiet=True)
        GitCommand(
            self,
            ["branch", "-D", name],
            capture_stdout=True,
            capture_stderr=True,
            verify_command=True,
        ).Wait()
        return True

    def PruneHeads(self):
        """Prune any topic branches already merged into upstream."""
        cb = self.CurrentBranch
        kill = []
        left = self._allrefs
        for name in left.keys():
            if name.startswith(R_HEADS):
                name = name[len(R_HEADS) :]
                if cb is None or name != cb:
                    kill.append(name)

        # Minor optimization: If there's nothing to prune, then don't try to
        # read any project state.
        if not kill and not cb:
            return []

        rev = self.GetRevisionId(left)
        if (
            cb is not None
            and not self._revlist(HEAD + "..." + rev)
            and not self.IsDirty(consider_untracked=False)
        ):
            self.work_git.DetachHead(HEAD)
            kill.append(cb)

        if kill:
            old = self.bare_git.GetHead()

            try:
                self.bare_git.DetachHead(rev)

                b = ["branch", "-d"]
                b.extend(kill)
                b = GitCommand(
                    self, b, bare=True, capture_stdout=True, capture_stderr=True
                )
                b.Wait()
            finally:
                if IsId(old):
                    self.bare_git.DetachHead(old)
                else:
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
            if R_HEADS + branch in left:
                branch = self.GetBranch(branch)
                base = branch.LocalMerge
                if not base:
                    base = rev
                kept.append(ReviewableBranch(self, branch, base))
        return kept

    def GetRegisteredSubprojects(self):
        result = []

        def rec(subprojects):
            if not subprojects:
                return
            result.extend(subprojects)
            for p in subprojects:
                rec(p.subprojects)

        rec(self.subprojects)
        return result

    def _GetSubmodules(self):
        # Unfortunately we cannot call `git submodule status --recursive` here
        # because the working tree might not exist yet, and it cannot be used
        # without a working tree in its current implementation.

        def get_submodules(gitdir, rev):
            # Parse .gitmodules for submodule sub_paths and sub_urls.
            sub_paths, sub_urls = parse_gitmodules(gitdir, rev)
            if not sub_paths:
                return []
            # Run `git ls-tree` to read SHAs of submodule object, which happen
            # to be revision of submodule repository.
            sub_revs = git_ls_tree(gitdir, rev, sub_paths)
            submodules = []
            for sub_path, sub_url in zip(sub_paths, sub_urls):
                try:
                    sub_rev = sub_revs[sub_path]
                except KeyError:
                    # Ignore non-exist submodules.
                    continue
                submodules.append((sub_rev, sub_path, sub_url))
            return submodules

        re_path = re.compile(r"^submodule\.(.+)\.path=(.*)$")
        re_url = re.compile(r"^submodule\.(.+)\.url=(.*)$")

        def parse_gitmodules(gitdir, rev):
            cmd = ["cat-file", "blob", "%s:.gitmodules" % rev]
            try:
                p = GitCommand(
                    None,
                    cmd,
                    capture_stdout=True,
                    capture_stderr=True,
                    bare=True,
                    gitdir=gitdir,
                )
            except GitError:
                return [], []
            if p.Wait() != 0:
                return [], []

            gitmodules_lines = []
            fd, temp_gitmodules_path = tempfile.mkstemp()
            try:
                os.write(fd, p.stdout.encode("utf-8"))
                os.close(fd)
                cmd = ["config", "--file", temp_gitmodules_path, "--list"]
                p = GitCommand(
                    None,
                    cmd,
                    capture_stdout=True,
                    capture_stderr=True,
                    bare=True,
                    gitdir=gitdir,
                )
                if p.Wait() != 0:
                    return [], []
                gitmodules_lines = p.stdout.split("\n")
            except GitError:
                return [], []
            finally:
                platform_utils.remove(temp_gitmodules_path)

            names = set()
            paths = {}
            urls = {}
            for line in gitmodules_lines:
                if not line:
                    continue
                m = re_path.match(line)
                if m:
                    names.add(m.group(1))
                    paths[m.group(1)] = m.group(2)
                    continue
                m = re_url.match(line)
                if m:
                    names.add(m.group(1))
                    urls[m.group(1)] = m.group(2)
                    continue
            names = sorted(names)
            return (
                [paths.get(name, "") for name in names],
                [urls.get(name, "") for name in names],
            )

        def git_ls_tree(gitdir, rev, paths):
            cmd = ["ls-tree", rev, "--"]
            cmd.extend(paths)
            try:
                p = GitCommand(
                    None,
                    cmd,
                    capture_stdout=True,
                    capture_stderr=True,
                    bare=True,
                    gitdir=gitdir,
                )
            except GitError:
                return []
            if p.Wait() != 0:
                return []
            objects = {}
            for line in p.stdout.split("\n"):
                if not line.strip():
                    continue
                object_rev, object_path = line.split()[2:4]
                objects[object_path] = object_rev
            return objects

        try:
            rev = self.GetRevisionId()
        except GitError:
            return []
        return get_submodules(self.gitdir, rev)

    def GetDerivedSubprojects(self):
        result = []
        if not self.Exists:
            # If git repo does not exist yet, querying its submodules will
            # mess up its states; so return here.
            return result
        for rev, path, url in self._GetSubmodules():
            name = self.manifest.GetSubprojectName(self, path)
            (
                relpath,
                worktree,
                gitdir,
                objdir,
            ) = self.manifest.GetSubprojectPaths(self, name, path)
            project = self.manifest.paths.get(relpath)
            if project:
                result.extend(project.GetDerivedSubprojects())
                continue

            if url.startswith(".."):
                url = urllib.parse.urljoin("%s/" % self.remote.url, url)
            remote = RemoteSpec(
                self.remote.name,
                url=url,
                pushUrl=self.remote.pushUrl,
                review=self.remote.review,
                revision=self.remote.revision,
            )
            subproject = Project(
                manifest=self.manifest,
                name=name,
                remote=remote,
                gitdir=gitdir,
                objdir=objdir,
                worktree=worktree,
                relpath=relpath,
                revisionExpr=rev,
                revisionId=rev,
                rebase=self.rebase,
                groups=self.groups,
                sync_c=self.sync_c,
                sync_s=self.sync_s,
                sync_tags=self.sync_tags,
                parent=self,
                is_derived=True,
            )
            result.append(subproject)
            result.extend(subproject.GetDerivedSubprojects())
        return result

    def EnableRepositoryExtension(self, key, value="true", version=1):
        """Enable git repository extension |key| with |value|.

        Args:
            key: The extension to enabled.  Omit the "extensions." prefix.
            value: The value to use for the extension.
            version: The minimum git repository version needed.
        """
        # Make sure the git repo version is new enough already.
        found_version = self.config.GetInt("core.repositoryFormatVersion")
        if found_version is None:
            found_version = 0
        if found_version < version:
            self.config.SetString("core.repositoryFormatVersion", str(version))

        # Enable the extension!
        self.config.SetString(f"extensions.{key}", value)

    def ResolveRemoteHead(self, name=None):
        """Find out what the default branch (HEAD) points to.

        Normally this points to refs/heads/master, but projects are moving to
        main. Support whatever the server uses rather than hardcoding "master"
        ourselves.
        """
        if name is None:
            name = self.remote.name

        # The output will look like (NB: tabs are separators):
        # ref: refs/heads/master	HEAD
        # 5f6803b100bb3cd0f534e96e88c91373e8ed1c44	HEAD
        output = self.bare_git.ls_remote(
            "-q", "--symref", "--exit-code", name, "HEAD"
        )

        for line in output.splitlines():
            lhs, rhs = line.split("\t", 1)
            if rhs == "HEAD" and lhs.startswith("ref:"):
                return lhs[4:].strip()

        return None

    def _CheckForImmutableRevision(self):
        try:
            # if revision (sha or tag) is not present then following function
            # throws an error.
            self.bare_git.rev_list(
                "-1",
                "--missing=allow-any",
                "%s^0" % self.revisionExpr,
                "--",
                log_as_error=False,
            )
            if self.upstream:
                rev = self.GetRemote().ToLocal(self.upstream)
                self.bare_git.rev_list(
                    "-1",
                    "--missing=allow-any",
                    "%s^0" % rev,
                    "--",
                    log_as_error=False,
                )
                self.bare_git.merge_base(
                    "--is-ancestor",
                    self.revisionExpr,
                    rev,
                    log_as_error=False,
                )
            return True
        except GitError:
            # There is no such persistent revision. We have to fetch it.
            return False

    def _FetchArchive(self, tarpath, cwd=None):
        cmd = ["archive", "-v", "-o", tarpath]
        cmd.append("--remote=%s" % self.remote.url)
        cmd.append("--prefix=%s/" % self.RelPath(local=False))
        cmd.append(self.revisionExpr)

        command = GitCommand(
            self,
            cmd,
            cwd=cwd,
            capture_stdout=True,
            capture_stderr=True,
            verify_command=True,
        )
        command.Wait()

    def _RemoteFetch(
        self,
        name=None,
        current_branch_only=False,
        initial=False,
        quiet=False,
        verbose=False,
        output_redir=None,
        alt_dir=None,
        tags=True,
        prune=False,
        depth=None,
        submodules=False,
        ssh_proxy=None,
        force_sync=False,
        clone_filter=None,
        retry_fetches=2,
        retry_sleep_initial_sec=4.0,
        retry_exp_factor=2.0,
    ) -> bool:
        tag_name = None
        # The depth should not be used when fetching to a mirror because
        # it will result in a shallow repository that cannot be cloned or
        # fetched from.
        # The repo project should also never be synced with partial depth.
        if self.manifest.IsMirror or self.relpath == ".repo/repo":
            depth = None

        if depth:
            current_branch_only = True

        is_sha1 = bool(IsId(self.revisionExpr))

        if current_branch_only:
            if self.revisionExpr.startswith(R_TAGS):
                # This is a tag and its commit id should never change.
                tag_name = self.revisionExpr[len(R_TAGS) :]
            elif self.upstream and self.upstream.startswith(R_TAGS):
                # This is a tag and its commit id should never change.
                tag_name = self.upstream[len(R_TAGS) :]

            if is_sha1 or tag_name is not None:
                if self._CheckForImmutableRevision():
                    if verbose:
                        print(
                            "Skipped fetching project %s (already have "
                            "persistent ref)" % self.name
                        )
                    return True
            if is_sha1 and not depth:
                # When syncing a specific commit and --depth is not set:
                # * if upstream is explicitly specified and is not a sha1, fetch
                #   only upstream as users expect only upstream to be fetch.
                #   Note: The commit might not be in upstream in which case the
                #   sync will fail.
                # * otherwise, fetch all branches to make sure we end up with
                #   the specific commit.
                if self.upstream:
                    current_branch_only = not IsId(self.upstream)
                else:
                    current_branch_only = False

        if not name:
            name = self.remote.name

        remote = self.GetRemote(name)
        if not remote.PreConnectFetch(ssh_proxy):
            ssh_proxy = None

        if initial:
            if alt_dir and "objects" == os.path.basename(alt_dir):
                ref_dir = os.path.dirname(alt_dir)
                packed_refs = os.path.join(self.gitdir, "packed-refs")

                all_refs = self.bare_ref.all
                ids = set(all_refs.values())
                tmp = set()

                for r, ref_id in GitRefs(ref_dir).all.items():
                    if r not in all_refs:
                        if r.startswith(R_TAGS) or remote.WritesTo(r):
                            all_refs[r] = ref_id
                            ids.add(ref_id)
                            continue

                    if ref_id in ids:
                        continue

                    r = "refs/_alt/%s" % ref_id
                    all_refs[r] = ref_id
                    ids.add(ref_id)
                    tmp.add(r)

                tmp_packed_lines = []
                old_packed_lines = []

                for r in sorted(all_refs):
                    line = f"{all_refs[r]} {r}\n"
                    tmp_packed_lines.append(line)
                    if r not in tmp:
                        old_packed_lines.append(line)

                tmp_packed = "".join(tmp_packed_lines)
                old_packed = "".join(old_packed_lines)
                _lwrite(packed_refs, tmp_packed)
            else:
                alt_dir = None

        cmd = ["fetch"]

        if clone_filter:
            git_require((2, 19, 0), fail=True, msg="partial clones")
            cmd.append("--filter=%s" % clone_filter)
            self.EnableRepositoryExtension("partialclone", self.remote.name)

        if depth:
            cmd.append("--depth=%s" % depth)
        else:
            # If this repo has shallow objects, then we don't know which refs
            # have shallow objects or not. Tell git to unshallow all fetched
            # refs.  Don't do this with projects that don't have shallow
            # objects, since it is less efficient.
            if os.path.exists(os.path.join(self.gitdir, "shallow")):
                cmd.append("--depth=2147483647")

        if not verbose:
            cmd.append("--quiet")
        if not quiet and sys.stdout.isatty():
            cmd.append("--progress")
        if not self.worktree:
            cmd.append("--update-head-ok")
        cmd.append(name)

        if force_sync:
            cmd.append("--force")

        if prune:
            cmd.append("--prune")

        # Always pass something for --recurse-submodules, git with GIT_DIR
        # behaves incorrectly when not given `--recurse-submodules=no`.
        # (b/218891912)
        cmd.append(
            f'--recurse-submodules={"on-demand" if submodules else "no"}'
        )

        spec = []
        if not current_branch_only:
            # Fetch whole repo.
            spec.append(
                str(("+refs/heads/*:") + remote.ToLocal("refs/heads/*"))
            )
        elif tag_name is not None:
            spec.append("tag")
            spec.append(tag_name)

        if self.manifest.IsMirror and not current_branch_only:
            branch = None
        else:
            branch = self.revisionExpr
        if not self.manifest.IsMirror and is_sha1 and depth:
            # Shallow checkout of a specific commit, fetch from that commit and
            # not the heads only as the commit might be deeper in the history.
            spec.append(branch)
            if self.upstream:
                spec.append(self.upstream)
        else:
            if is_sha1:
                branch = self.upstream
            if branch is not None and branch.strip():
                if not branch.startswith("refs/"):
                    branch = R_HEADS + branch
                spec.append(str(("+%s:" % branch) + remote.ToLocal(branch)))

        # If mirroring repo and we cannot deduce the tag or branch to fetch,
        # fetch whole repo.
        if self.manifest.IsMirror and not spec:
            spec.append(
                str(("+refs/heads/*:") + remote.ToLocal("refs/heads/*"))
            )

        # If using depth then we should not get all the tags since they may
        # be outside of the depth.
        if not tags or depth:
            cmd.append("--no-tags")
        else:
            cmd.append("--tags")
            spec.append(str(("+refs/tags/*:") + remote.ToLocal("refs/tags/*")))

        cmd.extend(spec)

        # At least one retry minimum due to git remote prune.
        retry_fetches = max(retry_fetches, 2)
        retry_cur_sleep = retry_sleep_initial_sec
        ok = prune_tried = False
        for try_n in range(retry_fetches):
            verify_command = try_n == retry_fetches - 1
            gitcmd = GitCommand(
                self,
                cmd,
                bare=True,
                objdir=os.path.join(self.objdir, "objects"),
                ssh_proxy=ssh_proxy,
                merge_output=True,
                capture_stdout=quiet or bool(output_redir),
                verify_command=verify_command,
            )
            if gitcmd.stdout and not quiet and output_redir:
                output_redir.write(gitcmd.stdout)
            ret = gitcmd.Wait()
            if ret == 0:
                ok = True
                break

            # Retry later due to HTTP 429 Too Many Requests.
            elif (
                gitcmd.stdout
                and "error:" in gitcmd.stdout
                and "HTTP 429" in gitcmd.stdout
            ):
                # Fallthru to sleep+retry logic at the bottom.
                pass

            # TODO(b/360889369#comment24): git may gc commits incorrectly.
            # Until the root cause is fixed, retry fetch with --refetch which
            # will bring the repository into a good state.
            elif gitcmd.stdout and "could not parse commit" in gitcmd.stdout:
                cmd.insert(1, "--refetch")
                print(
                    "could not parse commit error, retrying with refetch",
                    file=output_redir,
                )
                continue

            # Try to prune remote branches once in case there are conflicts.
            # For example, if the remote had refs/heads/upstream, but deleted
            # that and now has refs/heads/upstream/foo.
            elif (
                gitcmd.stdout
                and "error:" in gitcmd.stdout
                and "git remote prune" in gitcmd.stdout
                and not prune_tried
            ):
                prune_tried = True
                prunecmd = GitCommand(
                    self,
                    ["remote", "prune", name],
                    bare=True,
                    ssh_proxy=ssh_proxy,
                )
                ret = prunecmd.Wait()
                if ret:
                    break
                print(
                    "retrying fetch after pruning remote branches",
                    file=output_redir,
                )
                # Continue right away so we don't sleep as we shouldn't need to.
                continue
            elif current_branch_only and is_sha1 and ret == 128:
                # Exit code 128 means "couldn't find the ref you asked for"; if
                # we're in sha1 mode, we just tried sync'ing from the upstream
                # field; it doesn't exist, thus abort the optimization attempt
                # and do a full sync.
                break
            elif ret < 0:
                # Git died with a signal, exit immediately.
                break

            # Figure out how long to sleep before the next attempt, if there is
            # one.
            if not verbose and gitcmd.stdout:
                print(
                    f"\n{self.name}:\n{gitcmd.stdout}",
                    end="",
                    file=output_redir,
                )
            if try_n < retry_fetches - 1:
                print(
                    "%s: sleeping %s seconds before retrying"
                    % (self.name, retry_cur_sleep),
                    file=output_redir,
                )
                time.sleep(retry_cur_sleep)
                retry_cur_sleep = min(
                    retry_exp_factor * retry_cur_sleep, MAXIMUM_RETRY_SLEEP_SEC
                )
                retry_cur_sleep *= 1 - random.uniform(
                    -RETRY_JITTER_PERCENT, RETRY_JITTER_PERCENT
                )

        if initial:
            if alt_dir:
                if old_packed != "":
                    _lwrite(packed_refs, old_packed)
                else:
                    platform_utils.remove(packed_refs)
            self.bare_git.pack_refs("--all", "--prune")

        if is_sha1 and current_branch_only:
            # We just synced the upstream given branch; verify we
            # got what we wanted, else trigger a second run of all
            # refs.
            if not self._CheckForImmutableRevision():
                # Sync the current branch only with depth set to None.
                # We always pass depth=None down to avoid infinite recursion.
                return self._RemoteFetch(
                    name=name,
                    quiet=quiet,
                    verbose=verbose,
                    output_redir=output_redir,
                    current_branch_only=current_branch_only and depth,
                    initial=False,
                    alt_dir=alt_dir,
                    tags=tags,
                    depth=None,
                    ssh_proxy=ssh_proxy,
                    clone_filter=clone_filter,
                )

        return ok

    def _ApplyCloneBundle(self, initial=False, quiet=False, verbose=False):
        if initial and (
            self.manifest.manifestProject.depth or self.clone_depth
        ):
            return False

        remote = self.GetRemote()
        bundle_url = remote.url + "/clone.bundle"
        bundle_url = GitConfig.ForUser().UrlInsteadOf(bundle_url)
        if GetSchemeFromUrl(bundle_url) not in (
            "http",
            "https",
            "persistent-http",
            "persistent-https",
        ):
            return False

        bundle_dst = os.path.join(self.gitdir, "clone.bundle")
        bundle_tmp = os.path.join(self.gitdir, "clone.bundle.tmp")

        exist_dst = os.path.exists(bundle_dst)
        exist_tmp = os.path.exists(bundle_tmp)

        if not initial and not exist_dst and not exist_tmp:
            return False

        if not exist_dst:
            exist_dst = self._FetchBundle(
                bundle_url, bundle_tmp, bundle_dst, quiet, verbose
            )
        if not exist_dst:
            return False

        cmd = ["fetch"]
        if not verbose:
            cmd.append("--quiet")
        if not quiet and sys.stdout.isatty():
            cmd.append("--progress")
        if not self.worktree:
            cmd.append("--update-head-ok")
        cmd.append(bundle_dst)
        for f in remote.fetch:
            cmd.append(str(f))
        cmd.append("+refs/tags/*:refs/tags/*")

        ok = (
            GitCommand(
                self,
                cmd,
                bare=True,
                objdir=os.path.join(self.objdir, "objects"),
            ).Wait()
            == 0
        )
        platform_utils.remove(bundle_dst, missing_ok=True)
        platform_utils.remove(bundle_tmp, missing_ok=True)
        return ok

    def _FetchBundle(self, srcUrl, tmpPath, dstPath, quiet, verbose):
        platform_utils.remove(dstPath, missing_ok=True)

        # We do not use curl's --retry option since it generally doesn't
        # actually retry anything; code 18 for example, it will not retry on.
        cmd = ["curl", "--fail", "--output", tmpPath, "--netrc", "--location"]
        if quiet:
            cmd += ["--silent", "--show-error"]
        if os.path.exists(tmpPath):
            size = os.stat(tmpPath).st_size
            if size >= 1024:
                cmd += ["--continue-at", "%d" % (size,)]
            else:
                platform_utils.remove(tmpPath)
        with GetUrlCookieFile(srcUrl, quiet) as (cookiefile, proxy):
            if cookiefile:
                cmd += ["--cookie", cookiefile]
            if proxy:
                cmd += ["--proxy", proxy]
            elif "http_proxy" in os.environ and "darwin" == sys.platform:
                cmd += ["--proxy", os.environ["http_proxy"]]
            if srcUrl.startswith("persistent-https"):
                srcUrl = "http" + srcUrl[len("persistent-https") :]
            elif srcUrl.startswith("persistent-http"):
                srcUrl = "http" + srcUrl[len("persistent-http") :]
            cmd += [srcUrl]

            proc = None
            with Trace("Fetching bundle: %s", " ".join(cmd)):
                if verbose:
                    print(f"{self.name}: Downloading bundle: {srcUrl}")
                stdout = None if verbose else subprocess.PIPE
                stderr = None if verbose else subprocess.STDOUT
                try:
                    proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                except OSError:
                    return False

            (output, _) = proc.communicate()
            curlret = proc.returncode

            if curlret in (22, 35, 56, 92):
                # We use --fail so curl exits with unique status.
                # From curl man page:
                # 22: HTTP page not retrieved.  The requested url was not found
                #     or returned another error with the HTTP error code being
                #     400 or above.
                # 35: SSL connect error.  The SSL handshaking failed.  This can
                #     be thrown by Google storage sometimes.
                # 56: Failure in receiving network data.  This shows up with
                #     HTTP/404 on Google storage.
                # 92: Stream error in HTTP/2 framing layer.  Basically the same
                #     as 22 -- Google storage sometimes throws 500's.
                if verbose:
                    print(
                        "%s: Unable to retrieve clone.bundle; ignoring."
                        % self.name
                    )
                    if output:
                        print("Curl output:\n%s" % output)
                return False
            elif curlret and not verbose and output:
                logger.error("%s", output)

        if os.path.exists(tmpPath):
            if curlret == 0 and self._IsValidBundle(tmpPath, quiet):
                platform_utils.rename(tmpPath, dstPath)
                return True
            else:
                platform_utils.remove(tmpPath)
                return False
        else:
            return False

    def _IsValidBundle(self, path, quiet):
        try:
            with open(path, "rb") as f:
                if f.read(16) == b"# v2 git bundle\n":
                    return True
                else:
                    if not quiet:
                        logger.error("Invalid clone.bundle file; ignoring.")
                    return False
        except OSError:
            return False

    def _Checkout(self, rev, force_checkout=False, quiet=False):
        cmd = ["checkout"]
        if quiet:
            cmd.append("-q")
        if force_checkout:
            cmd.append("-f")
        cmd.append(rev)
        cmd.append("--")
        if GitCommand(self, cmd).Wait() != 0:
            if self._allrefs:
                raise GitError(
                    f"{self.name} checkout {rev} ", project=self.name
                )

    def _CherryPick(self, rev, ffonly=False, record_origin=False):
        cmd = ["cherry-pick"]
        if ffonly:
            cmd.append("--ff")
        if record_origin:
            cmd.append("-x")
        cmd.append(rev)
        cmd.append("--")
        if GitCommand(self, cmd).Wait() != 0:
            if self._allrefs:
                raise GitError(
                    f"{self.name} cherry-pick {rev} ", project=self.name
                )

    def _LsRemote(self, refs):
        cmd = ["ls-remote", self.remote.name, refs]
        p = GitCommand(self, cmd, capture_stdout=True)
        if p.Wait() == 0:
            return p.stdout
        return None

    def _Revert(self, rev):
        cmd = ["revert"]
        cmd.append("--no-edit")
        cmd.append(rev)
        cmd.append("--")
        if GitCommand(self, cmd).Wait() != 0:
            if self._allrefs:
                raise GitError(f"{self.name} revert {rev} ", project=self.name)

    def _ResetHard(self, rev, quiet=True):
        cmd = ["reset", "--hard"]
        if quiet:
            cmd.append("-q")
        cmd.append(rev)
        if GitCommand(self, cmd).Wait() != 0:
            raise GitError(
                f"{self.name} reset --hard {rev} ", project=self.name
            )

    def _SyncSubmodules(self, quiet=True):
        cmd = ["submodule", "update", "--init", "--recursive"]
        if quiet:
            cmd.append("-q")
        if GitCommand(self, cmd).Wait() != 0:
            raise GitError(
                "%s submodule update --init --recursive " % self.name,
                project=self.name,
            )

    def _Rebase(self, upstream, onto=None):
        cmd = ["rebase"]
        if onto is not None:
            cmd.extend(["--onto", onto])
        cmd.append(upstream)
        if GitCommand(self, cmd).Wait() != 0:
            raise GitError(f"{self.name} rebase {upstream} ", project=self.name)

    def _FastForward(self, head, ffonly=False, quiet=True):
        cmd = ["merge", "--no-stat", head]
        if ffonly:
            cmd.append("--ff-only")
        if quiet:
            cmd.append("-q")
        if GitCommand(self, cmd).Wait() != 0:
            raise GitError(f"{self.name} merge {head} ", project=self.name)

    def _InitGitDir(self, mirror_git=None, force_sync=False, quiet=False):
        init_git_dir = not os.path.exists(self.gitdir)
        init_obj_dir = not os.path.exists(self.objdir)
        try:
            # Initialize the bare repository, which contains all of the objects.
            if init_obj_dir:
                os.makedirs(self.objdir)
                self.bare_objdir.init()

                self._UpdateHooks(quiet=quiet)

                if self.use_git_worktrees:
                    # Enable per-worktree config file support if possible.  This
                    # is more a nice-to-have feature for users rather than a
                    # hard requirement.
                    if git_require((2, 20, 0)):
                        self.EnableRepositoryExtension("worktreeConfig")

            # If we have a separate directory to hold refs, initialize it as
            # well.
            if self.objdir != self.gitdir:
                if init_git_dir:
                    os.makedirs(self.gitdir)

                if init_obj_dir or init_git_dir:
                    self._ReferenceGitDir(
                        self.objdir, self.gitdir, copy_all=True
                    )
                try:
                    self._CheckDirReference(self.objdir, self.gitdir)
                except GitError as e:
                    if force_sync:
                        logger.error(
                            "Retrying clone after deleting %s", self.gitdir
                        )
                        try:
                            platform_utils.rmtree(os.path.realpath(self.gitdir))
                            if self.worktree and os.path.exists(
                                os.path.realpath(self.worktree)
                            ):
                                platform_utils.rmtree(
                                    os.path.realpath(self.worktree)
                                )
                            return self._InitGitDir(
                                mirror_git=mirror_git,
                                force_sync=False,
                                quiet=quiet,
                            )
                        except Exception:
                            raise e
                    raise e

            if init_git_dir:
                mp = self.manifest.manifestProject
                ref_dir = mp.reference or ""

                def _expanded_ref_dirs():
                    """Iterate through possible git reference dir paths."""
                    name = self.name + ".git"
                    yield mirror_git or os.path.join(ref_dir, name)
                    for prefix in "", self.remote.name:
                        yield os.path.join(
                            ref_dir, ".repo", "project-objects", prefix, name
                        )
                        yield os.path.join(
                            ref_dir, ".repo", "worktrees", prefix, name
                        )

                if ref_dir or mirror_git:
                    found_ref_dir = None
                    for path in _expanded_ref_dirs():
                        if os.path.exists(path):
                            found_ref_dir = path
                            break
                    ref_dir = found_ref_dir

                    if ref_dir:
                        if not os.path.isabs(ref_dir):
                            # The alternate directory is relative to the object
                            # database.
                            ref_dir = os.path.relpath(
                                ref_dir, os.path.join(self.objdir, "objects")
                            )
                        _lwrite(
                            os.path.join(
                                self.objdir, "objects/info/alternates"
                            ),
                            os.path.join(ref_dir, "objects") + "\n",
                        )

                m = self.manifest.manifestProject.config
                for key in ["user.name", "user.email"]:
                    if m.Has(key, include_defaults=False):
                        self.config.SetString(key, m.GetString(key))
                if not self.manifest.EnableGitLfs:
                    self.config.SetString(
                        "filter.lfs.smudge", "git-lfs smudge --skip -- %f"
                    )
                    self.config.SetString(
                        "filter.lfs.process", "git-lfs filter-process --skip"
                    )
                self.config.SetBoolean(
                    "core.bare", True if self.manifest.IsMirror else None
                )

            if not init_obj_dir:
                # The project might be shared (obj_dir already initialized), but
                # such information is not available here. Instead of passing it,
                # set it as shared, and rely to be unset down the execution
                # path.
                if git_require((2, 7, 0)):
                    self.EnableRepositoryExtension("preciousObjects")
                else:
                    self.config.SetString("gc.pruneExpire", "never")

        except Exception:
            if init_obj_dir and os.path.exists(self.objdir):
                platform_utils.rmtree(self.objdir)
            if init_git_dir and os.path.exists(self.gitdir):
                platform_utils.rmtree(self.gitdir)
            raise

    def _UpdateHooks(self, quiet=False):
        if os.path.exists(self.objdir):
            self._InitHooks(quiet=quiet)

    def _InitHooks(self, quiet=False):
        hooks = os.path.realpath(os.path.join(self.objdir, "hooks"))
        if not os.path.exists(hooks):
            os.makedirs(hooks)

        # Delete sample hooks.  They're noise.
        for hook in glob.glob(os.path.join(hooks, "*.sample")):
            try:
                platform_utils.remove(hook, missing_ok=True)
            except PermissionError:
                pass

        for stock_hook in _ProjectHooks():
            name = os.path.basename(stock_hook)

            if (
                name in ("commit-msg",)
                and not self.remote.review
                and self is not self.manifest.manifestProject
            ):
                # Don't install a Gerrit Code Review hook if this
                # project does not appear to use it for reviews.
                #
                # Since the manifest project is one of those, but also
                # managed through gerrit, it's excluded.
                continue

            dst = os.path.join(hooks, name)
            if platform_utils.islink(dst):
                continue
            if os.path.exists(dst):
                # If the files are the same, we'll leave it alone.  We create
                # symlinks below by default but fallback to hardlinks if the OS
                # blocks them. So if we're here, it's probably because we made a
                # hardlink below.
                if not filecmp.cmp(stock_hook, dst, shallow=False):
                    if not quiet:
                        logger.warning(
                            "warn: %s: Not replacing locally modified %s hook",
                            self.RelPath(local=False),
                            name,
                        )
                continue
            try:
                platform_utils.symlink(
                    os.path.relpath(stock_hook, os.path.dirname(dst)), dst
                )
            except OSError as e:
                if e.errno == errno.EPERM:
                    try:
                        os.link(stock_hook, dst)
                    except OSError:
                        raise GitError(
                            self._get_symlink_error_message(), project=self.name
                        )
                else:
                    raise

    def _InitRemote(self):
        if self.remote.url:
            remote = self.GetRemote()
            remote.url = self.remote.url
            remote.pushUrl = self.remote.pushUrl
            remote.review = self.remote.review
            remote.projectname = self.name

            if self.worktree:
                remote.ResetFetch(mirror=False)
            else:
                remote.ResetFetch(mirror=True)
            remote.Save()

    def _InitMRef(self):
        """Initialize the pseudo m/<manifest branch> ref."""
        if self.manifest.branch:
            if self.use_git_worktrees:
                # Set up the m/ space to point to the worktree-specific ref
                # space. We'll update the worktree-specific ref space on each
                # checkout.
                ref = R_M + self.manifest.branch
                if not self.bare_ref.symref(ref):
                    self.bare_git.symbolic_ref(
                        "-m",
                        "redirecting to worktree scope",
                        ref,
                        R_WORKTREE_M + self.manifest.branch,
                    )

                # We can't update this ref with git worktrees until it exists.
                # We'll wait until the initial checkout to set it.
                if not os.path.exists(self.worktree):
                    return

                base = R_WORKTREE_M
                active_git = self.work_git

                self._InitAnyMRef(HEAD, self.bare_git, detach=True)
            else:
                base = R_M
                active_git = self.bare_git

            self._InitAnyMRef(base + self.manifest.branch, active_git)

    def _InitMirrorHead(self):
        self._InitAnyMRef(HEAD, self.bare_git)

    def _InitAnyMRef(self, ref, active_git, detach=False):
        """Initialize |ref| in |active_git| to the value in the manifest.

        This points |ref| to the <project> setting in the manifest.

        Args:
            ref: The branch to update.
            active_git: The git repository to make updates in.
            detach: Whether to update target of symbolic refs, or overwrite the
                ref directly (and thus make it non-symbolic).
        """
        cur = self.bare_ref.symref(ref)

        if self.revisionId:
            if cur != "" or self.bare_ref.get(ref) != self.revisionId:
                msg = "manifest set to %s" % self.revisionId
                dst = self.revisionId + "^0"
                active_git.UpdateRef(ref, dst, message=msg, detach=True)
        else:
            remote = self.GetRemote()
            dst = remote.ToLocal(self.revisionExpr)
            if cur != dst:
                msg = "manifest set to %s" % self.revisionExpr
                if detach:
                    active_git.UpdateRef(ref, dst, message=msg, detach=True)
                else:
                    active_git.symbolic_ref("-m", msg, ref, dst)

    def _CheckDirReference(self, srcdir, destdir):
        # Git worktrees don't use symlinks to share at all.
        if self.use_git_worktrees:
            return

        for name in self.shareable_dirs:
            # Try to self-heal a bit in simple cases.
            dst_path = os.path.join(destdir, name)
            src_path = os.path.join(srcdir, name)

            dst = os.path.realpath(dst_path)
            if os.path.lexists(dst):
                src = os.path.realpath(src_path)
                # Fail if the links are pointing to the wrong place.
                if src != dst:
                    logger.error(
                        "error: %s is different in %s vs %s",
                        name,
                        destdir,
                        srcdir,
                    )
                    raise GitError(
                        "--force-sync not enabled; cannot overwrite a local "
                        "work tree. If you're comfortable with the "
                        "possibility of losing the work tree's git metadata,"
                        " use "
                        f"`repo sync --force-sync {self.RelPath(local=False)}` "
                        "to proceed.",
                        project=self.name,
                    )

    def _ReferenceGitDir(self, gitdir, dotgit, copy_all):
        """Update |dotgit| to reference |gitdir|, using symlinks where possible.

        Args:
            gitdir: The bare git repository. Must already be initialized.
            dotgit: The repository you would like to initialize.
            copy_all: If true, copy all remaining files from |gitdir| ->
                |dotgit|. This saves you the effort of initializing |dotgit|
                yourself.
        """
        symlink_dirs = self.shareable_dirs[:]
        to_symlink = symlink_dirs

        to_copy = []
        if copy_all:
            to_copy = platform_utils.listdir(gitdir)

        dotgit = os.path.realpath(dotgit)
        for name in set(to_copy).union(to_symlink):
            try:
                src = os.path.realpath(os.path.join(gitdir, name))
                dst = os.path.join(dotgit, name)

                if os.path.lexists(dst):
                    continue

                # If the source dir doesn't exist, create an empty dir.
                if name in symlink_dirs and not os.path.lexists(src):
                    os.makedirs(src)

                if name in to_symlink:
                    platform_utils.symlink(
                        os.path.relpath(src, os.path.dirname(dst)), dst
                    )
                elif copy_all and not platform_utils.islink(dst):
                    if platform_utils.isdir(src):
                        shutil.copytree(src, dst)
                    elif os.path.isfile(src):
                        shutil.copy(src, dst)

            except OSError as e:
                if e.errno == errno.EPERM:
                    raise DownloadError(self._get_symlink_error_message())
                else:
                    raise

    def _InitGitWorktree(self):
        """Init the project using git worktrees."""
        self.bare_git.worktree("prune")
        self.bare_git.worktree(
            "add",
            "-ff",
            "--checkout",
            "--detach",
            "--lock",
            self.worktree,
            self.GetRevisionId(),
        )

        # Rewrite the internal state files to use relative paths between the
        # checkouts & worktrees.
        dotgit = os.path.join(self.worktree, ".git")
        with open(dotgit) as fp:
            # Figure out the checkout->worktree path.
            setting = fp.read()
            assert setting.startswith("gitdir:")
            git_worktree_path = setting.split(":", 1)[1].strip()
        # Some platforms (e.g. Windows) won't let us update dotgit in situ
        # because of file permissions.  Delete it and recreate it from scratch
        # to avoid.
        platform_utils.remove(dotgit)
        # Use relative path from checkout->worktree & maintain Unix line endings
        # on all OS's to match git behavior.
        with open(dotgit, "w", newline="\n") as fp:
            print(
                "gitdir:",
                os.path.relpath(git_worktree_path, self.worktree),
                file=fp,
            )
        # Use relative path from worktree->checkout & maintain Unix line endings
        # on all OS's to match git behavior.
        with open(
            os.path.join(git_worktree_path, "gitdir"), "w", newline="\n"
        ) as fp:
            print(os.path.relpath(dotgit, git_worktree_path), file=fp)

        self._InitMRef()

    def _InitWorkTree(self, force_sync=False, submodules=False):
        """Setup the worktree .git path.

        This is the user-visible path like src/foo/.git/.

        With non-git-worktrees, this will be a symlink to the .repo/projects/
        path. With git-worktrees, this will be a .git file using "gitdir: ..."
        syntax.

        Older checkouts had .git/ directories.  If we see that, migrate it.

        This also handles changes in the manifest.  Maybe this project was
        backed by "foo/bar" on the server, but now it's "new/foo/bar".  We have
        to update the path we point to under .repo/projects/ to match.
        """
        dotgit = os.path.join(self.worktree, ".git")

        # If using an old layout style (a directory), migrate it.
        if not platform_utils.islink(dotgit) and platform_utils.isdir(dotgit):
            self._MigrateOldWorkTreeGitDir(dotgit, project=self.name)

        init_dotgit = not os.path.lexists(dotgit)
        if self.use_git_worktrees:
            if init_dotgit:
                self._InitGitWorktree()
                self._CopyAndLinkFiles()
        else:
            if not init_dotgit:
                # See if the project has changed.
                if os.path.realpath(self.gitdir) != os.path.realpath(dotgit):
                    platform_utils.remove(dotgit)

            if init_dotgit or not os.path.exists(dotgit):
                os.makedirs(self.worktree, exist_ok=True)
                platform_utils.symlink(
                    os.path.relpath(self.gitdir, self.worktree), dotgit
                )

            if init_dotgit:
                _lwrite(
                    os.path.join(dotgit, HEAD), "%s\n" % self.GetRevisionId()
                )

                # Finish checking out the worktree.
                cmd = ["read-tree", "--reset", "-u", "-v", HEAD]
                if GitCommand(self, cmd).Wait() != 0:
                    raise GitError(
                        "Cannot initialize work tree for " + self.name,
                        project=self.name,
                    )

                if submodules:
                    self._SyncSubmodules(quiet=True)
                self._CopyAndLinkFiles()

    @classmethod
    def _MigrateOldWorkTreeGitDir(cls, dotgit, project=None):
        """Migrate the old worktree .git/ dir style to a symlink.

        This logic specifically only uses state from |dotgit| to figure out
        where to move content and not |self|.  This way if the backing project
        also changed places, we only do the .git/ dir to .git symlink migration
        here.  The path updates will happen independently.
        """
        # Figure out where in .repo/projects/ it's pointing to.
        if not os.path.islink(os.path.join(dotgit, "refs")):
            raise GitError(
                f"{dotgit}: unsupported checkout state", project=project
            )
        gitdir = os.path.dirname(os.path.realpath(os.path.join(dotgit, "refs")))

        # Remove known symlink paths that exist in .repo/projects/.
        KNOWN_LINKS = {
            "config",
            "description",
            "hooks",
            "info",
            "logs",
            "objects",
            "packed-refs",
            "refs",
            "rr-cache",
            "shallow",
            "svn",
        }
        # Paths that we know will be in both, but are safe to clobber in
        # .repo/projects/.
        SAFE_TO_CLOBBER = {
            "COMMIT_EDITMSG",
            "FETCH_HEAD",
            "HEAD",
            "gc.log",
            "gitk.cache",
            "index",
            "ORIG_HEAD",
        }

        # First see if we'd succeed before starting the migration.
        unknown_paths = []
        for name in platform_utils.listdir(dotgit):
            # Ignore all temporary/backup names.  These are common with vim &
            # emacs.
            if name.endswith("~") or (name[0] == "#" and name[-1] == "#"):
                continue

            dotgit_path = os.path.join(dotgit, name)
            if name in KNOWN_LINKS:
                if not platform_utils.islink(dotgit_path):
                    unknown_paths.append(f"{dotgit_path}: should be a symlink")
            else:
                gitdir_path = os.path.join(gitdir, name)
                if name not in SAFE_TO_CLOBBER and os.path.exists(gitdir_path):
                    unknown_paths.append(
                        f"{dotgit_path}: unknown file; please file a bug"
                    )
        if unknown_paths:
            raise GitError(
                "Aborting migration: " + "\n".join(unknown_paths),
                project=project,
            )

        # Now walk the paths and sync the .git/ to .repo/projects/.
        for name in platform_utils.listdir(dotgit):
            dotgit_path = os.path.join(dotgit, name)

            # Ignore all temporary/backup names.  These are common with vim &
            # emacs.
            if name.endswith("~") or (name[0] == "#" and name[-1] == "#"):
                platform_utils.remove(dotgit_path)
            elif name in KNOWN_LINKS:
                platform_utils.remove(dotgit_path)
            else:
                gitdir_path = os.path.join(gitdir, name)
                platform_utils.remove(gitdir_path, missing_ok=True)
                platform_utils.rename(dotgit_path, gitdir_path)

        # Now that the dir should be empty, clear it out, and symlink it over.
        platform_utils.rmdir(dotgit)
        platform_utils.symlink(
            os.path.relpath(gitdir, os.path.dirname(os.path.realpath(dotgit))),
            dotgit,
        )

    def _get_symlink_error_message(self):
        if platform_utils.isWindows():
            return (
                "Unable to create symbolic link. Please re-run the command as "
                "Administrator, or see "
                "https://github.com/git-for-windows/git/wiki/Symbolic-Links "
                "for other options."
            )
        return "filesystem must support symlinks"

    def _revlist(self, *args, **kw):
        a = []
        a.extend(args)
        a.append("--")
        return self.work_git.rev_list(*a, **kw)

    @property
    def _allrefs(self):
        return self.bare_ref.all

    def _getLogs(
        self, rev1, rev2, oneline=False, color=True, pretty_format=None
    ):
        """Get logs between two revisions of this project."""
        comp = ".."
        if rev1:
            revs = [rev1]
            if rev2:
                revs.extend([comp, rev2])
            cmd = ["log", "".join(revs)]
            out = DiffColoring(self.config)
            if out.is_on and color:
                cmd.append("--color")
            if pretty_format is not None:
                cmd.append("--pretty=format:%s" % pretty_format)
            if oneline:
                cmd.append("--oneline")

            try:
                log = GitCommand(
                    self, cmd, capture_stdout=True, capture_stderr=True
                )
                if log.Wait() == 0:
                    return log.stdout
            except GitError:
                # worktree may not exist if groups changed for example. In that
                # case, try in gitdir instead.
                if not os.path.exists(self.worktree):
                    return self.bare_git.log(*cmd[1:])
                else:
                    raise
        return None

    def getAddedAndRemovedLogs(
        self, toProject, oneline=False, color=True, pretty_format=None
    ):
        """Get the list of logs from this revision to given revisionId"""
        logs = {}
        selfId = self.GetRevisionId(self._allrefs)
        toId = toProject.GetRevisionId(toProject._allrefs)

        logs["added"] = self._getLogs(
            selfId,
            toId,
            oneline=oneline,
            color=color,
            pretty_format=pretty_format,
        )
        logs["removed"] = self._getLogs(
            toId,
            selfId,
            oneline=oneline,
            color=color,
            pretty_format=pretty_format,
        )
        return logs

    class _GitGetByExec:
        def __init__(self, project, bare, gitdir):
            self._project = project
            self._bare = bare
            self._gitdir = gitdir

        # __getstate__ and __setstate__ are required for pickling because
        # __getattr__ exists.
        def __getstate__(self):
            return (self._project, self._bare, self._gitdir)

        def __setstate__(self, state):
            self._project, self._bare, self._gitdir = state

        def LsOthers(self):
            p = GitCommand(
                self._project,
                ["ls-files", "-z", "--others", "--exclude-standard"],
                bare=False,
                gitdir=self._gitdir,
                capture_stdout=True,
                capture_stderr=True,
            )
            if p.Wait() == 0:
                out = p.stdout
                if out:
                    # Backslash is not anomalous.
                    return out[:-1].split("\0")
            return []

        def DiffZ(self, name, *args):
            cmd = [name]
            cmd.append("-z")
            cmd.append("--ignore-submodules")
            cmd.extend(args)
            p = GitCommand(
                self._project,
                cmd,
                gitdir=self._gitdir,
                bare=False,
                capture_stdout=True,
                capture_stderr=True,
            )
            p.Wait()
            r = {}
            out = p.stdout
            if out:
                out = iter(out[:-1].split("\0"))
                while out:
                    try:
                        info = next(out)
                        path = next(out)
                    except StopIteration:
                        break

                    class _Info:
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
                                while self.level.startswith("0"):
                                    self.level = self.level[1:]

                    info = info[1:].split(" ")
                    info = _Info(path, *info)
                    if info.status in ("R", "C"):
                        info.src_path = info.path
                        info.path = next(out)
                    r[info.path] = info
            return r

        def GetDotgitPath(self, subpath=None):
            """Return the full path to the .git dir.

            As a convenience, append |subpath| if provided.
            """
            if self._bare:
                dotgit = self._gitdir
            else:
                dotgit = os.path.join(self._project.worktree, ".git")
                if os.path.isfile(dotgit):
                    # Git worktrees use a "gitdir:" syntax to point to the
                    # scratch space.
                    with open(dotgit) as fp:
                        setting = fp.read()
                    assert setting.startswith("gitdir:")
                    gitdir = setting.split(":", 1)[1].strip()
                    dotgit = os.path.normpath(
                        os.path.join(self._project.worktree, gitdir)
                    )

            return dotgit if subpath is None else os.path.join(dotgit, subpath)

        def GetHead(self):
            """Return the ref that HEAD points to."""
            path = self.GetDotgitPath(subpath=HEAD)
            try:
                with open(path) as fd:
                    line = fd.readline()
            except OSError as e:
                raise NoManifestException(path, str(e))
            try:
                line = line.decode()
            except AttributeError:
                pass
            if line.startswith("ref: "):
                return line[5:-1]
            return line[:-1]

        def SetHead(self, ref, message=None):
            cmdv = []
            if message is not None:
                cmdv.extend(["-m", message])
            cmdv.append(HEAD)
            cmdv.append(ref)
            self.symbolic_ref(*cmdv)

        def DetachHead(self, new, message=None):
            cmdv = ["--no-deref"]
            if message is not None:
                cmdv.extend(["-m", message])
            cmdv.append(HEAD)
            cmdv.append(new)
            self.update_ref(*cmdv)

        def UpdateRef(self, name, new, old=None, message=None, detach=False):
            cmdv = []
            if message is not None:
                cmdv.extend(["-m", message])
            if detach:
                cmdv.append("--no-deref")
            cmdv.append(name)
            cmdv.append(new)
            if old is not None:
                cmdv.append(old)
            self.update_ref(*cmdv)

        def DeleteRef(self, name, old=None):
            if not old:
                old = self.rev_parse(name)
            self.update_ref("-d", name, old)
            self._project.bare_ref.deleted(name)

        def rev_list(self, *args, log_as_error=True, **kw):
            if "format" in kw:
                cmdv = ["log", "--pretty=format:%s" % kw["format"]]
            else:
                cmdv = ["rev-list"]
            cmdv.extend(args)
            p = GitCommand(
                self._project,
                cmdv,
                bare=self._bare,
                gitdir=self._gitdir,
                capture_stdout=True,
                capture_stderr=True,
                verify_command=True,
                log_as_error=log_as_error,
            )
            p.Wait()
            return p.stdout.splitlines()

        def __getattr__(self, name):
            """Allow arbitrary git commands using pythonic syntax.

            This allows you to do things like:
                git_obj.rev_parse('HEAD')

            Since we don't have a 'rev_parse' method defined, the __getattr__
            will run.  We'll replace the '_' with a '-' and try to run a git
            command. Any other positional arguments will be passed to the git
            command, and the following keyword arguments are supported:
                config: An optional dict of git config options to be passed with
                    '-c'.

            Args:
                name: The name of the git command to call.  Any '_' characters
                    will be replaced with '-'.

            Returns:
                A callable object that will try to call git with the named
                command.
            """
            name = name.replace("_", "-")

            def runner(*args, log_as_error=True, **kwargs):
                cmdv = []
                config = kwargs.pop("config", None)
                for k in kwargs:
                    raise TypeError(
                        f"{name}() got an unexpected keyword argument {k!r}"
                    )
                if config is not None:
                    for k, v in config.items():
                        cmdv.append("-c")
                        cmdv.append(f"{k}={v}")
                cmdv.append(name)
                cmdv.extend(args)
                p = GitCommand(
                    self._project,
                    cmdv,
                    bare=self._bare,
                    gitdir=self._gitdir,
                    capture_stdout=True,
                    capture_stderr=True,
                    verify_command=True,
                    log_as_error=log_as_error,
                )
                p.Wait()
                r = p.stdout
                if r.endswith("\n") and r.index("\n") == len(r) - 1:
                    return r[:-1]
                return r

            return runner


class LocalSyncFail(RepoError):
    """Default error when there is an Sync_LocalHalf error."""


class _PriorSyncFailedError(LocalSyncFail):
    def __str__(self):
        return "prior sync failed; rebase still in progress"


class _DirtyError(LocalSyncFail):
    def __str__(self):
        return "contains uncommitted changes"


class _InfoMessage:
    def __init__(self, project, text):
        self.project = project
        self.text = text

    def Print(self, syncbuf):
        syncbuf.out.info(
            "%s/: %s", self.project.RelPath(local=False), self.text
        )
        syncbuf.out.nl()


class _Failure:
    def __init__(self, project, why):
        self.project = project
        self.why = why

    def Print(self, syncbuf):
        syncbuf.out.fail(
            "error: %s/: %s", self.project.RelPath(local=False), str(self.why)
        )
        syncbuf.out.nl()


class _Later:
    def __init__(self, project, action, quiet):
        self.project = project
        self.action = action
        self.quiet = quiet

    def Run(self, syncbuf):
        out = syncbuf.out
        if not self.quiet:
            out.project("project %s/", self.project.RelPath(local=False))
            out.nl()
        try:
            self.action()
            if not self.quiet:
                out.nl()
            return True
        except GitError:
            out.nl()
            return False


class _SyncColoring(Coloring):
    def __init__(self, config):
        super().__init__(config, "reposync")
        self.project = self.printer("header", attr="bold")
        self.info = self.printer("info")
        self.fail = self.printer("fail", fg="red")


class SyncBuffer:
    def __init__(self, config, detach_head=False):
        self._messages = []
        self._failures = []
        self._later_queue1 = []
        self._later_queue2 = []

        self.out = _SyncColoring(config)
        self.out.redirect(sys.stderr)

        self.detach_head = detach_head
        self.clean = True
        self.recent_clean = True

    def info(self, project, fmt, *args):
        self._messages.append(_InfoMessage(project, fmt % args))

    def fail(self, project, err=None):
        self._failures.append(_Failure(project, err))
        self._MarkUnclean()

    def later1(self, project, what, quiet):
        self._later_queue1.append(_Later(project, what, quiet))

    def later2(self, project, what, quiet):
        self._later_queue2.append(_Later(project, what, quiet))

    def Finish(self):
        self._PrintMessages()
        self._RunLater()
        self._PrintMessages()
        return self.clean

    def Recently(self):
        recent_clean = self.recent_clean
        self.recent_clean = True
        return recent_clean

    def _MarkUnclean(self):
        self.clean = False
        self.recent_clean = False

    def _RunLater(self):
        for q in ["_later_queue1", "_later_queue2"]:
            if not self._RunQueue(q):
                return

    def _RunQueue(self, queue):
        for m in getattr(self, queue):
            if not m.Run(self):
                self._MarkUnclean()
                return False
        setattr(self, queue, [])
        return True

    def _PrintMessages(self):
        if self._messages or self._failures:
            if os.isatty(2):
                self.out.write(progress.CSI_ERASE_LINE)
            self.out.write("\r")

        for m in self._messages:
            m.Print(self)
        for m in self._failures:
            m.Print(self)

        self._messages = []
        self._failures = []


class MetaProject(Project):
    """A special project housed under .repo."""

    def __init__(self, manifest, name, gitdir, worktree):
        Project.__init__(
            self,
            manifest=manifest,
            name=name,
            gitdir=gitdir,
            objdir=gitdir,
            worktree=worktree,
            remote=RemoteSpec("origin"),
            relpath=".repo/%s" % name,
            revisionExpr="refs/heads/master",
            revisionId=None,
            groups=None,
        )

    def PreSync(self):
        if self.Exists:
            cb = self.CurrentBranch
            if cb:
                base = self.GetBranch(cb).merge
                if base:
                    self.revisionExpr = base
                    self.revisionId = None

    @property
    def HasChanges(self):
        """Has the remote received new commits not yet checked out?"""
        if not self.remote or not self.revisionExpr:
            return False

        all_refs = self.bare_ref.all
        revid = self.GetRevisionId(all_refs)
        head = self.work_git.GetHead()
        if head.startswith(R_HEADS):
            try:
                head = all_refs[head]
            except KeyError:
                head = None

        if revid == head:
            return False
        elif self._revlist(not_rev(HEAD), revid):
            return True
        return False


class RepoProject(MetaProject):
    """The MetaProject for repo itself."""

    @property
    def LastFetch(self):
        try:
            fh = os.path.join(self.gitdir, "FETCH_HEAD")
            return os.path.getmtime(fh)
        except OSError:
            return 0


class ManifestProject(MetaProject):
    """The MetaProject for manifests."""

    def MetaBranchSwitch(self, submodules=False, verbose=False):
        """Prepare for manifest branch switch."""

        # detach and delete manifest branch, allowing a new
        # branch to take over
        syncbuf = SyncBuffer(self.config, detach_head=True)
        self.Sync_LocalHalf(syncbuf, submodules=submodules, verbose=verbose)
        syncbuf.Finish()

        return (
            GitCommand(
                self,
                ["update-ref", "-d", "refs/heads/default"],
                capture_stdout=True,
                capture_stderr=True,
            ).Wait()
            == 0
        )

    @property
    def standalone_manifest_url(self):
        """The URL of the standalone manifest, or None."""
        return self.config.GetString("manifest.standalone")

    @property
    def manifest_groups(self):
        """The manifest groups string."""
        return self.config.GetString("manifest.groups")

    @property
    def reference(self):
        """The --reference for this manifest."""
        return self.config.GetString("repo.reference")

    @property
    def dissociate(self):
        """Whether to dissociate."""
        return self.config.GetBoolean("repo.dissociate")

    @property
    def archive(self):
        """Whether we use archive."""
        return self.config.GetBoolean("repo.archive")

    @property
    def mirror(self):
        """Whether we use mirror."""
        return self.config.GetBoolean("repo.mirror")

    @property
    def use_worktree(self):
        """Whether we use worktree."""
        return self.config.GetBoolean("repo.worktree")

    @property
    def clone_bundle(self):
        """Whether we use clone_bundle."""
        return self.config.GetBoolean("repo.clonebundle")

    @property
    def submodules(self):
        """Whether we use submodules."""
        return self.config.GetBoolean("repo.submodules")

    @property
    def git_lfs(self):
        """Whether we use git_lfs."""
        return self.config.GetBoolean("repo.git-lfs")

    @property
    def use_superproject(self):
        """Whether we use superproject."""
        return self.config.GetBoolean("repo.superproject")

    @property
    def partial_clone(self):
        """Whether this is a partial clone."""
        return self.config.GetBoolean("repo.partialclone")

    @property
    def depth(self):
        """Partial clone depth."""
        return self.config.GetInt("repo.depth")

    @property
    def clone_filter(self):
        """The clone filter."""
        return self.config.GetString("repo.clonefilter")

    @property
    def partial_clone_exclude(self):
        """Partial clone exclude string"""
        return self.config.GetString("repo.partialcloneexclude")

    @property
    def clone_filter_for_depth(self):
        """Replace shallow clone with partial clone."""
        return self.config.GetString("repo.clonefilterfordepth")

    @property
    def manifest_platform(self):
        """The --platform argument from `repo init`."""
        return self.config.GetString("manifest.platform")

    @property
    def _platform_name(self):
        """Return the name of the platform."""
        return platform.system().lower()

    def SyncWithPossibleInit(
        self,
        submanifest,
        verbose=False,
        current_branch_only=False,
        tags="",
        git_event_log=None,
    ):
        """Sync a manifestProject, possibly for the first time.

        Call Sync() with arguments from the most recent `repo init`.  If this is
        a new sub manifest, then inherit options from the parent's
        manifestProject.

        This is used by subcmds.Sync() to do an initial download of new sub
        manifests.

        Args:
            submanifest: an XmlSubmanifest, the submanifest to re-sync.
            verbose: a boolean, whether to show all output, rather than only
                errors.
            current_branch_only: a boolean, whether to only fetch the current
                manifest branch from the server.
            tags: a boolean, whether to fetch tags.
            git_event_log: an EventLog, for git tracing.
        """
        # TODO(lamontjones): when refactoring sync (and init?) consider how to
        # better get the init options that we should use for new submanifests
        # that are added when syncing an existing workspace.
        git_event_log = git_event_log or EventLog()
        spec = submanifest.ToSubmanifestSpec()
        # Use the init options from the existing manifestProject, or the parent
        # if it doesn't exist.
        #
        # Today, we only support changing manifest_groups on the sub-manifest,
        # with no supported-for-the-user way to change the other arguments from
        # those specified by the outermost manifest.
        #
        # TODO(lamontjones): determine which of these should come from the
        # outermost manifest and which should come from the parent manifest.
        mp = self if self.Exists else submanifest.parent.manifestProject
        return self.Sync(
            manifest_url=spec.manifestUrl,
            manifest_branch=spec.revision,
            standalone_manifest=mp.standalone_manifest_url,
            groups=mp.manifest_groups,
            platform=mp.manifest_platform,
            mirror=mp.mirror,
            dissociate=mp.dissociate,
            reference=mp.reference,
            worktree=mp.use_worktree,
            submodules=mp.submodules,
            archive=mp.archive,
            partial_clone=mp.partial_clone,
            clone_filter=mp.clone_filter,
            partial_clone_exclude=mp.partial_clone_exclude,
            clone_bundle=mp.clone_bundle,
            git_lfs=mp.git_lfs,
            use_superproject=mp.use_superproject,
            verbose=verbose,
            current_branch_only=current_branch_only,
            tags=tags,
            depth=mp.depth,
            git_event_log=git_event_log,
            manifest_name=spec.manifestName,
            this_manifest_only=True,
            outer_manifest=False,
            clone_filter_for_depth=mp.clone_filter_for_depth,
        )

    def Sync(
        self,
        _kwargs_only=(),
        manifest_url="",
        manifest_branch=None,
        standalone_manifest=False,
        groups="",
        mirror=False,
        reference="",
        dissociate=False,
        worktree=False,
        submodules=False,
        archive=False,
        partial_clone=None,
        depth=None,
        clone_filter="blob:none",
        partial_clone_exclude=None,
        clone_bundle=None,
        git_lfs=None,
        use_superproject=None,
        verbose=False,
        current_branch_only=False,
        git_event_log=None,
        platform="",
        manifest_name="default.xml",
        tags="",
        this_manifest_only=False,
        outer_manifest=True,
        clone_filter_for_depth=None,
    ):
        """Sync the manifest and all submanifests.

        Args:
            manifest_url: a string, the URL of the manifest project.
            manifest_branch: a string, the manifest branch to use.
            standalone_manifest: a boolean, whether to store the manifest as a
                static file.
            groups: a string, restricts the checkout to projects with the
                specified groups.
            mirror: a boolean, whether to create a mirror of the remote
                repository.
            reference: a string, location of a repo instance to use as a
                reference.
            dissociate: a boolean, whether to dissociate from reference mirrors
                after clone.
            worktree: a boolean, whether to use git-worktree to manage projects.
            submodules: a boolean, whether sync submodules associated with the
                manifest project.
            archive: a boolean, whether to checkout each project as an archive.
                See git-archive.
            partial_clone: a boolean, whether to perform a partial clone.
            depth: an int, how deep of a shallow clone to create.
            clone_filter: a string, filter to use with partial_clone.
            partial_clone_exclude : a string, comma-delimeted list of project
                names to exclude from partial clone.
            clone_bundle: a boolean, whether to enable /clone.bundle on
                HTTP/HTTPS.
            git_lfs: a boolean, whether to enable git LFS support.
            use_superproject: a boolean, whether to use the manifest
                superproject to sync projects.
            verbose: a boolean, whether to show all output, rather than only
                errors.
            current_branch_only: a boolean, whether to only fetch the current
                manifest branch from the server.
            platform: a string, restrict the checkout to projects with the
                specified platform group.
            git_event_log: an EventLog, for git tracing.
            tags: a boolean, whether to fetch tags.
            manifest_name: a string, the name of the manifest file to use.
            this_manifest_only: a boolean, whether to only operate on the
                current sub manifest.
            outer_manifest: a boolean, whether to start at the outermost
                manifest.
            clone_filter_for_depth: a string, when specified replaces shallow
                clones with partial.

        Returns:
            a boolean, whether the sync was successful.
        """
        assert _kwargs_only == (), "Sync only accepts keyword arguments."

        groups = groups or self.manifest.GetDefaultGroupsStr(
            with_platform=False
        )
        platform = platform or "auto"
        git_event_log = git_event_log or EventLog()
        if outer_manifest and self.manifest.is_submanifest:
            # In a multi-manifest checkout, use the outer manifest unless we are
            # told not to.
            return self.client.outer_manifest.manifestProject.Sync(
                manifest_url=manifest_url,
                manifest_branch=manifest_branch,
                standalone_manifest=standalone_manifest,
                groups=groups,
                platform=platform,
                mirror=mirror,
                dissociate=dissociate,
                reference=reference,
                worktree=worktree,
                submodules=submodules,
                archive=archive,
                partial_clone=partial_clone,
                clone_filter=clone_filter,
                partial_clone_exclude=partial_clone_exclude,
                clone_bundle=clone_bundle,
                git_lfs=git_lfs,
                use_superproject=use_superproject,
                verbose=verbose,
                current_branch_only=current_branch_only,
                tags=tags,
                depth=depth,
                git_event_log=git_event_log,
                manifest_name=manifest_name,
                this_manifest_only=this_manifest_only,
                outer_manifest=False,
            )

        # If repo has already been initialized, we take -u with the absence of
        # --standalone-manifest to mean "transition to a standard repo set up",
        # which necessitates starting fresh.
        # If --standalone-manifest is set, we always tear everything down and
        # start anew.
        if self.Exists:
            was_standalone_manifest = self.config.GetString(
                "manifest.standalone"
            )
            if was_standalone_manifest and not manifest_url:
                logger.error(
                    "fatal: repo was initialized with a standlone manifest, "
                    "cannot be re-initialized without --manifest-url/-u"
                )
                return False

            if standalone_manifest or (
                was_standalone_manifest and manifest_url
            ):
                self.config.ClearCache()
                if self.gitdir and os.path.exists(self.gitdir):
                    platform_utils.rmtree(self.gitdir)
                if self.worktree and os.path.exists(self.worktree):
                    platform_utils.rmtree(self.worktree)

        is_new = not self.Exists
        if is_new:
            if not manifest_url:
                logger.error("fatal: manifest url is required.")
                return False

            if verbose:
                print(
                    "Downloading manifest from %s"
                    % (GitConfig.ForUser().UrlInsteadOf(manifest_url),),
                    file=sys.stderr,
                )

            # The manifest project object doesn't keep track of the path on the
            # server where this git is located, so let's save that here.
            mirrored_manifest_git = None
            if reference:
                manifest_git_path = urllib.parse.urlparse(manifest_url).path[1:]
                mirrored_manifest_git = os.path.join(
                    reference, manifest_git_path
                )
                if not mirrored_manifest_git.endswith(".git"):
                    mirrored_manifest_git += ".git"
                if not os.path.exists(mirrored_manifest_git):
                    mirrored_manifest_git = os.path.join(
                        reference, ".repo/manifests.git"
                    )

            self._InitGitDir(mirror_git=mirrored_manifest_git)

        # If standalone_manifest is set, mark the project as "standalone" --
        # we'll still do much of the manifests.git set up, but will avoid actual
        # syncs to a remote.
        if standalone_manifest:
            self.config.SetString("manifest.standalone", manifest_url)
        elif not manifest_url and not manifest_branch:
            # If -u is set and --standalone-manifest is not, then we're not in
            # standalone mode. Otherwise, use config to infer what we were in
            # the last init.
            standalone_manifest = bool(
                self.config.GetString("manifest.standalone")
            )
        if not standalone_manifest:
            self.config.SetString("manifest.standalone", None)

        self._ConfigureDepth(depth)

        # Set the remote URL before the remote branch as we might need it below.
        if manifest_url:
            r = self.GetRemote()
            r.url = manifest_url
            r.ResetFetch()
            r.Save()

        if not standalone_manifest:
            if manifest_branch:
                if manifest_branch == "HEAD":
                    manifest_branch = self.ResolveRemoteHead()
                    if manifest_branch is None:
                        logger.error("fatal: unable to resolve HEAD")
                        return False
                self.revisionExpr = manifest_branch
            else:
                if is_new:
                    default_branch = self.ResolveRemoteHead()
                    if default_branch is None:
                        # If the remote doesn't have HEAD configured, default to
                        # master.
                        default_branch = "refs/heads/master"
                    self.revisionExpr = default_branch
                else:
                    self.PreSync()

        groups = re.split(r"[,\s]+", groups or "")
        all_platforms = ["linux", "darwin", "windows"]
        platformize = lambda x: "platform-" + x
        if platform == "auto":
            if not mirror and not self.mirror:
                groups.append(platformize(self._platform_name))
        elif platform == "all":
            groups.extend(map(platformize, all_platforms))
        elif platform in all_platforms:
            groups.append(platformize(platform))
        elif platform != "none":
            logger.error("fatal: invalid platform flag", file=sys.stderr)
            return False
        self.config.SetString("manifest.platform", platform)

        groups = [x for x in groups if x]
        groupstr = ",".join(groups)
        if (
            platform == "auto"
            and groupstr == self.manifest.GetDefaultGroupsStr()
        ):
            groupstr = None
        self.config.SetString("manifest.groups", groupstr)

        if reference:
            self.config.SetString("repo.reference", reference)

        if dissociate:
            self.config.SetBoolean("repo.dissociate", dissociate)

        if worktree:
            if mirror:
                logger.error("fatal: --mirror and --worktree are incompatible")
                return False
            if submodules:
                logger.error(
                    "fatal: --submodules and --worktree are incompatible"
                )
                return False
            self.config.SetBoolean("repo.worktree", worktree)
            if is_new:
                self.use_git_worktrees = True
            logger.warning("warning: --worktree is experimental!")

        if archive:
            if is_new:
                self.config.SetBoolean("repo.archive", archive)
            else:
                logger.error(
                    "fatal: --archive is only supported when initializing a "
                    "new workspace."
                )
                logger.error(
                    "Either delete the .repo folder in this workspace, or "
                    "initialize in another location."
                )
                return False

        if mirror:
            if is_new:
                self.config.SetBoolean("repo.mirror", mirror)
            else:
                logger.error(
                    "fatal: --mirror is only supported when initializing a new "
                    "workspace."
                )
                logger.error(
                    "Either delete the .repo folder in this workspace, or "
                    "initialize in another location."
                )
                return False

        if partial_clone is not None:
            if mirror:
                logger.error(
                    "fatal: --mirror and --partial-clone are mutually "
                    "exclusive"
                )
                return False
            self.config.SetBoolean("repo.partialclone", partial_clone)
            if clone_filter:
                self.config.SetString("repo.clonefilter", clone_filter)
        elif self.partial_clone:
            clone_filter = self.clone_filter
        else:
            clone_filter = None

        if partial_clone_exclude is not None:
            self.config.SetString(
                "repo.partialcloneexclude", partial_clone_exclude
            )

        if clone_bundle is None:
            clone_bundle = False if partial_clone else True
        else:
            self.config.SetBoolean("repo.clonebundle", clone_bundle)

        if submodules:
            self.config.SetBoolean("repo.submodules", submodules)

        if git_lfs is not None:
            if git_lfs:
                git_require((2, 17, 0), fail=True, msg="Git LFS support")

            self.config.SetBoolean("repo.git-lfs", git_lfs)
            if not is_new:
                logger.warning(
                    "warning: Changing --git-lfs settings will only affect new "
                    "project checkouts.\n"
                    "         Existing projects will require manual updates.\n"
                )

        if clone_filter_for_depth is not None:
            self.ConfigureCloneFilterForDepth(clone_filter_for_depth)

        if use_superproject is not None:
            self.config.SetBoolean("repo.superproject", use_superproject)

        if not standalone_manifest:
            success = self.Sync_NetworkHalf(
                is_new=is_new,
                quiet=not verbose,
                verbose=verbose,
                clone_bundle=clone_bundle,
                current_branch_only=current_branch_only,
                tags=tags,
                submodules=submodules,
                clone_filter=clone_filter,
                partial_clone_exclude=self.manifest.PartialCloneExclude,
                clone_filter_for_depth=self.manifest.CloneFilterForDepth,
            ).success
            if not success:
                r = self.GetRemote()
                logger.error("fatal: cannot obtain manifest %s", r.url)

                # Better delete the manifest git dir if we created it; otherwise
                # next time (when user fixes problems) we won't go through the
                # "is_new" logic.
                if is_new:
                    platform_utils.rmtree(self.gitdir)
                return False

            if manifest_branch:
                self.MetaBranchSwitch(submodules=submodules, verbose=verbose)

            syncbuf = SyncBuffer(self.config)
            self.Sync_LocalHalf(syncbuf, submodules=submodules, verbose=verbose)
            syncbuf.Finish()

            if is_new or self.CurrentBranch is None:
                try:
                    self.StartBranch("default")
                except GitError as e:
                    msg = str(e)
                    logger.error(
                        "fatal: cannot create default in manifest %s", msg
                    )
                    return False

            if not manifest_name:
                logger.error("fatal: manifest name (-m) is required.")
                return False

        elif is_new:
            # This is a new standalone manifest.
            manifest_name = "default.xml"
            manifest_data = fetch.fetch_file(manifest_url, verbose=verbose)
            dest = os.path.join(self.worktree, manifest_name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(manifest_data)

        try:
            self.manifest.Link(manifest_name)
        except ManifestParseError as e:
            logger.error("fatal: manifest '%s' not available", manifest_name)
            logger.error("fatal: %s", e)
            return False

        if not this_manifest_only:
            for submanifest in self.manifest.submanifests.values():
                spec = submanifest.ToSubmanifestSpec()
                submanifest.repo_client.manifestProject.Sync(
                    manifest_url=spec.manifestUrl,
                    manifest_branch=spec.revision,
                    standalone_manifest=standalone_manifest,
                    groups=self.manifest_groups,
                    platform=platform,
                    mirror=mirror,
                    dissociate=dissociate,
                    reference=reference,
                    worktree=worktree,
                    submodules=submodules,
                    archive=archive,
                    partial_clone=partial_clone,
                    clone_filter=clone_filter,
                    partial_clone_exclude=partial_clone_exclude,
                    clone_bundle=clone_bundle,
                    git_lfs=git_lfs,
                    use_superproject=use_superproject,
                    verbose=verbose,
                    current_branch_only=current_branch_only,
                    tags=tags,
                    depth=depth,
                    git_event_log=git_event_log,
                    manifest_name=spec.manifestName,
                    this_manifest_only=False,
                    outer_manifest=False,
                )

        # Lastly, if the manifest has a <superproject> then have the
        # superproject sync it (if it will be used).
        if git_superproject.UseSuperproject(use_superproject, self.manifest):
            sync_result = self.manifest.superproject.Sync(git_event_log)
            if not sync_result.success:
                submanifest = ""
                if self.manifest.path_prefix:
                    submanifest = f"for {self.manifest.path_prefix} "
                logger.warning(
                    "warning: git update of superproject %s failed, "
                    "repo sync will not use superproject to fetch source; "
                    "while this error is not fatal, and you can continue to "
                    "run repo sync, please run repo init with the "
                    "--no-use-superproject option to stop seeing this warning",
                    submanifest,
                )
                if sync_result.fatal and use_superproject is not None:
                    return False

        return True

    def ConfigureCloneFilterForDepth(self, clone_filter_for_depth):
        """Configure clone filter to replace shallow clones.

        Args:
            clone_filter_for_depth: a string or None, e.g. 'blob:none' will
            disable shallow clones and replace with partial clone. None will
            enable shallow clones.
        """
        self.config.SetString(
            "repo.clonefilterfordepth", clone_filter_for_depth
        )

    def _ConfigureDepth(self, depth):
        """Configure the depth we'll sync down.

        Args:
            depth: an int, how deep of a partial clone to create.
        """
        # Opt.depth will be non-None if user actually passed --depth to repo
        # init.
        if depth is not None:
            if depth > 0:
                # Positive values will set the depth.
                depth = str(depth)
            else:
                # Negative numbers will clear the depth; passing None to
                # SetString will do that.
                depth = None

            # We store the depth in the main manifest project.
            self.config.SetString("repo.depth", depth)
