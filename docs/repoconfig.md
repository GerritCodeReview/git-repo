# repoconfig: User Configuration

Repo keeps a small number of settings that apply to the current user rather
than to one checkout.  They live in the per-user configuration file
`~/.repoconfig/config`, which is separate from both git's own `~/.gitconfig`
and the per-checkout settings stored in `.repo/manifests.git/config` (see
[internal-fs-layout.md](./internal-fs-layout.md#Global-settings) for those).

[TOC]

## Location

The file is `.repoconfig/config` inside the user's home directory.  The parent
directory can be changed by setting the `REPO_CONFIG_DIR` environment variable,
in which case repo reads `$REPO_CONFIG_DIR/.repoconfig/config` instead.

The file is created on demand; it's fine for it to be missing.

## Format

The file uses the [git-config] syntax.  The easiest way to manage it is the
`repo config` command:

```sh
# Set a value.
repo config set sync.smartsync true

# Read a value.
repo config get sync.smartsync

# Remove a value.
repo config unset sync.smartsync

# Show all settings.
repo config list
```

Like other repo subcommands, `repo config` must be run from inside a repo
checkout.  The file can also be edited by hand:

```ini
[sync]
	smartsync = true
```

Boolean settings accept `true`/`yes` and `false`/`no`.

## Settings

### alias.*

`alias.<name>` defines `repo <name>` as a shortcut for another subcommand,
optionally with arguments, in the same way as git aliases:

```ini
[alias]
	ss = sync -s
	st = status -o
```

Aliases defined in a checkout's `.repo/config` take precedence over per-user
ones.  Existing subcommands cannot be overridden by an alias.

### sync

#### smartsync

`sync.smartsync` is a boolean that lets a user decide once, for all their
checkouts, whether `repo sync` should [Smart Sync](./smart-sync.md) by
default: `true` always Smart Syncs, as if `-s`/`--smart-sync` were passed;
`false` never does by default, even if the manifest sets
`sync-smartsync="true"`; unset follows the manifest.

The effective behavior is resolved in this order; the first match wins:

1.  Command line: `-s`/`--smart-sync`, `--no-smart-sync`, or `-t`/`--smart-tag`.
2.  User config: `sync.smartsync` in `~/.repoconfig/config`.
3.  Manifest: `sync-smartsync="true"` on the `<default>` element.
4.  Otherwise, a regular ToT sync.

So `sync.smartsync=false` turns off the manifest-driven default, but an
explicit `repo sync -s`, `repo sync -t TAG` or `repo smartsync` still works.
Likewise `sync.smartsync=true` is overridden by `--no-smart-sync`.

A Smart Sync enabled by `sync.smartsync=true` is treated as an explicit
request: it is subject to the same restrictions as `-s` (it is skipped when
`-l`/`--local-only`, `-m`/`--manifest-name`, `-t`/`--smart-tag` or
`--superproject-revision` is used), and a failure to obtain a manifest from
the server fails the sync instead of silently falling back to ToT.

`sync.smartsync` does not affect `-l`/`--local-only`: a local-only sync keeps
whatever `smart_sync_override.xml` the previous network sync left behind.  See
[smart-sync.md](./smart-sync.md#Client-Options) for details.


[git-config]: https://git-scm.com/docs/git-config
