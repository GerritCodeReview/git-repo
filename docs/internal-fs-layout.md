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

*   `config`: Per-repo client checkout settings using [git-config] file format.
*   `.repo_config.json`: JSON cache of the `config` file for repo to
    read/process quickly.

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

*   `manifest.xml`: The manifest that repo uses.  It is generated at `repo init`
    and uses the `--manifest-name` to determine what manifest file to load next
    out of `manifests/`.

    Do not try to modify this to load other manifests as it will confuse repo.
    If you want to switch manifest files, re-run `repo init` with the new
    setting.

    Older versions of repo managed this with symlinks.

*   `manifest.xml -> manifests/<manifest-name>.xml`: A symlink to the manifest
    that the user wishes to sync.  It is specified at `repo init` time via
    `--manifest-name`.


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
    setting in the manifest (i.e. the path on the remote server) with a `.git`
    suffix.  This allows for multiple checkouts of the same remote git repo to
    share their objects.  For example, you could have different branches of
    `foo/bar.git` checked out to `foo/bar-master`, `foo/bar-release`, etc...
    There will be multiple trees under `projects/` for each one, but only one
    under `project-objects/`.

    This layout is designed to allow people to sync against different remotes
    (e.g. a local mirror & a public review server) while avoiding duplicating
    the content.  However, this can run into problems if different remotes use
    the same path on their respective servers.  Best to avoid that.
*   `subprojects/`: Like `projects/`, but for git submodules.
*   `subproject-objects/`: Like `project-objects/`, but for git submodules.
*   `worktrees/`: Bare checkouts of every project synced by the manifest.  The
    filesystem layout matches the `<project name=...` setting in the manifest
    (i.e. the path on the remote server) with a `.git` suffix.  This has the
    same advantages as the `project-objects/` layout above.

    This is used when git worktrees are enabled.

### Global settings

The `.repo/manifests.git/config` file is used to track settings for the entire
repo client checkout.
Most settings use the `[repo]` section to avoid conflicts with git.
User controlled settings are initialized when running `repo init`.

| Setting           | `repo init` Option        | Use/Meaning |
|-------------------|---------------------------|-------------|
| manifest.groups   | `--groups` & `--platform` | The manifest groups to sync |
| repo.archive      | `--archive`               | Use `git archive` for checkouts |
| repo.clonefilter  | `--clone-filter`          | Filter setting when using [partial git clones] |
| repo.depth        | `--depth`                 | Create shallow checkouts when cloning |
| repo.dissociate   | `--dissociate`            | Dissociate from any reference/mirrors after initial clone |
| repo.mirror       | `--mirror`                | Checkout is a repo mirror |
| repo.partialclone | `--partial-clone`         | Create [partial git clones] |
| repo.reference    | `--reference`             | Reference repo client checkout |
| repo.submodules   | `--submodules`            | Sync git submodules |
| repo.worktree     | `--worktree`              | Use `git worktree` for checkouts |
| user.email        | `--config-name`           | User's e-mail address; Copied into `.git/config` when checking out a new project |
| user.name         | `--config-name`           | User's name; Copied into `.git/config` when checking out a new project |

[partial git clones]: https://git-scm.com/docs/gitrepository-layout#_code_partialclone_code

### Repo hooks settings

For more details on this feature, see the [repo-hooks docs](./repo-hooks.md).
We'll just discuss the internal configuration settings.
These are stored in the registered `<repo-hooks>` project itself, so if the
manifest switches to a different project, the settings will not be copied.

| Setting                              | Use/Meaning |
|--------------------------------------|-------------|
| repo.hooks.\<hook\>.approvedmanifest | User approval for secure manifest sources (e.g. https://) |
| repo.hooks.\<hook\>.approvedhash     | User approval for insecure manifest sources (e.g. http://) |


For example, if our manifest had the following entries, we would store settings
under `.repo/projects/src/repohooks.git/config` (which would be reachable via
`git --git-dir=src/repohooks/.git config`).
```xml
  <project path="src/repohooks" name="chromiumos/repohooks" ... />
  <repo-hooks in-project="chromiumos/repohooks" ... />
```

If `<hook>` is `pre-upload`, the `.git/config` setting might be:
```ini
[repo "hooks.pre-upload"]
	approvedmanifest = https://chromium.googlesource.com/chromiumos/manifest
```

## Per-project settings

These settings are somewhat meant to be tweaked by the user on a per-project
basis (e.g. `git config` in a checked out source repo).

Where possible, we re-use standard git settings to avoid confusion, and we
refrain from documenting those, so see [git-config] documentation instead.

See `repo help upload` for documentation on `[review]` settings.

The `[remote]` settings are automatically populated/updated from the manifest.

The `[branch]` settings are updated by `repo start` and `git branch`.

| Setting                       | Subcommands   | Use/Meaning |
|-------------------------------|---------------|-------------|
| review.\<url\>.autocopy       | upload        | Automatically add to `--cc=<value>` |
| review.\<url\>.autoreviewer   | upload        | Automatically add to `--reviewers=<value>` |
| review.\<url\>.autoupload     | upload        | Automatically answer "yes" or "no" to all prompts |
| review.\<url\>.uploadhashtags | upload        | Automatically add to `--hashtag=<value>` |
| review.\<url\>.uploadlabels   | upload        | Automatically add to `--label=<value>` |
| review.\<url\>.uploadnotify   | upload        | [Notify setting][upload-notify] to use |
| review.\<url\>.uploadtopic    | upload        | Default [topic] to use |
| review.\<url\>.username       | upload        | Override username with `ssh://` review URIs |
| remote.\<remote\>.fetch       | sync          | Set of refs to fetch |
| remote.\<remote\>.projectname | \<network\>   | The name of the project as it exists in Gerrit review |
| remote.\<remote\>.pushurl     | upload        | The base URI for pushing CLs |
| remote.\<remote\>.review      | upload        | The URI of the Gerrit review server |
| remote.\<remote\>.url         | sync & upload | The URI of the git project to fetch |
| branch.\<branch\>.merge       | sync & upload | The branch to merge & upload & track |
| branch.\<branch\>.remote      | sync & upload | The remote to track |

## ~/ dotconfig layout

Repo will create & maintain a few files in the user's home directory.

*   `.repoconfig/`: Repo's per-user directory for all random config files/state.
*   `.repoconfig/config`: Per-user settings using [git-config] file format.
*   `.repoconfig/keyring-version`: Cache file for checking if the gnupg subdir
    has all the same keys as the repo launcher.  Used to avoid running gpg
    constantly as that can be quite slow.
*   `.repoconfig/gnupg/`: GnuPG's internal state directory used when repo needs
    to run `gpg`.  This provides isolation from the user's normal `~/.gnupg/`.

*   `.repoconfig/.repo_config.json`: JSON cache of the `.repoconfig/config`
    file for repo to read/process quickly.
*   `.repo_.gitconfig.json`: JSON cache of the `.gitconfig` file for repo to
    read/process quickly.


[git-config]: https://git-scm.com/docs/git-config
[manifest-format.md]: ./manifest-format.md
[local manifests]: ./manifest-format.md#Local-Manifests
[topic]: https://gerrit-review.googlesource.com/Documentation/intro-user.html#topics
[upload-notify]: https://gerrit-review.googlesource.com/Documentation/user-upload.html#notify
