# repo release process

This is the process for creating a new release of repo, as well as all the
related topics and flows.

[TOC]

## Schedule {#schedule}

Releases are automated.
Every Tuesday morning [US PT], a pipeline checks if any new commits have landed
since last release.
If so, it tags & tests the latest `main`, pushes & announces the tag, and then
promotes it to `stable` a day later.
The release is skipped if there's a holiday or [production freeze](#freeze)
that week.
Maintainers can also trigger it by hand.
The [manual steps](#manual) below are only needed as a fallback, or to roll
back a release.

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

When `VERSION` changes, the release pipeline publishes the new launcher to the
`git-repo-downloads` Google Cloud Storage bucket.
To publish it by hand, run `./release/sign-launcher.py`, which signs the
launcher and prints the commands to upload it.

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

If the env variable `REPO_SKIP_SELF_UPDATE` is set to anything other than `0`,
`repo sync` will bypass the self update algorithm.

### Force an update

The `repo selfupdate` command can be used to force an immediate update.
It is not subject to the 24 hour limitation.

## Branch management

All development happens on the `main` branch and should generally be stable.

Since the repo launcher defaults to tracking the `stable` branch, it is not
normally updated until a new release is available.
If something goes wrong with a new release, `stable` can be pointed back at an
older release and clients will automatically downgrade.

We don't have parallel release branches/series.
Typically all tags are made against the `main` branch and then promoted to the
`stable` branch to make it available to the rest of the world.
Since repo doesn't typically see a lot of changes, this tends to be OK.

## Creating a new release {#manual}

Releases are normally created automatically (see [Schedule](#schedule)).
If you need to create one by hand, you'll need to select a good version and
create a signed tag using a key registered in repo itself.
Typically we just tag the latest version of the `main` branch.

### Creating a signed tag

Lets assume your keys live in a dedicated directory, e.g. `~/.gnupg/repo/`.

*** note
If you need access to the official keys, check out the internal documentation
at [go/repo-release].
Note that only official maintainers of repo will have access as it describes
internal processes for accessing the restricted keys.
***

```sh
# Pick the new version.
$ t=v2.XX

# Create a new signed tag of the latest main branch.
$ ./release/sign-tag.py $t origin/main

# Verify the signed tag.
$ git show $t
```

### Push the new release

First push the tag, [announce](#announce) it, and wait a day to get feedback
from people testing new releases early.

```sh
$ git push https://gerrit-review.googlesource.com/git-repo $t
```

Then make the release available to everyone by updating the `stable` branch.
Direct pushes to it are rejected, so it has to be deleted & recreated via the
authenticated [Gerrit REST API] (see [go/repo-release] for maintainers).

Make sure you never point the stable branch at the tag itself!
Only use the commit -- note the use of `^0` below.
The commit is resolved before deleting anything so that a bad `$t` can't leave
`stable` missing.

```sh
$ api=https://gerrit-review.googlesource.com/a/projects/git-repo/branches/stable
$ rev=$(git rev-parse --verify "$t^0") && \
    curl --fail -X DELETE "$api" && \
    curl --fail -X PUT -H 'Content-Type: application/json' \
      -d "{\"revision\":\"$rev\"}" "$api"
```

If something goes horribly wrong, run the same commands with the previous
release (e.g. `t=$(git describe --abbrev=0 $t^0~)`) and people should
automatically recover.

### Announce the release {#announce}

Once you push a new release, make sure to announce it on the
[repo-discuss@googlegroups.com] group, and follow up once it's on `stable`.
Here is an [example announcement].

You can create a short changelog since the previous release using the command:

```sh
$ git log --format="%h (%aN) %s" --no-merges \
    $(git describe --abbrev=0 $t^0~)..$t
```

[contact]: ../README.md#contact
[example announcement]: https://groups.google.com/d/topic/repo-discuss/UGBNismWo1M/discussion
[repo-discuss@googlegroups.com]: https://groups.google.com/forum/#!forum/repo-discuss
[go/repo-release]: https://goto.google.com/repo-release
[Gerrit REST API]: https://gerrit-review.googlesource.com/Documentation/rest-api-projects.html#branch-endpoints
