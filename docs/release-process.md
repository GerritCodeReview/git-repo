# repo release process

This is the process for creating a new release of repo, as well as all the
related topics and flows.

[TOC]

## Launcher script

The main repo script serves as a standalone program and is often referred to as
the "launcher script".
This makes it easy to copy around and install as you don't have to install any
other files from the git repo.

Whenever major changes are made to the launcher script, you should increment the
`VERSION` variable in the launcher itself.
At runtime, repo will check this to see if it needs to be updated (and notify
the user automatically).

## Key management

Every release has a git tag that is signed with a key that repo recognizes.
Those keys are hardcoded inside of the repo launcher itself -- look for the
`KEYRING_VERSION` and `MAINTAINER_KEYS` settings.

Adding new keys to the repo launcher will allow tags to be recognized by new
keys, but only people using that updated version will be able to.
Since the majority of users will be using an official launcher version, their
version will simply ignore any new signed tags.

If you want to add new keys, it's best to register them long ahead of time,
and then wait for that updated launcher to make its way out to everyone.
Even then, there will be a long tail of users with outdated launchers, so be
prepared for people asking questions.

### Registering a new key

The process of actually adding a new key is quite simple.

1.  Add the public half of the key to `MAINTAINER_KEYS`.
2.  Increment `KEYRING_VERSION` so repo knows it needs to update.
3.  Wait a long time after that version is in a release (~months) before trying
    to create a new release using those new keys.

## Self update algorithm

When creating a new repo checkout with `repo init`, there are a few options that
control how repo finds updates:

*   `--repo-url`: This tells repo where to clone the full repo project itself.
    It defaults to the official project (`REPO_URL` in the launcher script).
*   `--repo-branch`: This tells repo which branch to use for the full project.
    It defaults to the `stable` branch (`REPO_REV` in the launcher script).

Whenever `repo sync` is run, repo will check to see if an update is available.
It fetches the latest repo-branch from the repo-url.
Then it verifies that the latest commit in the branch has a valid signed tag
using `git tag -v` (which uses gpg).
If the tag is valid, then repo will update its internal checkout to it.

If the latest commit doesn't have a signed tag, repo will fall back to the
closest tag it can find (via `git describe`).
If that tag is valid, then repo will warn and use that commit instead.

If that tag cannot be verified, it gives up and forces the user to resolve.

## Branch management

All development happens on the `master` branch and should generally be stable.

Since the repo launcher defaults to tracking the `stable` branch, it is not
normally updated until a new release is available.
If something goes wrong with a new release, an older release can be force pushed
and clients will automatically downgrade.

The `maint` branch is used to track the previous major release of repo.
It is not normally meant to be used by people as `stable` should be good enough.
Once a new major release is pushed to the `stable` branch, then the previous
major release can be pushed to `maint`.
For example, when `stable` moves from `v1.10.x` to `v1.11.x`, then the `maint`
branch will be updated from `v1.9.x` to `v1.10.x`.

We don't have parallel release branches/series.
Typically all tags are made against the `master` branch and then pushed to the
`stable` branch to make it available to the rest of the world.
Since repo doesn't typically see a lot of changes, this tends to be OK.

## Creating a new release

When you want to create a new release, you'll need to select a good version and
create a signed tag using a key registered in repo itself.
Typically we just tag the latest version of the `master` branch.
The tag could be pushed now, but it won't be used by clients normally (since the
default `repo-branch` setting is `stable`).
This would allow some early testing on systems who explicitly select `master`.

### Creating a signed tag

Lets assume your keys live in a dedicated directory, e.g. `~/.gnupg/repo/`.
If you need access to the official keys, check out [go/repo-release].

```sh
# Set the gpg key directory.
$ export GNUPGHOME=~/.gnupg/repo/

# Verify the listed key is “Repo Maintainer”.
$ gpg -K

# Pick whatever branch or commit you want to tag.
$ r=master

# Pick the new version.
$ t=1.12.10

# Create the signed tag.
$ git tag -s v$t -u "Repo Maintainer <repo@android.kernel.org>" -m "repo $t" $r

# Verify the signed tag.
$ git show v$t
```

### Push the new release

Once you're ready to make the release available to everyone, push it to the
`stable` branch.

Make sure you never push the tag itself to the stable branch!
Only push the commit -- notice the use of `$t` and `$r` below.

```sh
$ git push https://gerrit-review.googlesource.com/git-repo v$t
$ git push https://gerrit-review.googlesource.com/git-repo $r:stable
```

If something goes horribly wrong, you can force push the previous version to the
`stable` branch and people should automatically recover.
Again, make sure you never push the tag itself!

```sh
$ oldrev="whatever-old-commit"
$ git push https://gerrit-review.googlesource.com/git-repo $oldrev:stable --force
```

### Announce the release

Once you do push a new release to `stable`, make sure to announce it on the
[repo-discuss@googlegroups.com] group.
Here is an [example announcement].

You can create a short changelog using the command:

```sh
# If you haven't pushed to the stable branch yet, you can use origin/stable.
# If you have pushed, change origin/stable to the previous release tag.
$ git log --format="%h (%aN) %s" --no-merges origin/stable..$r
```


[example announcement]: https://groups.google.com/d/topic/repo-discuss/UGBNismWo1M/discussion
[repo-discuss@googlegroups.com]: https://groups.google.com/forum/#!forum/repo-discuss
[repo-release]: https://goto.google.com/repo-release
