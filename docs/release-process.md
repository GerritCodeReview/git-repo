# repo release process

This is the process for creating a new release of repo, as well as all the
related topics and flows.

[TOC]

## Schedule

There is no specific schedule for when releases are made.
Usually it's more along the lines of "enough minor changes have been merged",
or "there's a known issue the maintainers know should get fixed".
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
The tag could be pushed now, but it won't be used by clients normally (since the
default `repo-rev` setting is `stable`).
This would allow some early testing on systems who explicitly select `main`.

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
$ t=v2.30

# Create a new signed tag with the current HEAD.
$ ./release/sign-tag.py $t

# Verify the signed tag.
$ git show $t
```

### Push the new release

Once you're ready to make the release available to everyone, push it to the
`stable` branch.

Make sure you never push the tag itself to the stable branch!
Only push the commit -- note the use of `^0` below.

```sh
$ git push https://gerrit-review.googlesource.com/git-repo $t
$ git push https://gerrit-review.googlesource.com/git-repo $t^0:stable
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
# This assumes "main" is the current tagged release.  If it's newer, change it
# to the current release tag too.
$ git log --format="%h (%aN) %s" --no-merges origin/stable..main
```

## Project References

Here's a table showing the relationship of major tools, their EOL dates, and
their status in Ubuntu & Debian.
Those distros tend to be good indicators of how long we need to support things.

Things in bold indicate stuff to take note of, but does not guarantee that we
still support them.
Things in italics are things we used to care about but probably don't anymore.

|   Date   |     EOL      | [Git][rel-g] | [Python][rel-p] | [SSH][rel-o] | [Ubuntu][rel-u] / [Debian][rel-d] | Git | Python | SSH |
|:--------:|:------------:|:------------:|:---------------:|:------------:|-----------------------------------|:---:|:------:|:---:|
| Apr 2008 |              |              |                 | 5.0          |
| Jun 2008 |              |              |                 | 5.1          |
| Oct 2008 | *Oct 2013*   |              | 2.6.0           |              | *10.04 Lucid* - 10.10 Maverick / *Squeeze* |
| Dec 2008 | *Feb 2009*   |              | 3.0.0           |
| Feb 2009 |              |              |                 | 5.2          |
| Feb 2009 | *Mar 2012*   |              |                 |              | Debian 5 Lenny       | 1.5.6.5 | 2.5.2 |
| Jun 2009 | *Jun 2016*   |              | 3.1.0           |              | *10.04 Lucid* - 10.10 Maverick / *Squeeze* |
| Sep 2009 |              |              |                 | 5.3          | *10.04 Lucid* |
| Feb 2010 | *Oct 2012*   | 1.7.0        |                 |              | *10.04 Lucid* - *12.04 Precise* - 12.10 Quantal |
| Mar 2010 |              |              |                 | 5.4          |
| Apr 2010 |              |              |                 | 5.5          | 10.10 Maverick |
| Apr 2010 | *Apr 2015*   |              |                 |              | *10.04 Lucid*        | 1.7.0.4  | 2.6.5 3.1.2  | 5.3 |
| Jul 2010 | *Dec 2019*   |              | *2.7.0*         |              | 11.04 Natty - *<current>* |
| Aug 2010 |              |              |                 | 5.6          |
| Oct 2010 |              |              |                 |              | 10.10 Maverick       | 1.7.1    | 2.6.6 3.1.3  | 5.5 |
| Jan 2011 |              |              |                 | 5.7          |
| Feb 2011 |              |              |                 | 5.8          | 11.04 Natty |
| Feb 2011 | *Feb 2016*   |              |                 |              | Debian 6 Squeeze     | 1.7.2.5  | 2.6.6 3.1.3  |
| Apr 2011 |              |              |                 |              | 11.04 Natty          | 1.7.4    | 2.7.1 3.2.0  | 5.8 |
| Sep 2011 |              |              |                 | 5.9          | *12.04 Precise* |
| Oct 2011 | *Feb 2016*   |              | 3.2.0           |              | 11.04 Natty - 12.10 Quantal |
| Oct 2011 |              |              |                 |              | 11.10 Ocelot         | 1.7.5.4  | 2.7.2 3.2.2  | 5.8 |
| Apr 2012 |              |              |                 | 6.0          | 12.10 Quantal |
| Apr 2012 | *Apr 2019*   |              |                 |              | *12.04 Precise*      | 1.7.9.5  | 2.7.3 3.2.3  | 5.9 |
| Aug 2012 |              |              |                 | 6.1          | 13.04 Raring |
| Sep 2012 | *Sep 2017*   |              | 3.3.0           |              | 13.04 Raring - 13.10 Saucy |
| Oct 2012 | *Dec 2014*   | 1.8.0        |                 |              | 13.04 Raring - 13.10 Saucy |
| Oct 2012 |              |              |                 |              | 12.10 Quantal        | 1.7.10.4 | 2.7.3 3.2.3  | 6.0 |
| Mar 2013 |              |              |                 | 6.2          | 13.10 Saucy |
| Apr 2013 |              |              |                 |              | 13.04 Raring         | 1.8.1.2  | 2.7.4 3.3.1  | 6.1 |
| May 2013 | *May 2018*   |              |                 |              | Debian 7 Wheezy      | 1.7.10.4 | 2.7.3 3.2.3  |
| Sep 2013 |              |              |                 | 6.3          |
| Oct 2013 |              |              |                 |              | 13.10 Saucy          | 1.8.3.2  | 2.7.5 3.3.2  | 6.2 |
| Nov 2013 |              |              |                 | 6.4          |
| Jan 2014 |              |              |                 | 6.5          |
| Feb 2014 | *Dec 2014*   | **1.9.0**    |                 |              | *14.04 Trusty* |
| Mar 2014 | *Mar 2019*   |              | *3.4.0*         |              | *14.04 Trusty* - 15.10 Wily / *Jessie* |
| Mar 2014 |              |              |                 | 6.6          | *14.04 Trusty* - 14.10 Utopic |
| Apr 2014 | *Apr 2024*   |              |                 |              | *14.04 Trusty*       | 1.9.1    | 2.7.5 3.4.0  | 6.6 |
| May 2014 | *Dec 2014*   | 2.0.0        |
| Aug 2014 | *Dec 2014*   | *2.1.0*      |                 |              | 14.10 Utopic - 15.04 Vivid / *Jessie* |
| Oct 2014 |              |              |                 | 6.7          | 15.04 Vivid |
| Oct 2014 |              |              |                 |              | 14.10 Utopic         | 2.1.0    | 2.7.8 3.4.2  | 6.6 |
| Nov 2014 | *Sep 2015*   | 2.2.0        |
| Feb 2015 | *Sep 2015*   | 2.3.0        |
| Mar 2015 |              |              |                 | 6.8          |
| Apr 2015 | *May 2017*   | 2.4.0        |
| Apr 2015 | *Jun 2020*   |              |                 |              | *Debian 8 Jessie*    | 2.1.4    | 2.7.9 3.4.2  |
| Apr 2015 |              |              |                 |              | 15.04 Vivid          | 2.1.4    | 2.7.9 3.4.3  | 6.7 |
| Jul 2015 | *May 2017*   | 2.5.0        |                 |              | 15.10 Wily |
| Jul 2015 |              |              |                 | 6.9          | 15.10 Wily |
| Aug 2015 |              |              |                 | 7.0          |
| Aug 2015 |              |              |                 | 7.1          |
| Sep 2015 | *May 2017*   | 2.6.0        |
| Sep 2015 | *Sep 2020*   |              | *3.5.0*         |              | *16.04 Xenial* - 17.04 Zesty / *Stretch* |
| Oct 2015 |              |              |                 |              | 15.10 Wily           | 2.5.0    | 2.7.9 3.4.3  | 6.9 |
| Jan 2016 | *Jul 2017*   | *2.7.0*      |                 |              | *16.04 Xenial* |
| Feb 2016 |              |              |                 | 7.2          | *16.04 Xenial* |
| Mar 2016 | *Jul 2017*   | 2.8.0        |
| Apr 2016 | *Apr 2026*   |              |                 |              | *16.04 Xenial*       | 2.7.4    | 2.7.11 3.5.1 | 7.2 |
| Jun 2016 | *Jul 2017*   | 2.9.0        |                 |              | 16.10 Yakkety |
| Jul 2016 |              |              |                 | 7.3          | 16.10 Yakkety |
| Sep 2016 | *Sep 2017*   | 2.10.0       |
| Oct 2016 |              |              |                 |              | 16.10 Yakkety        | 2.9.3    | 2.7.11 3.5.1 | 7.3 |
| Nov 2016 | *Sep 2017*   | *2.11.0*     |                 |              | 17.04 Zesty / *Stretch* |
| Dec 2016 | **Dec 2021** |              | **3.6.0**       |              | 17.10 Artful - **18.04 Bionic** - 18.10 Cosmic |
| Dec 2016 |              |              |                 | 7.4          | 17.04 Zesty / *Debian 9 Stretch* |
| Feb 2017 | *Sep 2017*   | 2.12.0       |
| Mar 2017 |              |              |                 | 7.5          | 17.10 Artful |
| Apr 2017 |              |              |                 |              | 17.04 Zesty          | 2.11.0   | 2.7.13 3.5.3 | 7.4 |
| May 2017 | *May 2018*   | 2.13.0       |
| Jun 2017 | *Jun 2022*   |              |                 |              | *Debian 9 Stretch*   | 2.11.0   | 2.7.13 3.5.3 | 7.4 |
| Aug 2017 | *Dec 2019*   | 2.14.0       |                 |              | 17.10 Artful |
| Oct 2017 | *Dec 2019*   | 2.15.0       |
| Oct 2017 |              |              |                 | 7.6          | **18.04 Bionic** |
| Oct 2017 |              |              |                 |              | 17.10 Artful         | 2.14.1   | 2.7.14 3.6.3 | 7.5 |
| Jan 2018 | *Dec 2019*   | 2.16.0       |
| Apr 2018 | *Mar 2021*   | **2.17.0**   |                 |              | **18.04 Bionic**     |
| Apr 2018 |              |              |                 | 7.7          | 18.10 Cosmic |
| Apr 2018 | **Apr 2028** |              |                 |              | **18.04 Bionic**     | 2.17.0   | 2.7.15 3.6.5 | 7.6 |
| Jun 2018 | *Mar 2021*   | 2.18.0       |
| Jun 2018 | **Jun 2023** |              | 3.7.0           |              | 19.04 Disco - **Buster** |
| Aug 2018 |              |              |                 | 7.8          |
| Sep 2018 | *Mar 2021*   | 2.19.0       |                 |              | 18.10 Cosmic |
| Oct 2018 |              |              |                 | 7.9          | 19.04 Disco / **Buster** |
| Oct 2018 |              |              |                 |              | 18.10 Cosmic         | 2.19.1   | 2.7.15 3.6.6 | 7.7 |
| Dec 2018 | *Mar 2021*   | **2.20.0**   |                 |              | 19.04 Disco - 19.10 Eoan / **Buster** |
| Feb 2019 | *Mar 2021*   | 2.21.0       |
| Apr 2019 |              |              |                 | 8.0          | 19.10 Eoan |
| Apr 2019 |              |              |                 |              | 19.04 Disco          | 2.20.1   | 2.7.16 3.7.3 | 7.9 |
| Jun 2019 |              | 2.22.0       |
| Jul 2019 | **Jul 2024** |              |                 |              | **Debian 10 Buster** | 2.20.1   | 2.7.16 3.7.3 | 7.9 |
| Aug 2019 | *Mar 2021*   | 2.23.0       |
| Oct 2019 | **Oct 2024** |              | 3.8.0           |              | **20.04 Focal** - 20.10 Groovy |
| Oct 2019 |              |              |                 | 8.1          |
| Oct 2019 |              |              |                 |              | 19.10 Eoan           | 2.20.1   | 2.7.17 3.7.5 | 8.0 |
| Nov 2019 | *Mar 2021*   | 2.24.0       |
| Jan 2020 | *Mar 2021*   | 2.25.0       |                 |              | **20.04 Focal** |
| Feb 2020 |              |              |                 | 8.2          | **20.04 Focal** |
| Mar 2020 | *Mar 2021*   | 2.26.0       |
| Apr 2020 | **Apr 2030** |              |                 |              | **20.04 Focal**      | 2.25.1   | 2.7.17 3.8.2 | 8.2 |
| May 2020 | *Mar 2021*   | 2.27.0       |                 |              | 20.10 Groovy |
| May 2020 |              |              |                 | 8.3          |
| Jul 2020 | *Mar 2021*   | 2.28.0       |
| Sep 2020 |              |              |                 | 8.4          | 21.04 Hirsute / **Bullseye** |
| Oct 2020 | *Mar 2021*   | 2.29.0       |
| Oct 2020 |              |              |                 |              | 20.10 Groovy         | 2.27.0   | 2.7.18 3.8.6 | 8.3 |
| Oct 2020 | **Oct 2025** |              | 3.9.0           |              | 21.04 Hirsute / **Bullseye** |
| Dec 2020 | *Mar 2021*   | 2.30.0       |                 |              | 21.04 Hirsute / **Bullseye** |
| Mar 2021 |              | 2.31.0       |                 | 8.5          |
| Apr 2021 |              |              |                 | 8.6          |
| Apr 2021 | *Jan 2022*   |              |                 |              | 21.04 Hirsute        | 2.30.2   | 2.7.18 3.9.4 | 8.4 |
| Jun 2021 |              | 2.32.0       |
| Aug 2021 |              | 2.33.0       |                 | 8.7          |
| Aug 2021 | **Aug 2026** |              |                 |              | **Debian 11 Bullseye** | 2.30.2 | 2.7.18 3.9.2 | 8.4 |
| Sep 2021 |              |              |                 | 8.8          |
| Oct 2021 |              | 2.34.0       | 3.10.0          |              | **22.04 Jammy** |
| Jan 2022 |              | 2.35.0       |
| Feb 2022 |              |              |                 | 8.9          | **22.04 Jammy** |
| Apr 2022 |              | 2.36.0       |                 | 9.0          |
| Apr 2022 | **Apr 2032** |              |                 |              | **22.04 Jammy**      | 2.34.1 | 2.7.18 3.10.6 | 8.9 |
| Jun 2022 |              | 2.37.0       |
| Oct 2022 |              | 2.38.0       |                 | 9.1          |
| Oct 2022 |              |              | 3.11.0          |              | **Bookworm** |
| Dec 2022 |              | 2.39.0       |                 |              | **Bookworm** |
| Feb 2023 |              |              |                 | 9.2          | **Bookworm** |
| Mar 2023 |              | 2.40.0       |                 | 9.3          |
| Jun 2023 |              | 2.41.0       |
| Jun 2023 | **Jun 2028** |              |                 |              | **Debian 12 Bookworm** | 2.39.2 | 3.11.2 | 9.2 |
| Aug 2023 |              | 2.42.0       |                 | 9.4          |
| Oct 2023 |              |              | 3.12.0          | 9.5          |
| Nov 2022 |              | 2.43.0       |
| Dec 2023 |              |              |                 | 9.6          |
| Feb 2024 |              | 2.44.0       |
| Mar 2024 |              |              |                 | 9.7          |
| Oct 2024 |              |              | 3.13.0          |
| **Date** |   **EOL**    | **[Git][rel-g]** | **[Python][rel-p]** | **[SSH][rel-o]** | **[Ubuntu][rel-u] / [Debian][rel-d]** | **Git** | **Python** | **SSH** |


[contact]: ../README.md#contact
[rel-d]: https://en.wikipedia.org/wiki/Debian_version_history
[rel-g]: https://en.wikipedia.org/wiki/Git#Releases
[rel-o]: https://www.openssh.com/releasenotes.html
[rel-p]: https://en.wikipedia.org/wiki/History_of_Python#Table_of_versions
[rel-u]: https://wiki.ubuntu.com/Releases
[example announcement]: https://groups.google.com/d/topic/repo-discuss/UGBNismWo1M/discussion
[repo-discuss@googlegroups.com]: https://groups.google.com/forum/#!forum/repo-discuss
[go/repo-release]: https://goto.google.com/repo-release
