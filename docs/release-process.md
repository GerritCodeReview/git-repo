# repo release process

This is the process for creating a new release of repo, as well as all the
related topics and flows.

[TOC]

## Schedule

New releases are normally cut from the `main` branch once a week (currently on
Tuesday mornings [US PT]), subject to the [release freezes](#freeze) below.
Additional releases may be made as needed, e.g. when there's a known issue the
maintainers know should get fixed.
If you find a fix has been merged for an issue important to you, but hasn't been
released after a week or so, feel free to [contact] us to request a new release.

### Release Freezes {#freeze}

We try to observe a regular schedule for when **not** to release.
If something goes wrong, staff need to be active in order to respond quickly &
effectively.
We also don't want to disrupt non-Google organizations if possible.

We generally follow the rules:

* Release during Mon - Thu, 9:00 - 14:00 [US PT]
* Avoid holidays
  * All regular [US holidays]
  * Large international ones if possible
  * All the various [New Years]
    * Jan 1 in Gregorian calendar is the most obvious
    * Check for large Lunar New Years too
* Follow the normal [Google production freeze schedule]

[US holidays]: https://en.wikipedia.org/wiki/Federal_holidays_in_the_United_States
[US PT]: https://en.wikipedia.org/wiki/Pacific_Time_Zone
[New Years]: https://en.wikipedia.org/wiki/New_Year
[Google production freeze schedule]: http://goto.google.com/prod-freeze

## Launcher script

The main repo script serves as a standalone program and is often referred to as
the "launcher script".
This makes it easy to copy around and install as you don't have to install any
other files from the git repo.

Whenever major changes are made to the launcher script, you should increment the
`VERSION` variable in the launcher itself.
At runtime, repo will check this to see if it needs to be updated (and notify
the user automatically).

### Checking if a launcher update is needed

The launcher is published separately from the rest of repo, so a release of
repo doesn't automatically mean a new launcher needs to be published.
Compare the version of the currently published launcher with the one in the
tree:

```sh
# The currently published launcher.
$ curl -s https://storage.googleapis.com/git-repo-downloads/repo | \
    python3 - --version | grep launcher
# The launcher in the current checkout.
$ ./repo --version | grep launcher
```

If the version in the tree is newer, then a new launcher should be published.

### Publishing a new launcher

*** note
Publishing requires write access to the `git-repo-downloads` Google Cloud
Storage bucket, which only official maintainers have.
***

1.  Sign the launcher using the release keys (see [Key management](#keys)).
    This creates a detached `repo.asc` signature next to `repo`, and prints the
    exact `gcloud` commands to use for the following steps.

    ```sh
    $ ./release/sign-launcher.py
    ```

2.  Upload the launcher with its version suffix (e.g. `repo-2.71`) first.
    This makes it available for early testing without changing the default.

3.  Once it has been tested, copy the versioned launcher over the default
    `repo` & `repo.asc` files so everyone gets it.

4.  Make sure the files are publicly accessible and properly signed.

    ```sh
    $ curl -O "https://storage.googleapis.com/git-repo-downloads/repo{,.asc}"
    $ gpg --verify repo.asc
    ```

If a rollback is necessary, the bucket archives old versions.
The output of `sign-launcher.py` shows how to restore them.

### Launcher mirrors

The launcher is also copied into other projects, so updates will eventually
show up in places such as:

*   [Chromium depot_tools]: Automatically synced, but each update requires
    manual review.
*   [Chromium OS repo]: Chromium OS fork of the repo project.
    It rolls in changes for CrOS while upstream discussion/merging is ongoing.
    See [managing the fork] for how it's updated.

## Key management {#keys}

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
*   `--repo-rev`: This tells repo which branch to use for the full project.
    It defaults to the `stable` branch (`REPO_REV` in the launcher script).

Whenever `repo sync` is run, repo will, once every 24 hours, see if an update
is available.
It fetches the latest repo-rev from the repo-url.
Then it verifies that the latest commit in the branch has a valid signed tag
using `git tag -v` (which uses gpg).
If the tag is valid, then repo will update its internal checkout to it.

If the latest commit doesn't have a signed tag, repo will fall back to the
most recent tag it can find (via `git describe`).
If that tag is valid, then repo will warn and use that commit instead.

If that tag cannot be verified, it gives up and forces the user to resolve.

If env variable `REPO_SKIP_SELF_UPDATE` is defined, this will
bypass the self update algorithm.

### Force an update

The `repo selfupdate` command can be used to force an immediate update.
It is not subject to the 24 hour limitation.

## Branch management

All development happens on the `main` branch and should generally be stable.

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
Typically all tags are made against the `main` branch and then pushed to the
`stable` branch to make it available to the rest of the world.
Since repo doesn't typically see a lot of changes, this tends to be OK.

## Creating a new release

When you want to create a new release, you'll need to select a good version and
create a signed tag using a key registered in repo itself.
Typically we just tag the latest version of the `main` branch.
The tag is then tested & pushed for early testing before the release is made
available to everyone via the `stable` branch.

The steps below assume you're starting from a fresh directory.

### Creating a signed tag

Lets assume your keys live in a dedicated directory, e.g. `~/.gnupg/repo/`.
This is the default location used by the scripts under `release/`.

*** note
If you need access to the official keys, check out the internal documentation
at [go/repo-release].
Note that only official maintainers of repo will have access as it describes
internal processes for accessing the restricted keys.
***

```sh
# Make sure the release keys are available.
$ gpg --homedir ~/.gnupg/repo -K

$ git clone https://gerrit.googlesource.com/git-repo
$ cd git-repo

# Tell git to sort tags by version instead of lexically, then look at the most
# recent releases to pick the new version.
$ git config tag.sort version:refname
$ git tag --list | tail -n5
$ t=v2.XX

# Create a new signed tag against the latest main branch.
# The script will verify the tag & display a summary of changes since the last
# release.
$ ./release/sign-tag.py $t origin/main

# Verify the signed tag.
$ git show $t
```

### Testing the release

Before pushing anything, use the local checkout to test both updating an
existing checkout and creating a fresh one.
Any manifest will do; the Android one is used here as it's large.

Since `--repo-rev` defaults to `stable`, the local checkout's `stable` branch
is what gets used.

To test updating an existing checkout from the current release:

```sh
$ cd git-repo
$ git checkout stable
$ git reset --hard origin/stable
$ cd ..

$ mkdir update
$ cd update
$ repo init -u https://android.googlesource.com/platform/manifest \
    --repo-url "file://$(pwd)/../git-repo"
$ repo sync -j32

# Move the local stable branch to the new release & update to it.
$ git -C ../git-repo reset --hard $t^0
$ repo selfupdate
$ repo sync -j32
$ cd ..
```

To test a fresh checkout with the new release:

```sh
$ git -C git-repo checkout stable
$ git -C git-repo reset --hard $t^0

$ mkdir fresh
$ cd fresh
$ repo init -u https://android.googlesource.com/platform/manifest \
    --repo-url "file://$(pwd)/../git-repo"
$ repo sync -j32
$ cd ..
```

### Push the new release

*** note
Avoid pushing new releases during [release freezes](#freeze).
***

First push the tag by itself.
This doesn't affect most users, but makes the release available to people
testing new releases early (e.g. by tracking `main`).
Run with `-n` first to make sure it's going to push what you expect.

```sh
$ cd git-repo
$ git push -n https://gerrit-review.googlesource.com/git-repo $t
$ git push https://gerrit-review.googlesource.com/git-repo $t
```

Then [announce the release](#announce).
It's advisable to wait a day after pushing the tag to get enough signal from
early testers before making it available to everyone.

Once you're ready to make the release available to everyone, push it to the
`stable` branch.
People will start upgrading to this version immediately.

Make sure you never push the tag itself to the stable branch!
Only push the commit -- note the use of `^0` below.

```sh
$ git push -n https://gerrit-review.googlesource.com/git-repo $t^0:stable
$ git push https://gerrit-review.googlesource.com/git-repo $t^0:stable
```

*** note
If pushing directly to the `stable` branch is rejected, official maintainers
should check [go/repo-release] for how to update it instead.
***

Finally, reply to the announcement thread to let people know that the release
has been promoted to `stable`.

### Rolling back a release

If something goes horribly wrong, you can force push the previous version to the
`stable` branch and people should automatically recover.
Again, make sure you never push the tag itself!

```sh
# Roll back to the release before $t.
$ oldrev=$(git describe --abbrev=0 $t^0~)
# Or roll back to a specific release.
$ oldrev=v2.XX

$ git push -n https://gerrit-review.googlesource.com/git-repo $oldrev^0:stable --force
$ git push https://gerrit-review.googlesource.com/git-repo $oldrev^0:stable --force
```

### Announce the release {#announce}

Once you push a new release, make sure to announce it on the
[repo-discuss@googlegroups.com] group.
Here is an [example announcement].

You can create a short changelog since the previous release using the command:

```sh
$ prev=$(git describe --abbrev=0 $t^0~)
$ git log --decorate-refs=refs/tags/ --format="%h (%aN) %s %d" --no-merges \
    $prev..$t
```

[contact]: ../README.md#contact
[example announcement]: https://groups.google.com/d/topic/repo-discuss/UGBNismWo1M/discussion
[repo-discuss@googlegroups.com]: https://groups.google.com/forum/#!forum/repo-discuss
[go/repo-release]: https://goto.google.com/repo-release
[Chromium depot_tools]: https://chromium.googlesource.com/chromium/tools/depot_tools/
[Chromium OS repo]: https://chromium.googlesource.com/external/repo/
[managing the fork]: https://www.chromium.org/chromium-os/developer-library/reference/tools/repo-tool/#managing-our-fork
