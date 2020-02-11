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
most recent tag it can find (via `git describe`).
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

*** note
If you need access to the official keys, check out the internal documentation
at [go/repo-release].
Note that only official maintainers of repo will have access as it describes
internal processes for accessing the restricted keys.
***

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

## Project References

Here's a table showing the relationship of major tools, their EOL dates, and
their status in Ubuntu & Debian.
Those distros tend to be good indicators of how long we need to support things.

Things in bold indicate stuff to take note of, but does not guarantee that we
still support them.
Things in italics are things we used to care about but probably don't anymore.

|   Date   |     EOL      | [Git][rel-g] | [Python][rel-p] | [Ubuntu][rel-u] / [Debian][rel-d] | Git | Python |
|:--------:|:------------:|--------------|-----------------|-----------------------------------|-----|--------|
| Oct 2008 | *Oct 2013*   |              | 2.6.0           | *10.04 Lucid* - 10.10 Maverick / *Squeeze* |
| Dec 2008 | *Feb 2009*   |              | 3.0.0           |
| Feb 2009 | *Mar 2012*   |              |                 | Debian 5 Lenny       | 1.5.6.5 | 2.5.2 |
| Jun 2009 | *Jun 2016*   |              | 3.1.0           | *10.04 Lucid* - 10.10 Maverick / *Squeeze* |
| Feb 2010 | *Oct 2012*   | 1.7.0        |                 | *10.04 Lucid* - *12.04 Precise* - 12.10 Quantal |
| Apr 2010 | *Apr 2015*   |              |                 | *10.04 Lucid*        | 1.7.0.4  | 2.6.5 3.1.2  |
| Jul 2010 | *Dec 2019*   |              | **2.7.0**       | 11.04 Natty - **<current>** |
| Oct 2010 |              |              |                 | 10.10 Maverick       | 1.7.1    | 2.6.6 3.1.3  |
| Feb 2011 | *Feb 2016*   |              |                 | Debian 6 Squeeze     | 1.7.2.5  | 2.6.6 3.1.3  |
| Apr 2011 |              |              |                 | 11.04 Natty          | 1.7.4    | 2.7.1 3.2.0  |
| Oct 2011 | *Feb 2016*   |              | 3.2.0           | 11.04 Natty - 12.10 Quantal |
| Oct 2011 |              |              |                 | 11.10 Ocelot         | 1.7.5.4  | 2.7.2 3.2.2  |
| Apr 2012 | *Apr 2019*   |              |                 | *12.04 Precise*      | 1.7.9.5  | 2.7.3 3.2.3  |
| Sep 2012 | *Sep 2017*   |              | 3.3.0           | 13.04 Raring - 13.10 Saucy |
| Oct 2012 | *Dec 2014*   | 1.8.0        |                 | 13.04 Raring - 13.10 Saucy |
| Oct 2012 |              |              |                 | 12.10 Quantal        | 1.7.10.4 | 2.7.3 3.2.3  |
| Apr 2013 |              |              |                 | 13.04 Raring         | 1.8.1.2  | 2.7.4 3.3.1  |
| May 2013 | *May 2018*   |              |                 | Debian 7 Wheezy      | 1.7.10.4 | 2.7.3 3.2.3  |
| Oct 2013 |              |              |                 | 13.10 Saucy          | 1.8.3.2  | 2.7.5 3.3.2  |
| Feb 2014 | *Dec 2014*   | **1.9.0**    |                 | **14.04 Trusty** |
| Mar 2014 | *Mar 2019*   |              | **3.4.0**       | **14.04 Trusty** - 15.10 Wily / **Jessie** |
| Apr 2014 | **Apr 2022** |              |                 | **14.04 Trusty**     | 1.9.1    | 2.7.5 3.4.0  |
| May 2014 | *Dec 2014*   | 2.0.0        |
| Aug 2014 | *Dec 2014*   | **2.1.0**    |                 | 14.10 Utopic - 15.04 Vivid / **Jessie** |
| Oct 2014 |              |              |                 | 14.10 Utopic         | 2.1.0    | 2.7.8 3.4.2  |
| Nov 2014 | *Sep 2015*   | 2.2.0        |
| Feb 2015 | *Sep 2015*   | 2.3.0        |
| Apr 2015 | *May 2017*   | 2.4.0        |
| Apr 2015 | **Jun 2020** |              |                 | **Debian 8 Jessie**  | 2.1.4    | 2.7.9 3.4.2  |
| Apr 2015 |              |              |                 | 15.04 Vivid          | 2.1.4    | 2.7.9 3.4.3  |
| Jul 2015 | *May 2017*   | 2.5.0        |                 | 15.10 Wily |
| Sep 2015 | *May 2017*   | 2.6.0        |
| Sep 2015 | **Sep 2020** |              | **3.5.0**       | **16.04 Xenial** - 17.04 Zesty / **Stretch** |
| Oct 2015 |              |              |                 | 15.10 Wily           | 2.5.0    | 2.7.9 3.4.3  |
| Jan 2016 | *Jul 2017*   | **2.7.0**    |                 | **16.04 Xenial** |
| Mar 2016 | *Jul 2017*   | 2.8.0        |
| Apr 2016 | **Apr 2024** |              |                 | **16.04 Xenial**     | 2.7.4    | 2.7.11 3.5.1 |
| Jun 2016 | *Jul 2017*   | 2.9.0        |                 | 16.10 Yakkety |
| Sep 2016 | *Sep 2017*   | 2.10.0       |
| Oct 2016 |              |              |                 | 16.10 Yakkety        | 2.9.3    | 2.7.11 3.5.1 |
| Nov 2016 | *Sep 2017*   | **2.11.0**   |                 | 17.04 Zesty / **Stretch** |
| Dec 2016 | **Dec 2021** |              | **3.6.0**       | 17.10 Artful - **18.04 Bionic** - 18.10 Cosmic |
| Feb 2017 | *Sep 2017*   | 2.12.0       |
| Apr 2017 |              |              |                 | 17.04 Zesty          | 2.11.0   | 2.7.13 3.5.3 |
| May 2017 | *May 2018*   | 2.13.0       |
| Jun 2017 | **Jun 2022** |              |                 | **Debian 9 Stretch** | 2.11.0   | 2.7.13 3.5.3 |
| Aug 2017 | *Dec 2019*   | 2.14.0       |                 | 17.10 Artful |
| Oct 2017 | *Dec 2019*   | 2.15.0       |
| Oct 2017 |              |              |                 | 17.10 Artful         | 2.14.1   | 2.7.14 3.6.3 |
| Jan 2018 | *Dec 2019*   | 2.16.0       |
| Apr 2018 | *Dec 2019*   | 2.17.0       |                 | **18.04 Bionic**     |
| Apr 2018 | **Apr 2028** |              |                 | **18.04 Bionic**     | 2.17.0   | 2.7.15 3.6.5 |
| Jun 2018 | *Dec 2019*   | 2.18.0       |
| Jun 2018 | **Jun 2023** |              | 3.7.0           | 19.04 Disco - **20.04 Focal** / **Buster** |
| Sep 2018 | *Dec 2019*   | 2.19.0       |                 | 18.10 Cosmic |
| Oct 2018 |              |              |                 | 18.10 Cosmic         | 2.19.1   | 2.7.15 3.6.6 |
| Dec 2018 | *Dec 2019*   | **2.20.0**   |                 | 19.04 Disco / **Buster** |
| Feb 2019 | *Dec 2019*   | 2.21.0       |
| Apr 2019 |              |              |                 | 19.04 Disco          | 2.20.1   | 2.7.16 3.7.3 |
| Jun 2019 |              | 2.22.0       |
| Jul 2019 | **Jul 2024** |              |                 | **Debian 10 Buster** | 2.20.1   | 2.7.16 3.7.3 |
| Aug 2019 |              | 2.23.0       |
| Oct 2019 | **Oct 2024** |              | 3.8.0           |
| Oct 2019 |              |              |                 | 19.10 Eoan           | 2.20.1   | 2.7.17 3.7.5 |
| Nov 2019 |              | 2.24.0       |
| Jan 2020 |              | 2.25.0       |                 | **20.04 Focal** |
| Apr 2020 | **Apr 2030** |              |                 | **20.04 Focal**      | 2.25.0   | 2.7.17 3.7.5 |


[rel-d]: https://en.wikipedia.org/wiki/Debian_version_history
[rel-g]: https://en.wikipedia.org/wiki/Git#Releases
[rel-p]: https://en.wikipedia.org/wiki/History_of_Python#Table_of_versions
[rel-u]: https://en.wikipedia.org/wiki/Ubuntu_version_history#Table_of_versions
[example announcement]: https://groups.google.com/d/topic/repo-discuss/UGBNismWo1M/discussion
[repo-discuss@googlegroups.com]: https://groups.google.com/forum/#!forum/repo-discuss
[go/repo-release]: https://goto.google.com/repo-release
