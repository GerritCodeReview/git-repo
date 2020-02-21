# Microsoft Windows Details

Repo is primarily developed on Linux with a lot of users on macOS.
Windows is, unfortunately, not a common platform.
There is support in repo for Windows, but there might be some rough edges.

Keep in mind that Windows in general is "best effort" and "community supported".
That means we don't actively test or verify behavior, but rely heavily on users
to report problems back to us, and to contribute fixes as needed.

[TOC]

## Windows

We only support Windows 10 or newer.
This is largely due to symlinks not being available in older versions, but it's
also due to most developers not using Windows.

We will never add code specific to older versions of Windows.
It might work, but it most likely won't, so please don't bother asking.

## Git worktrees

*** note
**Warning**: Repo's support for Git worktrees is new & experimental.
Please report any bugs and be sure to maintain backups!
***

The Repo 2.4 release introduced support for [Git worktrees][git-worktree].
You don't have to worry about or understand this particular feature, so don't
worry if this section of the Git manual is particularly impenetrable.

The salient point is that Git worktrees allow Repo to create repo client
checkouts that do not require symlinks at all under Windows.
This means users no longer need Administrator access to sync code.

Simply use `--worktree` when running `repo init` to opt in.

This does not effect specific Git repositories that use symlinks themselves.

[git-worktree]: https://git-scm.com/docs/git-worktree

## Symlinks by default

*** note
**NB**: This section applies to the default Repo behavior which does not use
Git worktrees (see the previous section for more info).
***

Repo will use symlinks heavily internally.
On *NIX platforms, this isn't an issue, but Windows makes it a bit difficult.

There are some documents out there for how to do this, but usually the easiest
answer is to run your shell as an Administrator and invoke repo/git in that.

This isn't a great solution, but Windows doesn't make this easy, so here we are.

### Launch Git Bash

If you install Git Bash (see below), you can launch that with appropriate
permissions so that all programs "just work".

* Open the Start Menu (i.e. press the ⊞ key).
* Find/search for "Git Bash".
* Right click it and select "Run as administrator".

*** note
**NB**: This environment is only needed when running `repo`, or any specific `git`
command that might involve symlinks (e.g. `pull` or `checkout`).
You do not need to run all your commands in here such as your editor.
***

### Symlinks with GNU tools

If you want to use `ln -s` inside of the default Git/bash shell, you might need
to export this environment variable:
```sh
$ export MSYS="winsymlinks:nativestrict"
```

Otherwise `ln -s` will copy files and not actually create a symlink.
This also helps `tar` unpack symlinks, so that's nice.

### References

* https://github.com/git-for-windows/git/wiki/Symbolic-Links
* https://blogs.windows.com/windowsdeveloper/2016/12/02/symlinks-windows-10/

## Python

Python 3.6 or newer is required.
Python 2 is known to be broken when running under Windows.
See our [Python Support](./python-support.md) document for more details.

You can grab the latest Windows installer here:<br>
https://www.python.org/downloads/release/python-3

## Git

You should install the most recent version of Git for Windows:<br>
https://git-scm.com/download/win

When installing, make sure to turn on "Enable symbolic links" when prompted.

If you've already installed Git for Windows, you can simply download the latest
installer from above and run it again.
It should safely upgrade things in situ for you.
This is useful if you want to switch the symbolic link option after the fact.

## Shell

We don't have a specific requirement for shell environments when running repo.
Most developers use MinTTY/bash that's included with the Git for Windows install
(so see above for installing Git).

Command & Powershell & the Windows Terminal probably work.
Who knows!

## FAQ

### repo upload always complains about allowing hooks or using --no-verify!

When using `repo upload` in projects that have custom repohooks, you might get
an error like the following:
```sh
$ repo upload
ERROR: You must allow the pre-upload hook or use --no-verify.
```

This can be confusing as you never get prompted.
[MinTTY has a bug][mintty] that breaks isatty checking inside of repo which
causes repo to never interactively prompt the user which means the upload check
always fails.

You can workaround this by manually granting consent when uploading.
Simply add the `--verify` option whenever uploading:
```sh
$ repo upload --verify
```

You will have to specify this flag every time you upload.

[mintty]: https://github.com/mintty/mintty/issues/56

### repohooks always fail with an close_fds error.

When using the [reference repohooks project][repohooks] included in AOSP,
you might see errors like this when running `repo upload`:
```sh
$ repo upload
ERROR: Traceback (most recent call last):
  ...
  File "C:\...\lib\subprocess.py", line 351, in __init__
    raise ValueError("close_fds is not supported on Windows "
ValueError: close_fds is not supported on Windows platforms if you redirect stdin/stderr/stdout

Failed to run main() for pre-upload hook; see traceback above.
```

This error shows up when using Python 2.
You should upgrade to Python 3 instead (see above).

If you already have Python 3 installed, make sure it's the default version.
Running `python --version` should say `Python 3`, not `Python 2`.
If you didn't install the Python versions, or don't have permission to change
the default version, you can probably workaround this by changing `$PATH` in
your shell so the Python 3 version is found first.

[repohooks]: https://android.googlesource.com/platform/tools/repohooks
