# repo workspace

`repo workspace` gives you a second, independent checkout of a project that
appears at the project's normal path, with its own `out/` directory, inside a
private shell.  It exists for source trees whose build system keys its state
on absolute paths (Android's Soong is the motivating case): a plain
`git worktree` elsewhere on disk is scanned as a duplicate or loses its
incremental build state, and a second repo client costs a full copy of the
tree.

[TOC]

## Quick start

```sh
$ cd packages/modules/HealthFitness
$ repo workspace create fix-crash
Created workspace 'fix-crash' for packages/modules/HealthFitness on branch 'fix-crash'
Entering workspace 'fix-crash' (type 'exit' to leave)
$ git status          # on branch fix-crash, same path as before
$ m my-module         # builds into this workspace's own out/
$ repo upload .       # repo sees the workspace branch
$ exit
```

While the workspace shell is open, the main checkout and any other workspaces
are untouched; each has its own files and its own `out/`.  Re-enter later
with `repo workspace enter fix-crash`.

## Commands

```
repo workspace create <name> [-b <branch>] [-r <rev>|--head] [<project>]
repo workspace enter  <name>
repo workspace run    <name> -- <command>...
repo workspace list   [--size]
repo workspace remove <name> [--force]
repo workspace clean  [<name>] [--all] [--days <n>] [-y]
repo workspace status
```

*   `create` makes a linked git worktree on a new branch (default name: the
    workspace name; default start point: the project's manifest revision,
    exactly like `repo start`) and enters it.  `--head` starts from the main
    checkout's current commit instead.  `--no-enter` skips the shell.
*   `enter` starts `$SHELL` in the overlay, in your current directory.
*   `run` executes one command in the overlay and returns its exit status;
    use it from scripts and automation.
*   `list` shows workspaces for this client; `*` marks the one you are in.
*   `remove` deletes the worktree, its `out/`, and the branch.  If there are
    uncommitted changes or commits not in the manifest revision it asks first
    (or requires `--force`).
*   `clean` wipes build output that has been idle for `--days` (default 7, or
    `repo.workspace.cleanDays`) and offers to remove workspaces that have no
    local changes or commits.
*   `status` reports whether you are inside a workspace.

Inside a workspace these variables are set:

*   `REPO_WORKSPACE`: the workspace name.
*   `REPO_WORKSPACE_PROJECT`: the project path relative to the client root.
*   `REPO_WORKSPACE_DIR`: the state directory under `.repo/workspaces/`.

A prompt hint for bash (`~/.bashrc`):

```sh
PS1='${REPO_WORKSPACE:+[$REPO_WORKSPACE] }'"$PS1"
```

## How it works

`create` runs `git worktree add` with the worktree stored under
`.repo/workspaces/<name>/<project path>/`, so nothing new appears in the
source tree.  `enter` and `run` then fork a child that:

1.  creates a user namespace mapping only your own uid and gid, and a mount
    namespace (`unshare(CLONE_NEWUSER | CLONE_NEWNS)`), with all mounts made
    private so nothing propagates back to the host;
2.  bind-mounts the worktree over the project's path;
3.  bind-mounts `.repo/workspaces/<name>/out/` over `<client>/out/`;
4.  sets `PR_SET_NO_NEW_PRIVS` and executes your shell or command.

Only Linux syscalls are used; there are no helper binaries and no privileges
involved.  Every mount is checked and the shell is not started if any step
fails, so a workspace shell never silently shares `out/` with the host.

### Runtime directory preservation

Inside a single-uid user namespace every file you do not own appears to be
owned by the overflow user.  Credential helpers and IPC libraries that verify
the ownership of a file's parent directories then reject anything under the
root-owned `/run`.  To keep such tools working, the overlay replaces `/run`
with a tmpfs you own and re-exposes from the host:

*   entries directly under `/run`, or one level below, that you own
    (for example `/run/user/<uid>`);
*   Unix domain sockets at those depths (for example
    `/run/dbus/system_bus_socket`);
*   whatever `$XDG_RUNTIME_DIR`, `$SSH_AUTH_SOCK`, `$XAUTHORITY` and
    `$DBUS_SESSION_BUS_ADDRESS` point at, if under `/run`;
*   the real file behind `/etc/resolv.conf`, if under `/run`;
*   any path listed in the `repo.workspace.bind` git config key.

`/tmp` and everything else are left exactly as on the host.  Set
`repo.workspace.preserveRuntime` to `false` to skip this step entirely.

### Working with `repo sync`

Run `repo sync` in the main checkout as usual.  Git will not let `sync`,
`repo abandon` or `repo prune` check out or delete a branch that is checked
out in a workspace, so live workspaces are safe.  To bring a workspace up to
date, enter it and `git rebase` onto the project's upstream (for example
`git rebase goog/main`).

If a manifest change removes or moves the project, `repo workspace list`
flags the workspace; remove it or recreate it after the sync.

## Requirements and limitations

*   Linux with unprivileged user namespaces enabled.  If
    `unshare(CLONE_NEWUSER)` is refused, repo prints the sysctl responsible
    (`kernel.unprivileged_userns_clone`,
    `kernel.apparmor_restrict_unprivileged_userns`, or
    `user.max_user_namespaces`).  `create --no-overlay` still makes the
    worktree and prints its path.
*   git 2.15 or newer (the same requirement as `repo init --worktree`).
*   One project per workspace in this version.
*   Nothing is isolated except the project path, `out/`, and `/run`; network,
    `/tmp`, home directory and devices are shared with the host.  Nested
    sandboxes (browsers, build sandboxes, bwrap) work inside a workspace.
*   `repo workspace` is unrelated to `repo init --worktree`, which changes how
    repo stores `.git` for every project; both layouts are supported.

## Configuration

Git config keys, read through the normal chain (so `.repo/manifests.git/config`,
`~/.gitconfig` and `/etc/gitconfig` all work):

| Key                              | Default | Meaning                                  |
|----------------------------------|---------|------------------------------------------|
| `repo.workspace.preserveRuntime` | `true`  | Apply the `/run` preservation policy.    |
| `repo.workspace.bind`            |         | Extra host path(s) under `/run` to keep. |
| `repo.workspace.cleanDays`       | `7`     | Idle threshold for `clean`.              |

## Layout

```
.repo/workspaces/<name>/
    <project path>/     the linked worktree
    out/                this workspace's build output (contains .out-dir)
    workspace.json      project, branch, timestamps
```

Git's own metadata for the worktree lives where `git worktree` puts it:
`.repo/projects/<path>.git/worktrees/<n>/` in the default layout, or
`.repo/worktrees/<name>.git/worktrees/<n>/` in `--worktree` clients.
