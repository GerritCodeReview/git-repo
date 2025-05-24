# repo Smart Syncing

Repo normally fetches & syncs manifests from the same URL specified during
`repo init`, and that often fetches the latest revisions of all projects in
the manifest.  This flow works well for tracking and developing with the
latest code, but often it's desirable to sync to other points.  For example,
to get a local build matching a specific release or build to reproduce bugs
reported by other people.

Repo's sync subcommand has support for fetching manifests from a server over
an XML-RPC connection.  The local configuration and network API are defined by
repo, but individual projects have to host their own server for the client to
communicate with.

This process is called "smart syncing" -- instead of blindly fetching the latest
revision of all projects and getting an unknown state to develop against, the
client passes a request to the server and is given a matching manifest that
typically specifies specific commits for every project to fetch a known source
state.

[TOC]

## Manifest Configuration

The manifest specifies the server to communicate with via the
the [`<manifest-server>` element](manifest-format.md#Element-manifest_server)
element.  This is how the client knows what service to talk to.

```xml
  <manifest-server url="https://example.com/your/manifest/server/url" />
```

If the URL starts with `persistent-`, then the
[`git-remote-persistent-https` helper](https://github.com/git/git/blob/HEAD/contrib/persistent-https/README)
is used to communicate with the server.

## Credentials

Credentials may be specified directly in typical `username:password`
[URI syntax](https://en.wikipedia.org/wiki/URI#Syntax) in the
`<manifest-server>` element directly in the manifest.

If they are not specified, `repo sync` has `--manifest-server-username=USERNAME`
and `--manifest-server-password=PASSWORD` options.

If those are not used, then repo will look up the host in your
[`~/.netrc`](https://docs.python.org/3/library/netrc.html) database.

When making the connection, cookies matching the host are automatically loaded
from the cookiejar specified in
[Git's `http.cookiefile` setting](https://git-scm.com/docs/git-config#Documentation/git-config.txt-httpcookieFile).

## Manifest Server

Unfortunately, there are no public reference implementations.  Google has an
internal one for Android, but it is written using Google's internal systems,
so wouldn't be that helpful as a reference.

That said, the XML-RPC API is pretty simple, so any standard XML-RPC server
example would do.  Google's internal server uses Python's
[xmlrpc.server.SimpleXMLRPCDispatcher](https://docs.python.org/3/library/xmlrpc.server.html).

## Network API

The manifest server should implement the following RPC methods.

### GetApprovedManifest

> `GetApprovedManifest(branch: str, target: Optional[str]) -> str`

The meaning of `branch` and `target` is not strictly defined.  The server may
interpret them however it wants.  The recommended interpretation is that the
`branch` matches the manifest branch, and `target` is an identifier for your
project that matches something users would build.

See the client section below for how repo typically generates these values.

The server will return a manifest or an error.  If it's an error, repo will
show the output directly to the user to provide a limited feedback channel.

If the user's request is ambiguous and could match multiple manifests, the
server has to decide whether to pick one automatically (and silently such that
the user won't know there were multiple matches), or return an error and force
the user to be more specific.

### GetManifest

> `GetManifest(tag: str) -> str`

The meaning of `tag` is not strictly defined.  Projects are encouraged to use
a system where the tag matches a unique source state.

See the client section below for how repo typically generates these values.

The server will return a manifest or an error.  If it's an error, repo will
show the output directly to the user to provide a limited feedback channel.

If the user's request is ambiguous and could match multiple manifests, the
server has to decide whether to pick one automatically (and silently such that
the user won't know there were multiple matches), or return an error and force
the user to be more specific.

## Client Options

Once repo has successfully downloaded the manifest from the server, it saves a
copy into `.repo/manifests/smart_sync_override.xml` so users can examine it.
The next time `repo sync` is run, this file is automatically replaced or removed
based on the current set of options.

### --smart-sync

Repo will call `GetApprovedManifest(branch[, target])`.

The `branch` is determined by the current manifest branch as specified by
`--manifest-branch=BRANCH` when running `repo init`.

The `target` is defined by environment variables in the order below.  If none
of them match, then `target` is omitted.  These variables were decided as they
match the settings Android build environments automatically setup.

1.  `${SYNC_TARGET}`: If defined, the value is used directly.
2.  `${TARGET_PRODUCT}-${TARGET_RELEASE}-${TARGET_BUILD_VARIANT}`: If these
    variables are all defined, then they are merged with `-` and used.
3.  `${TARGET_PRODUCT}-${TARGET_BUILD_VARIANT}`: If these variables are all
    defined, then they are merged with `-` and used.

### --smart-tag=TAG

Repo will call `GetManifest(TAG)`.
