# Repo internal filesystem layout

A reference to the `.repo/` tree in repo client checkouts.
Hopefully it's complete & up-to-date, but who knows!

*** note
**Warning**:
This is meant for developers of the repo project itself as a quick reference.
**Nothing** in here must be construed as ABI, or that repo itself will never
change its internals in backwards incompatible ways.
***

[TOC]

## .repo/ layout

All content under `.repo/` is managed by `repo` itself with few exceptions.

In general, you should not make manual changes in here.
If a setting was initialized using an option to `repo init`, you should use that
command to change the setting later on.
It is always safe to re-run `repo init` in existing repo client checkouts.
For example, if you want to change the manifest branch, you can simply run
`repo init --manifest-branch=<new name>` and repo will take care of the rest.

### repo/ state

*   `repo/`: A git checkout of the repo project.  This is how `repo` re-execs
    itself to get the latest released version.

    It tracks the git repository at `REPO_URL` using the `REPO_REV` branch.
    Those are specified at `repo init` time using the `--repo-url=<REPO_URL>`
    and `--repo-branch=<REPO_REV>` options.

    Any changes made to this directory will usually be automatically discarded
    by repo itself when it checks for updates.  If you want to update to the
    latest version of repo, use `repo selfupdate` instead.  If you want to
    change the git URL/branch that this tracks, re-run `repo init` with the new
    settings.

*   `.repo_fetchtimes.json`: Used by `repo sync` to record stats when syncing
    the various projects.

### Manifests

For more documentation on the manifest format, including the local_manifests
support, see the [manifest-format.md] file.

*   `manifests/`: A git checkout of the manifest project.  Its `.git/` state
    points to the `manifest.git` bare checkout (see below).  It tracks the git
    branch specified at `repo init` time via `--manifest-branch`.

    The local branch name is always `default` regardless of the remote tracking
    branch.  Do not get confused if the remote branch is not `default`, or if
    there is a remote `default` that is completely different!

    No manual changes should be made in here as it will just confuse repo and
    it won't automatically recover causing no new changes to be picked up.

*   `manifests.git/`: A bare checkout of the manifest project.  It tracks the
    git repository specified at `repo init` time via `--manifest-url`.

    No manual changes should be made in here as it will just confuse repo.
    If you want to switch the tracking settings, re-run `repo init` with the
    new settings.

*   `manifest.xml -> manifests/<manifest-name>.xml`: A symlink to the manifest
    that the user wishes to sync.  It is specified at `repo init` time via
    `--manifest-name`.

    Do not try to repoint this symlink to other files as it will confuse repo.
    If you want to switch manifest files, re-run `repo init` with the new
    setting.

*   `manifests.git/.repo_config.json`: JSON cache of the `manifests.git/config`
    file for repo to read/process quickly.

*   `local_manifest.xml` (*Deprecated*): User-authored tweaks to the manifest
    used to sync.  See [local manifests] for more details.
*   `local_manifests/`: Directory of user-authored manifest fragments to tweak
    the manifest used to sync.  See [local manifests] for more details.

### Project objects

*   `project.list`: Tracking file used by `repo sync` to determine when projects
    are added or removed and need corresponding updates in the checkout.
*   `projects/`: Bare checkouts of every project synced by the manifest.  The
    filesystem layout matches the `<project path=...` setting in the manifest
    (i.e. where it's checked out in the repo client source tree).  Those
    checkouts will symlink their `.git/` state to paths under here.

    Some git state is further split out under `project-objects/`.
*   `project-objects/`: Git objects that are safe to share across multiple
    git checkouts.  The filesystem layout matches the `<project name=...`
    setting in the manifest (i.e. the path on the remote server).  This allows
    for multiple checkouts of the same remote git repo to share their objects.
    For example, you could have different branches of `foo/bar.git` checked
    out to `foo/bar-master`, `foo/bar-release`, etc...  There will be multiple
    trees under `projects/` for each one, but only one under `project-objects/`.

    This can run into problems if different remotes use the same path on their
    respective servers ...
*   `subprojects/`: Like `projects/`, but for git submodules.
*   `subproject-objects/`: Like `project-objects/`, but for git submodules.

## ~/ dotconfig layout

Repo will create & maintain a few files in the user's home directory.

*   `.repoconfig/`: Repo's per-user directory for all random config files/state.
*   `.repoconfig/keyring-version`: Cache file for checking if the gnupg subdir
    has all the same keys as the repo launcher.  Used to avoid running gpg
    constantly as that can be quite slow.
*   `.repoconfig/gnupg/`: GnuPG's internal state directory used when repo needs
    to run `gpg`.  This provides isolation from the user's normal `~/.gnupg/`.

*   `.repo_.gitconfig.json`: JSON cache of the `.gitconfig` file for repo to
    read/process quickly.


[manifest-format.md]: ./manifest-format.md
[local manifests]: ./manifest-format.md#Local-Manifests
