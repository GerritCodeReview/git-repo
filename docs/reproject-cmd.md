# Reproject Command Contract

The `repo.reprojectcmd` configuration names a command that `repo sync` runs
instead of Git to move a project's index and worktree to the tree of the
target commit. It is the checkout-side counterpart of `repo.fetchcmd` (see
`docs/fetch-cmd.md`): together they let an external tool take over both the
network fetch and the materialization of a project. This is useful on
virtualized filesystems that address content by hash, where a tree can be
materialized far faster than `git checkout` can write every file.

The command only materializes the tree. `repo` then makes the ref write that
Git would have made, using `git update-ref`.

## Configuration

To use this feature, set the following in `.repo/manifests.git/config`:
```ini
[repo]
	reprojectcmd = "your custom command here"
	uselocalgitdirs = true
```
Setting `repo.reprojectcmd` **requires** `repo.uselocalgitdirs` to be set to
`true`.

For reference, this command does with Git what `repo` would otherwise do
itself:
```ini
[repo]
	reprojectcmd = "git -C $REPO_PATH read-tree -m -u $REPO_TREV"
	uselocalgitdirs = true
```
The one-tree merge applies the change to the target, keeps local changes to
every other path, and refuses to overwrite a modified or untracked file, so it
enforces the preconditions below by itself. It also works for a project that
has nothing checked out yet.

## Environment Variables

The command is executed in a subshell, from the root of the client, populated
with standard project-context environment variables. For details on standard
variables (such as `REPO_PROJECT`, `REPO_PATH`, `REPO_REMOTE`, etc.), see the
Environment section in `repo help forall` or `subcmds/forall.py`.

The variables the command typically needs are:

*   `REPO_PATH`: The project path relative to the root of the client.
*   `REPO_TREV`: The target revision resolved to a full commit hash. Match this
    commit's tree.

There is no force mode: a project that would need one never reaches the
command (see the preconditions below).

## When the command runs

`repo sync` already classifies each project and picks a Git operation. The
command replaces the three that are a materialization of a target tree:

1.  The checkout that detaches HEAD at the target. This is the common case: a
    project on a detached HEAD, a project on a branch that does not track
    upstream, and `repo sync -d`.
2.  The fast-forward of the checked out branch to the target.
3.  The hard reset of the checked out branch to the target, when the commits
    it carried were dropped upstream.

After the command exits 0, `repo` writes the ref itself: it detaches `HEAD` at
`REPO_TREV`, or moves the checked out branch to `REPO_TREV`.

The command is **not** run:

*   When `HEAD` already names `REPO_TREV`.
*   At the fast-forward step when `HEAD` is ahead of `REPO_TREV`, where Git's
    merge would be a no-op.
*   For a rebase. A branch carrying local commits has them replayed onto the
    target by `git rebase`, which is not a materialization of a target tree.
*   For `MetaProject`s (i.e. the internal `repo` repository itself at
    `.repo/repo` and the `manifests` repository at `.repo/manifests`).

## Contract

### Preconditions

Before invoking the command, `repo` ensures that:

*   The index has no staged changes (the index matches `HEAD`, or is empty on an unborn `HEAD`).
*   No rebase, cherry-pick, merge, or revert is in progress.

Detecting collisions with untracked files or unstaged working-tree modifications is the responsibility of the reproject command itself (e.g. via `git read-tree -m -u $REPO_TREV` or a custom virtual filesystem checkout tool). If local changes collide with the target tree, the command must abort with a non-zero exit code. Local modifications and untracked files outside the diff between `HEAD` and `REPO_TREV` must be preserved.

### Postconditions on exit 0

After the command exits with status 0, `repo` expects the following
postconditions to be met:

1.  `git diff-index --quiet --cached REPO_TREV^{tree}` exits 0 (the index
    matches the target tree).
2.  `HEAD` still names what it did before the command, and its resolved commit
    object ID has not changed.

### Invariants

The command may modify the worktree and the index, and may write project-local
Git config. The command must:

*   Apply the change from `HEAD`'s tree to `REPO_TREV`'s tree and leave every
    other path alone. Local modifications and untracked files outside that
    change must survive: the command applies a diff, it does not reset the
    tree.
*   Not write any ref, including `HEAD` and `ORIG_HEAD`. `repo` owns every ref
    write.
*   Not create or replace `.git/`, and not touch anything under `.repo/`.
*   Not require the Git remote, to preserve `repo sync --local-only`.
*   Be idempotent. Running it twice on the same target is a no-op.

### Failure

*   A non-zero exit status, a failed precondition or a failed postcondition
    fails that project's sync, and the command's or Git's output is surfaced
    to the user.
*   Other projects continue, and `repo sync` exits non-zero.

## Limitations

Nested projects are out of scope: a project whose path lies inside another
project's path, a `<project>` nested in another `<project>` in the manifest,
and a submodule discovered with `sync-s` or `--recurse-submodules`. `repo sync`
fails if the manifest has one while `repo.reprojectcmd` is set.
