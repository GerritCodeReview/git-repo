# Supported Python Versions

This documents the current supported Python versions, and tries to provide
guidance for when we decide to drop support for older versions.

## Summary

*   Python 3.6 (released Dec 2016) is required starting with repo-2.0.
*   Older versions of Python (e.g. v2.7) may use old releases via the repo-1.x
    branch, but no support is provided.

## repo hooks

Projects that use [repo hooks] run on independent schedules.
Since it's not possible to detect what version of Python the hooks were written
or tested against, we always import & exec them with the active Python version.

If the user's Python is too new for the [repo hooks], then it is up to the hooks
maintainer to update.

## Repo launcher

The [repo launcher] is an independent script that can support older versions of
Python without holding back the rest of the codebase.
If it detects the current version of Python is too old, it will try to reexec
via a newer version of Python via standard `pythonX.Y` interpreter names.

However, this is provided as a nicety when it is not onerous, and there is no
official support for older versions of Python than the rest of the codebase.

If your default python interpreters are too old to run the launcher even though
you have newer versions installed, your choices are:

*   Modify the [repo launcher]'s shebang to suite your environment.
*   Download an older version of the [repo launcher] and don't upgrade it.
    Be aware that we do not guarantee old repo launchers will work with current
    versions of repo.  Bug reports using old launchers will not be accepted.

## When to drop support

So far, Python 3.6 has provided most of the interesting features that we want
(e.g. typing & f-strings), and there haven't been features in newer versions
that are critical to us.

That said, let's assume we need functionality that only exists in Python 3.7.
How do we decide when it's acceptable to drop Python 3.6?

1.  Review the [Project References](./release-process.md#project-references) to
    see what major distros are using the previous version of Python, and when
    they go EOL.  Generally we care about Ubuntu LTS & current/previous Debian
    stable versions.
    *   If they're all EOL already, then go for it, drop support.
    *   If they aren't EOL, start a thread on [repo-discuss] to see how the user
        base feels about the proposal.
1.  Update the "soft" versions in the codebase.  This will start warning users
    that the older version is deprecated.
    *   Update [repo](/repo) if the launcher needs updating.
        This only helps with people who download newer launchers.
    *   Update [main.py](/main.py) for the main codebase.
        This warns for everyone regardless of [repo launcher] version.
    *   Update [requirements.json](/requirements.json).
        This allows [repo launcher] to display warnings/errors without having
        to execute the new codebase.  This helps in case of syntax or module
        changes where older versions won't even be able to import the new code.
1.  After some grace period (ideally at least 2 quarters after the first release
    with the updated soft requirements), update the "hard" versions, and then
    start using the new functionality.

## Python 2.7 & 3.0-3.5

> **There is no support for these versions.**
> **Do not file bugs if you are using old Python versions.**
> **Any such reports will be marked invalid and ignored.**
> **Upgrade your distro and/or runtime instead.**

Fetch an old version of the [repo launcher]:

```sh
$ curl https://storage.googleapis.com/git-repo-downloads/repo-2.32 > ~/.bin/repo-2.32
$ chmod a+rx ~/.bin/repo-2.32
```

Then initialize an old version of repo:

```sh
$ repo-2.32 init --repo-rev=repo-1 ...
```


[repo-discuss]: https://groups.google.com/forum/#!forum/repo-discuss
[repo hooks]: ./repo-hooks.md
[repo launcher]: ../repo
