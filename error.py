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

from enum import IntEnum
from typing import List


class ExitCode(IntEnum):
    """Exit codes for each error type. See docs/exit-codes.md."""

    GENERAL_ERROR = 1
    MANIFEST_PARSE_ERROR = 2
    MANIFEST_INVALID_REVISION_ERROR = 3
    MANIFEST_INVALID_PATH_ERROR = 4
    NO_MANIFEST_EXCEPTION = 5
    GIT_AUTH_ERROR = 6
    DOWNLOAD_ERROR = 7
    INVALID_ARGUMENTS_ERROR = 8
    SYNC_ERROR = 9
    UPDATE_MANIFEST_ERROR = 10
    NO_SUCH_PROJECT_ERROR = 11
    INVALID_PROJECT_GROUPS_ERROR = 12
    USAGE_ERROR = 13
    ABANDON_ERROR = 14
    CHECKOUT_COMMAND_ERROR = 15
    MISSING_BRANCH_ERROR = 16
    DOWNLOAD_COMMAND_ERROR = 17
    GREP_COMMAND_ERROR = 18
    START_ERROR = 19
    UPLOAD_EXIT_ERROR = 20
    SUPERPROJECT_ERROR = 21
    SYNC_FAIL_FAST_ERROR = 22
    SMART_SYNC_ERROR = 23
    SELFUPDATE_ERROR = 24
    WIPE_ERROR = 25
    FETCH_FILE_ERROR = 26
    GIT_REQUIRE_ERROR = 126


class BaseRepoError(Exception):
    """All repo specific exceptions derive from BaseRepoError."""


class RepoError(BaseRepoError):
    """Exceptions thrown inside repo that can be handled."""

    def __init__(self, *args, project: str = None) -> None:
        super().__init__(*args)
        self.project = project


class RepoExitError(BaseRepoError):
    """Exception thrown that result in termination of repo program.
    - Should only be handled in main.py
    """

    def __init__(
        self,
        *args,
        exit_code: int = ExitCode.GENERAL_ERROR,
        aggregate_errors: List[Exception] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.exit_code = exit_code
        self.aggregate_errors = aggregate_errors


class RepoUnhandledExceptionError(RepoExitError):
    """Exception that maintains error as reason for program exit."""

    def __init__(
        self,
        error: BaseException,
        **kwargs,
    ) -> None:
        super().__init__(error, **kwargs)
        self.error = error


class SilentRepoExitError(RepoExitError):
    """RepoExitError that should no include CLI logging of issue/issues."""


class ManifestParseError(RepoExitError):
    """Failed to parse the manifest file."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("exit_code", ExitCode.MANIFEST_PARSE_ERROR)
        super().__init__(*args, **kwargs)


class ManifestInvalidRevisionError(ManifestParseError):
    """The revision value in a project is incorrect."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, exit_code=ExitCode.MANIFEST_INVALID_REVISION_ERROR, **kwargs
        )


class ManifestInvalidPathError(ManifestParseError):
    """A path used in <copyfile> or <linkfile> is incorrect."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, exit_code=ExitCode.MANIFEST_INVALID_PATH_ERROR, **kwargs
        )


class NoManifestException(RepoExitError):
    """The required manifest does not exist."""

    def __init__(self, path, reason, **kwargs):
        super().__init__(
            path, reason, exit_code=ExitCode.NO_MANIFEST_EXCEPTION, **kwargs
        )
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
    """Unspecified git related error."""

    def __init__(self, message, command_args=None, **kwargs):
        super().__init__(message, **kwargs)
        self.message = message
        self.command_args = command_args

    def __str__(self):
        return self.message


class GitAuthError(RepoExitError):
    """Cannot talk to remote due to auth issue."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, exit_code=ExitCode.GIT_AUTH_ERROR, **kwargs)


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
        super().__init__(reason, exit_code=ExitCode.DOWNLOAD_ERROR, **kwargs)
        self.reason = reason

    def __str__(self):
        return self.reason


class InvalidArgumentsError(RepoExitError):
    """Invalid command Arguments."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, exit_code=ExitCode.INVALID_ARGUMENTS_ERROR, **kwargs
        )


class SyncError(RepoExitError):
    """Cannot sync repo."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("exit_code", ExitCode.SYNC_ERROR)
        super().__init__(*args, **kwargs)


class UpdateManifestError(RepoExitError):
    """Cannot update manifest."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, exit_code=ExitCode.UPDATE_MANIFEST_ERROR, **kwargs
        )


class NoSuchProjectError(RepoExitError):
    """A specified project does not exist in the work tree."""

    def __init__(self, name=None, **kwargs):
        super().__init__(exit_code=ExitCode.NO_SUCH_PROJECT_ERROR, **kwargs)
        self.name = name

    def __str__(self):
        if self.name is None:
            return "in current directory"
        return self.name


class InvalidProjectGroupsError(RepoExitError):
    """A specified project is not suitable for the specified groups"""

    def __init__(self, name=None, **kwargs):
        super().__init__(
            exit_code=ExitCode.INVALID_PROJECT_GROUPS_ERROR, **kwargs
        )
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
