# Fetch Command Contract

The `repo.fetchcmd` configuration allows specifying a custom command to be
executed during `repo sync` to fetch objects, instead of using standard
`git fetch`. This is particularly useful in environments with virtualized
filesystems or lazy checkouts where fetching metadata and downloading file
contents should be decoupled.

## Configuration

To use this feature, set the following in `.repo/manifests.git/config`:
```ini
[repo]
	fetchcmd = "your custom command here"
	uselocalgitdirs = true
```
Setting `repo.fetchcmd` **requires** `repo.uselocalgitdirs` to be set to `true`.

## Environment Variables

The custom command is executed in a subshell populated with standard
project-context environment variables. For details on standard variables (such
as `REPO_PROJECT`, `REPO_PATH`, `REPO_PROJECT_FETCH_URL`, etc.), see the
Environment section in `repo help forall` or `subcmds/forall.py`.

The following environment variable is specific to `repo.fetchcmd`:

*   `REPO_TREV`: The target revision resolved to a full commit hash.

## Contract

### Postconditions on exit 0

After the fetch command exits with status 0, `repo` expects the following
postconditions to be met:

1.  `git cat-file -e REPO_TREV` succeeds (the commit must exist in the object
    store).
2.  The mapped local tracking ref (e.g. `refs/remotes/REPO_REMOTE/<branch>`
    for a branch revision, or the tag ref itself for a tag) must point to
    `REPO_TREV`.
3.  `FETCH_HEAD` must point to `REPO_TREV`.
4.  The commit graph from `REPO_TREV` must be reachable far enough to compute
    merge bases with local branches.

### Invariants

*   The command should be idempotent; fetching the same `REPO_TREV` twice should
    be a no-op.
*   Only `FETCH_HEAD` and `refs/remotes/*` should be modified to preserve
    `repo sync --network-only` semantics. `HEAD` and local branches must not be
    touched by the fetch command.
*   Dirty worktree state must be preserved.
*   The command is **not** executed for `MetaProject`s (i.e. the internal `repo`
    repository itself at `.repo/repo` and the `manifests` repository at
    `.repo/manifests`).

### Failure

*   A non-zero exit status aborts the project's sync, and the command's stderr
    is surfaced to the user.
*   `repo` verifies the tracking ref and target reachability after exit 0. Any
    mismatch is treated as a failure.
