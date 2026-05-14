# Fetch Command Contract

The `repo.fetch_cmd` configuration allows specifying a custom command to be executed during `repo sync` to fetch objects, instead of using standard `git fetch`. This is particularly useful in environments with virtualized Git workspaces or lazy checkouts (like CartFS/Git Workspaces).

## Configuration

To use this feature, set the following in `.repo/manifests.git/config`:
```ini
[repo]
	fetchcmd = "your custom command here"
	uselocalgitdirs = true
```
Setting `repo.fetchcmd` **requires** `repo.uselocalgitdirs` to be set to `true`.

## Environment Variables

The custom command is executed in a subshell populated with the following project-context environment variables:

*   `REPO_PROJECT`: The unique name of the project.
*   `REPO_PATH`: The path relative to the root of the client.
*   `REPO_OUTERPATH`: The path of the sub manifest's root relative to the root of the client.
*   `REPO_INNERPATH`: The path relative to the root of the sub manifest.
*   `REPO_REMOTE`: The name of the remote system from the manifest.
*   `REPO_LREV`: The name of the revision from the manifest, translated to a local tracking branch.
*   `REPO_RREV`: The name of the revision from the manifest, exactly as written in the manifest.
*   `REPO_UPSTREAM`: The name of the upstream branch as specified in the manifest.
*   `REPO_DEST_BRANCH`: The name of the destination branch for code review, as specified in the manifest.
*   `REPO_TREV`: The target revision resolved to a full commit hash.
*   `REPO_PROJECT_FETCH_URL`: The full resolved fetch URL for the project.
*   `REPO__*`: Any extra environment variables specified by the "annotation" element under any project element.

## Contract

### Postconditions on exit 0

After the fetch command exits with status 0, `repo` expects the following postconditions to be met:

1.  `git cat-file -e REPO_TREV` succeeds (the commit must exist in the object store).
2.  `refs/remotes/REPO_REMOTE/REPO_RREV` must point to `REPO_TREV`.
3.  `FETCH_HEAD` must point to `REPO_TREV`.
4.  The commit graph from `REPO_TREV` must be reachable far enough to compute merge bases with local branches.

### Invariants

*   The command should be idempotent; fetching the same `REPO_TREV` twice should be a no-op.
*   Only `FETCH_HEAD` and `refs/remotes/*` should be modified to preserve `repo sync --network-only` semantics. `HEAD` and local branches must not be touched by the fetch command.
*   Dirty worktree state must be preserved.

### Failure

*   A non-zero exit status aborts the project's sync, and the command's stderr is surfaced to the user.
*   `repo` verifies the tracking ref and target reachability after exit 0. Any mismatch is treated as a failure.
