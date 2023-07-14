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

from typing import List, Text

DEFAULT_GIT_FAIL_MESSAGE = "git command failure"


class BaseRepoError(Exception):
    """All repo specific exceptions derive from BaseRepoError."""

    def __init__(self, *args, project: Text = None):
        super().__init__(*args)
        self.project = project


class RepoError(BaseRepoError):
    """Exceptions thrown inside repo that can be handled outside of main.py."""


class RepoExitError(BaseRepoError):
    """Exception thrown that result in termination of repo program.
    - Should only be handled in main.py
    """

    def __init__(
        self,
        *args,
        exit_code=1,
        aggregate_errors: List[Exception] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.exit_code = exit_code
        self.aggregate_errors = aggregate_errors


class ManifestParseError(RepoExitError):
    """Failed to parse the manifest file."""


class ManifestInvalidRevisionError(ManifestParseError):
    """The revision value in a project is incorrect."""


class ManifestInvalidPathError(ManifestParseError):
    """A path used in <copyfile> or <linkfile> is incorrect."""


class NoManifestException(RepoExitError):
    """The required manifest does not exist."""

    def __init__(self, path, reason, **kwargs):
        super().__init__(path, reason, **kwargs)
        self.path = path
        self.reason = reason

    def __str__(self):
        return self.reason


class EditorError(RepoError):
    """Unspecified error from the user's text editor."""

    def __init__(self, reason, **kwargs):
        super().__init__(reason, **kwargs)
        self.reason = reason

    def __str__(self):
        return self.reason


class GitError(RepoError):
    """Unspecified internal error from git."""

    def __init__(self, command, command_args=None, **kwargs):
        super().__init__(command, **kwargs)
        self.command = command
        self.command_args = command_args

    def __str__(self):
        return self.command


class GitCommandError(GitError):
    """Error raised from a failed git command."""

    def __init__(
        self,
        message=DEFAULT_GIT_FAIL_MESSAGE,
        git_rc=None,
        **kwargs,
    ):
        super().__init__(
            message,
            **kwargs,
        )
        self.git_rc = git_rc

    def __str__(self):
        args = [] if not self.command_args else " ".join(self.command_args)
        error_type = type(self).__name__
        return f"""{error_type}: {self.command}
    Project: {self.project}
    Args: {args}"""


class UploadError(RepoError):
    """A bundle upload to Gerrit did not succeed."""

    def __init__(self, reason, **kwargs):
        super().__init__(reason, **kwargs)
        self.reason = reason

    def __str__(self):
        return self.reason


class DownloadError(RepoExitError):
    """Cannot download a repository."""

    def __init__(self, reason, **kwargs):
        super().__init__(reason, **kwargs)
        self.reason = reason

    def __str__(self):
        return self.reason


class SyncError(RepoExitError):
    """Cannot sync repo."""


class UpdateManifestError(RepoExitError):
    """Cannot update manifest."""


class NoSuchProjectError(RepoExitError):
    """A specified project does not exist in the work tree."""

    def __init__(self, name=None):
        super().__init__(name)
        self.name = name

    def __str__(self):
        if self.name is None:
            return "in current directory"
        return self.name


class InvalidProjectGroupsError(RepoExitError):
    """A specified project is not suitable for the specified groups"""

    def __init__(self, name=None):
        super().__init__(name)
        self.name = name

    def __str__(self):
        if self.name is None:
            return "in current directory"
        return self.name


class RepoChangedException(BaseRepoError):
    """Thrown if 'repo sync' results in repo updating its internal
    repo or manifest repositories.  In this special case we must
    use exec to re-execute repo with the new code and manifest.
    """

    def __init__(self, extra_args=None):
        super().__init__(extra_args)
        self.extra_args = extra_args or []


class HookError(RepoError):
    """Thrown if a 'repo-hook' could not be run.

    The common case is that the file wasn't present when we tried to run it.
    """
