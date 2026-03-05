# Exit Codes

This document describes all exit codes that `repo` can return.

## Fixed Exit Codes

| Code | Exception | Description |
|------|-----------|-------------|
| 0 | — | Success. |
| 1 | `RepoUnhandledExceptionError` / catch-all | Unknown or unhandled error. Default for any failure path not covered below. |
| 2 | `ManifestParseError` | Failed to parse the manifest XML. |
| 3 | `ManifestInvalidRevisionError` | Invalid revision specified in manifest. |
| 4 | `ManifestInvalidPathError` | Invalid path in copyfile or linkfile element. |
| 5 | `NoManifestException` | Required manifest file does not exist. |
| 6 | `GitAuthError` | Authentication failure talking to a remote. |
| 7 | `DownloadError` | Cannot download a repository. |
| 8 | `InvalidArgumentsError` | Invalid command-line arguments. |
| 9 | `SyncError` | Cannot sync one or more projects. |
| 10 | `UpdateManifestError` | Cannot update the manifest repository. |
| 11 | `NoSuchProjectError` | Specified project not found in the work tree. |
| 12 | `InvalidProjectGroupsError` | Project not in the requested manifest groups. |
| 13 | `UsageError` | Invalid command usage. |
| 14 | `AbandonError` | Abandon command failed. |
| 15 | `CheckoutCommandError` | Checkout command failed. |
| 16 | `MissingBranchError` | No project has the specified branch. |
| 17 | `DownloadCommandError` | Download command failed. |
| 18 | `GrepCommandError` | Grep found no matches or failed. |
| 19 | `StartError` | Start command failed. |
| 20 | `UploadExitError` | Upload command failed. |
| 21 | `SuperprojectError` | Superproject sync error. |
| 22 | `SyncFailFastError` | Sync aborted due to --fail-fast. |
| 23 | `SmartSyncError` | Smart sync failure. |
| 24 | `SelfupdateError` | Self-update failed. |
| 25 | `wipe.Error` | Wipe command failed. |
| 26 | `FetchFileError` | File fetch failed. |
| 126 | `GitRequireError` | Git not found or version too old. |
| 128 | — | Cannot restart after self-upgrade. Returned when repo upgrades itself (`RepoChangedException`) but `os.execv` fails to re-exec the new version. |
| 130 | — | Keyboard interrupt. Returned when the user presses Ctrl+C (128 + SIGINT). |
| 148 | — | Cannot exec repo entry point. Returned by the launcher (`repo` script) when it fails to exec the main repo program after bootstrap. |
| 255 | — | Cannot start pager. Returned when forking the pager process fails. |

## Dynamic Exit Codes

These codes depend on runtime conditions and are not fixed values.

### `repo forall`

The `forall` command runs a shell command in each project directory and exits
with the first non-zero return code from any child process. This means `repo
forall` can return any exit code from 0 to 255 depending on the command being
run. On `KeyboardInterrupt` inside a worker, it returns 4 (`errno.EINTR`).

### `repo rebase`

On failure, `rebase` returns the count of projects that failed to rebase. A
return value of 3 means three projects failed.

## Exception Hierarchy

Most errors are reported through exceptions that inherit from `RepoExitError`.
Each subclass has a unique exit code listed in the table above.

| Exception | Base Class | Exit Code |
|-----------|------------|-----------|
| `RepoExitError` | `BaseRepoError` | 1 (default) |
| `RepoUnhandledExceptionError` | `RepoExitError` | 1 |
| `SilentRepoExitError` | `RepoExitError` | (base class, not raised directly) |
| `ManifestParseError` | `RepoExitError` | 2 |
| `ManifestInvalidRevisionError` | `ManifestParseError` | 3 |
| `ManifestInvalidPathError` | `ManifestParseError` | 4 |
| `NoManifestException` | `RepoExitError` | 5 |
| `GitAuthError` | `RepoExitError` | 6 |
| `DownloadError` | `RepoExitError` | 7 |
| `InvalidArgumentsError` | `RepoExitError` | 8 |
| `SyncError` | `RepoExitError` | 9 |
| `UpdateManifestError` | `RepoExitError` | 10 |
| `NoSuchProjectError` | `RepoExitError` | 11 |
| `InvalidProjectGroupsError` | `RepoExitError` | 12 |
| `UsageError` | `RepoExitError` | 13 |
| `AbandonError` | `RepoExitError` | 14 |
| `CheckoutCommandError` | `RepoExitError` | 15 |
| `MissingBranchError` | `RepoExitError` | 16 |
| `DownloadCommandError` | `RepoExitError` | 17 |
| `GrepCommandError` | `SilentRepoExitError` | 18 |
| `StartError` | `RepoExitError` | 19 |
| `UploadExitError` | `SilentRepoExitError` | 20 |
| `SuperprojectError` | `SyncError` | 21 |
| `SyncFailFastError` | `SyncError` | 22 |
| `SmartSyncError` | `SyncError` | 23 |
| `SelfupdateError` | `RepoExitError` | 24 |
| `wipe.Error` | `RepoExitError` | 25 |
| `FetchFileError` | `RepoExitError` | 26 |
| `GitRequireError` | `RepoExitError` | 126 |

