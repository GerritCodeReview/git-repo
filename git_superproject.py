# Copyright (C) 2021 The Android Open Source Project
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

"""Provide functionality to get projects and their commit ids from Superproject.

For more information on superproject, check out:
https://en.wikibooks.org/wiki/Git/Submodules_and_Superprojects

Examples:
  superproject = Superproject(manifest, name, remote, revision)
  UpdateProjectsResult = superproject.UpdateProjectsRevisionId(projects)
"""

import functools
import hashlib
import os
import sys
import time
from typing import NamedTuple

from git_command import git_require
from git_command import GitCommand
from git_config import RepoConfig
from git_refs import GitRefs


_SUPERPROJECT_GIT_NAME = "superproject.git"
_SUPERPROJECT_MANIFEST_NAME = "superproject_override.xml"


class SyncResult(NamedTuple):
    """Return the status of sync and whether caller should exit."""

    # Whether the superproject sync was successful.
    success: bool
    # Whether the caller should exit.
    fatal: bool


class CommitIdsResult(NamedTuple):
    """Return the commit ids and whether caller should exit."""

    # A dictionary with the projects/commit ids on success, otherwise None.
    commit_ids: dict
    # Whether the caller should exit.
    fatal: bool


class UpdateProjectsResult(NamedTuple):
    """Return the overriding manifest file and whether caller should exit."""

    # Path name of the overriding manifest file if successful, otherwise None.
    manifest_path: str
    # Whether the caller should exit.
    fatal: bool


class Superproject:
    """Get commit ids from superproject.

    Initializes a bare local copy of a superproject for the manifest. This
    allows lookup of commit ids for all projects. It contains
    _project_commit_ids which is a dictionary with project/commit id entries.
    """

    def __init__(
        self,
        manifest,
        name,
        remote,
        revision,
        superproject_dir="exp-superproject",
    ):
        """Initializes superproject.

        Args:
            manifest: A Manifest object that is to be written to a file.
            name: The unique name of the superproject
            remote: The RemoteSpec for the remote.
            revision: The name of the git branch to track.
            superproject_dir: Relative path under |manifest.subdir| to checkout
                superproject.
        """
        self._project_commit_ids = None
        self._manifest = manifest
        self.name = name
        self.remote = remote
        self.revision = self._branch = revision
        self._repodir = manifest.repodir
        self._superproject_dir = superproject_dir
        self._superproject_path = manifest.SubmanifestInfoDir(
            manifest.path_prefix, superproject_dir
        )
        self._manifest_path = os.path.join(
            self._superproject_path, _SUPERPROJECT_MANIFEST_NAME
        )
        git_name = hashlib.md5(remote.name.encode("utf8")).hexdigest() + "-"
        self._remote_url = remote.url
        self._work_git_name = git_name + _SUPERPROJECT_GIT_NAME
        self._work_git = os.path.join(
            self._superproject_path, self._work_git_name
        )

        # The following are command arguemnts, rather than superproject
        # attributes, and were included here originally.  They should eventually
        # become arguments that are passed down from the public methods, instead
        # of being treated as attributes.
        self._git_event_log = None
        self._quiet = False
        self._print_messages = False

    def SetQuiet(self, value):
        """Set the _quiet attribute."""
        self._quiet = value

    def SetPrintMessages(self, value):
        """Set the _print_messages attribute."""
        self._print_messages = value

    @property
    def project_commit_ids(self):
        """Returns a dictionary of projects and their commit ids."""
        return self._project_commit_ids

    @property
    def manifest_path(self):
        """Returns the manifest path if the path exists or None."""
        return (
            self._manifest_path if os.path.exists(self._manifest_path) else None
        )

    def _LogMessage(self, fmt, *inputs):
        """Logs message to stderr and _git_event_log."""
        message = f"{self._LogMessagePrefix()} {fmt.format(*inputs)}"
        if self._print_messages:
            print(message, file=sys.stderr)
        self._git_event_log.ErrorEvent(message, fmt)

    def _LogMessagePrefix(self):
        """Returns the prefix string to be logged in each log message"""
        return (
            f"repo superproject branch: {self._branch} url: {self._remote_url}"
        )

    def _LogError(self, fmt, *inputs):
        """Logs error message to stderr and _git_event_log."""
        self._LogMessage(f"error: {fmt}", *inputs)

    def _LogWarning(self, fmt, *inputs):
        """Logs warning message to stderr and _git_event_log."""
        self._LogMessage(f"warning: {fmt}", *inputs)

    def _Init(self):
        """Sets up a local Git repository to get a copy of a superproject.

        Returns:
            True if initialization is successful, or False.
        """
        if not os.path.exists(self._superproject_path):
            os.mkdir(self._superproject_path)
        if not self._quiet and not os.path.exists(self._work_git):
            print(
                "%s: Performing initial setup for superproject; this might "
                "take several minutes." % self._work_git
            )
        cmd = ["init", "--bare", self._work_git_name]
        p = GitCommand(
            None,
            cmd,
            cwd=self._superproject_path,
            capture_stdout=True,
            capture_stderr=True,
        )
        retval = p.Wait()
        if retval:
            self._LogWarning(
                "git init call failed, command: git {}, "
                "return code: {}, stderr: {}",
                cmd,
                retval,
                p.stderr,
            )
            return False
        return True

    def _Fetch(self):
        """Fetches a superproject for the manifest based on |_remote_url|.

        This runs git fetch which stores a local copy the superproject.

        Returns:
            True if fetch is successful, or False.
        """
        if not os.path.exists(self._work_git):
            self._LogWarning("git fetch missing directory: {}", self._work_git)
            return False
        if not git_require((2, 28, 0)):
            self._LogWarning(
                "superproject requires a git version 2.28 or later"
            )
            return False
        cmd = [
            "fetch",
            self._remote_url,
            "--depth",
            "1",
            "--force",
            "--no-tags",
            "--filter",
            "blob:none",
        ]

        # Check if there is a local ref that we can pass to --negotiation-tip.
        # If this is the first fetch, it does not exist yet.
        # We use --negotiation-tip to speed up the fetch. Superproject branches
        # do not share commits. So this lets git know it only needs to send
        # commits reachable from the specified local refs.
        rev_commit = GitRefs(self._work_git).get(f"refs/heads/{self.revision}")
        if rev_commit:
            cmd.extend(["--negotiation-tip", rev_commit])

        if self._branch:
            cmd += [self._branch + ":" + self._branch]
        p = GitCommand(
            None,
            cmd,
            gitdir=self._work_git,
            bare=True,
            capture_stdout=True,
            capture_stderr=True,
        )
        retval = p.Wait()
        if retval:
            self._LogWarning(
                "git fetch call failed, command: git {}, "
                "return code: {}, stderr: {}",
                cmd,
                retval,
                p.stderr,
            )
            return False
        return True

    def _LsTree(self):
        """Gets the commit ids for all projects.

        Works only in git repositories.

        Returns:
            data: data returned from 'git ls-tree ...' instead of None.
        """
        if not os.path.exists(self._work_git):
            self._LogWarning(
                "git ls-tree missing directory: {}", self._work_git
            )
            return None
        data = None
        branch = "HEAD" if not self._branch else self._branch
        cmd = ["ls-tree", "-z", "-r", branch]

        p = GitCommand(
            None,
            cmd,
            gitdir=self._work_git,
            bare=True,
            capture_stdout=True,
            capture_stderr=True,
        )
        retval = p.Wait()
        if retval == 0:
            data = p.stdout
        else:
            self._LogWarning(
                "git ls-tree call failed, command: git {}, "
                "return code: {}, stderr: {}",
                cmd,
                retval,
                p.stderr,
            )
        return data

    def Sync(self, git_event_log):
        """Gets a local copy of a superproject for the manifest.

        Args:
            git_event_log: an EventLog, for git tracing.

        Returns:
            SyncResult
        """
        self._git_event_log = git_event_log
        if not self._manifest.superproject:
            self._LogWarning(
                "superproject tag is not defined in manifest: {}",
                self._manifest.manifestFile,
            )
            return SyncResult(False, False)

        should_exit = True
        if not self._remote_url:
            self._LogWarning(
                "superproject URL is not defined in manifest: {}",
                self._manifest.manifestFile,
            )
            return SyncResult(False, should_exit)

        if not self._Init():
            return SyncResult(False, should_exit)
        if not self._Fetch():
            return SyncResult(False, should_exit)
        if not self._quiet:
            print(
                "%s: Initial setup for superproject completed." % self._work_git
            )
        return SyncResult(True, False)

    def _GetAllProjectsCommitIds(self):
        """Get commit ids for all projects from superproject and save them.

        Commit ids are saved in _project_commit_ids.

        Returns:
            CommitIdsResult
        """
        sync_result = self.Sync(self._git_event_log)
        if not sync_result.success:
            return CommitIdsResult(None, sync_result.fatal)

        data = self._LsTree()
        if not data:
            self._LogWarning(
                "git ls-tree failed to return data for manifest: {}",
                self._manifest.manifestFile,
            )
            return CommitIdsResult(None, True)

        # Parse lines like the following to select lines starting with '160000'
        # and build a dictionary with project path (last element) and its commit
        # id (3rd element).
        #
        # 160000 commit 2c2724cb36cd5a9cec6c852c681efc3b7c6b86ea\tart\x00
        # 120000 blob acc2cbdf438f9d2141f0ae424cec1d8fc4b5d97f\tbootstrap.bash\x00  # noqa: E501
        commit_ids = {}
        for line in data.split("\x00"):
            ls_data = line.split(None, 3)
            if not ls_data:
                break
            if ls_data[0] == "160000":
                commit_ids[ls_data[3]] = ls_data[2]

        self._project_commit_ids = commit_ids
        return CommitIdsResult(commit_ids, False)

    def _WriteManifestFile(self):
        """Writes manifest to a file.

        Returns:
            manifest_path: Path name of the file into which manifest is written
                instead of None.
        """
        if not os.path.exists(self._superproject_path):
            self._LogWarning(
                "missing superproject directory: {}", self._superproject_path
            )
            return None
        manifest_str = self._manifest.ToXml(
            groups=self._manifest.GetGroupsStr(), omit_local=True
        ).toxml()
        manifest_path = self._manifest_path
        try:
            with open(manifest_path, "w", encoding="utf-8") as fp:
                fp.write(manifest_str)
        except OSError as e:
            self._LogError("cannot write manifest to : {} {}", manifest_path, e)
            return None
        return manifest_path

    def _SkipUpdatingProjectRevisionId(self, project):
        """Checks if a project's revision id needs to be updated or not.

        Revision id for projects from local manifest will not be updated.

        Args:
            project: project whose revision id is being updated.

        Returns:
            True if a project's revision id should not be updated, or False,
        """
        path = project.relpath
        if not path:
            return True
        # Skip the project with revisionId.
        if project.revisionId:
            return True
        # Skip the project if it comes from the local manifest.
        return project.manifest.IsFromLocalManifest(project)

    def UpdateProjectsRevisionId(self, projects, git_event_log):
        """Update revisionId of every project in projects with the commit id.

        Args:
            projects: a list of projects whose revisionId needs to be updated.
            git_event_log: an EventLog, for git tracing.

        Returns:
            UpdateProjectsResult
        """
        self._git_event_log = git_event_log
        commit_ids_result = self._GetAllProjectsCommitIds()
        commit_ids = commit_ids_result.commit_ids
        if not commit_ids:
            return UpdateProjectsResult(None, commit_ids_result.fatal)

        projects_missing_commit_ids = []
        for project in projects:
            if self._SkipUpdatingProjectRevisionId(project):
                continue
            path = project.relpath
            commit_id = commit_ids.get(path)
            if not commit_id:
                projects_missing_commit_ids.append(path)

        # If superproject doesn't have a commit id for a project, then report an
        # error event and continue as if do not use superproject is specified.
        if projects_missing_commit_ids:
            self._LogWarning(
                "please file a bug using {} to report missing "
                "commit_ids for: {}",
                self._manifest.contactinfo.bugurl,
                projects_missing_commit_ids,
            )
            return UpdateProjectsResult(None, False)

        for project in projects:
            if not self._SkipUpdatingProjectRevisionId(project):
                project.SetRevisionId(commit_ids.get(project.relpath))

        manifest_path = self._WriteManifestFile()
        return UpdateProjectsResult(manifest_path, False)


@functools.lru_cache(maxsize=None)
def _UseSuperprojectFromConfiguration():
    """Returns the user choice of whether to use superproject."""
    user_cfg = RepoConfig.ForUser()
    time_now = int(time.time())

    user_value = user_cfg.GetBoolean("repo.superprojectChoice")
    if user_value is not None:
        user_expiration = user_cfg.GetInt("repo.superprojectChoiceExpire")
        if (
            user_expiration is None
            or user_expiration <= 0
            or user_expiration >= time_now
        ):
            # TODO(b/190688390) - Remove prompt when we are comfortable with the
            # new default value.
            if user_value:
                print(
                    (
                        "You are currently enrolled in Git submodules "
                        "experiment (go/android-submodules-quickstart).  Use "
                        "--no-use-superproject to override.\n"
                    ),
                    file=sys.stderr,
                )
            else:
                print(
                    (
                        "You are not currently enrolled in Git submodules "
                        "experiment (go/android-submodules-quickstart).  Use "
                        "--use-superproject to override.\n"
                    ),
                    file=sys.stderr,
                )
            return user_value

    # We don't have an unexpired choice, ask for one.
    system_cfg = RepoConfig.ForSystem()
    system_value = system_cfg.GetBoolean("repo.superprojectChoice")
    if system_value:
        # The system configuration is proposing that we should enable the
        # use of superproject. Treat the user as enrolled for two weeks.
        #
        # TODO(b/190688390) - Remove prompt when we are comfortable with the new
        # default value.
        userchoice = True
        time_choiceexpire = time_now + (86400 * 14)
        user_cfg.SetString(
            "repo.superprojectChoiceExpire", str(time_choiceexpire)
        )
        user_cfg.SetBoolean("repo.superprojectChoice", userchoice)
        print(
            "You are automatically enrolled in Git submodules experiment "
            "(go/android-submodules-quickstart) for another two weeks.\n",
            file=sys.stderr,
        )
        return True

    # For all other cases, we would not use superproject by default.
    return False


def PrintMessages(use_superproject, manifest):
    """Returns a boolean if error/warning messages are to be printed.

    Args:
        use_superproject: option value from optparse.
        manifest: manifest to use.
    """
    return use_superproject is not None or bool(manifest.superproject)


def UseSuperproject(use_superproject, manifest):
    """Returns a boolean if use-superproject option is enabled.

    Args:
        use_superproject: option value from optparse.
        manifest: manifest to use.

    Returns:
        Whether the superproject should be used.
    """

    if not manifest.superproject:
        # This (sub) manifest does not have a superproject definition.
        return False
    elif use_superproject is not None:
        return use_superproject
    else:
        client_value = manifest.manifestProject.use_superproject
        if client_value is not None:
            return client_value
        elif manifest.superproject:
            return _UseSuperprojectFromConfiguration()
        else:
            return False
