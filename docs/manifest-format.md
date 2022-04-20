# repo Manifest Format

A repo manifest describes the structure of a repo client; that is
the directories that are visible and where they should be obtained
from with git.

The basic structure of a manifest is a bare Git repository holding
a single `default.xml` XML file in the top level directory.

Manifests are inherently version controlled, since they are kept
within a Git repository.  Updates to manifests are automatically
obtained by clients during `repo sync`.

[TOC]


## XML File Format

A manifest XML file (e.g. `default.xml`) roughly conforms to the
following DTD:

```xml
<!DOCTYPE manifest [

  <!ELEMENT manifest (notice?,
                      remote*,
                      default?,
                      manifest-server?,
                      submanifest*?,
                      remove-project*,
                      project*,
                      extend-project*,
                      repo-hooks?,
                      superproject?,
                      contactinfo?,
                      include*)>

  <!ELEMENT notice (#PCDATA)>

  <!ELEMENT remote (annotation*)>
  <!ATTLIST remote name         ID    #REQUIRED>
  <!ATTLIST remote alias        CDATA #IMPLIED>
  <!ATTLIST remote fetch        CDATA #REQUIRED>
  <!ATTLIST remote pushurl      CDATA #IMPLIED>
  <!ATTLIST remote review       CDATA #IMPLIED>
  <!ATTLIST remote revision     CDATA #IMPLIED>

  <!ELEMENT default EMPTY>
  <!ATTLIST default remote      IDREF #IMPLIED>
  <!ATTLIST default revision    CDATA #IMPLIED>
  <!ATTLIST default dest-branch CDATA #IMPLIED>
  <!ATTLIST default upstream    CDATA #IMPLIED>
  <!ATTLIST default sync-j      CDATA #IMPLIED>
  <!ATTLIST default sync-c      CDATA #IMPLIED>
  <!ATTLIST default sync-s      CDATA #IMPLIED>
  <!ATTLIST default sync-tags   CDATA #IMPLIED>

  <!ELEMENT manifest-server EMPTY>
  <!ATTLIST manifest-server url CDATA #REQUIRED>

  <!ELEMENT submanifest EMPTY>
  <!ATTLIST submanifest name           ID #REQUIRED>
  <!ATTLIST submanifest remote         IDREF #IMPLIED>
  <!ATTLIST submanifest project        CDATA #IMPLIED>
  <!ATTLIST submanifest manifest-name  CDATA #IMPLIED>
  <!ATTLIST submanifest revision       CDATA #IMPLIED>
  <!ATTLIST submanifest path           CDATA #IMPLIED>
  <!ATTLIST submanifest groups         CDATA #IMPLIED>
  <!ATTLIST submanifest default-groups CDATA #IMPLIED>

  <!ELEMENT project (annotation*,
                     project*,
                     copyfile*,
                     linkfile*)>
  <!ATTLIST project name        CDATA #REQUIRED>
  <!ATTLIST project path        CDATA #IMPLIED>
  <!ATTLIST project remote      IDREF #IMPLIED>
  <!ATTLIST project revision    CDATA #IMPLIED>
  <!ATTLIST project dest-branch CDATA #IMPLIED>
  <!ATTLIST project groups      CDATA #IMPLIED>
  <!ATTLIST project sync-c      CDATA #IMPLIED>
  <!ATTLIST project sync-s      CDATA #IMPLIED>
  <!ATTLIST project sync-tags   CDATA #IMPLIED>
  <!ATTLIST project upstream CDATA #IMPLIED>
  <!ATTLIST project clone-depth CDATA #IMPLIED>
  <!ATTLIST project force-path CDATA #IMPLIED>

  <!ELEMENT annotation EMPTY>
  <!ATTLIST annotation name  CDATA #REQUIRED>
  <!ATTLIST annotation value CDATA #REQUIRED>
  <!ATTLIST annotation keep  CDATA "true">

  <!ELEMENT copyfile EMPTY>
  <!ATTLIST copyfile src  CDATA #REQUIRED>
  <!ATTLIST copyfile dest CDATA #REQUIRED>

  <!ELEMENT linkfile EMPTY>
  <!ATTLIST linkfile src CDATA #REQUIRED>
  <!ATTLIST linkfile dest CDATA #REQUIRED>

  <!ELEMENT extend-project EMPTY>
  <!ATTLIST extend-project name CDATA #REQUIRED>
  <!ATTLIST extend-project path CDATA #IMPLIED>
  <!ATTLIST extend-project dest-path CDATA #IMPLIED>
  <!ATTLIST extend-project groups CDATA #IMPLIED>
  <!ATTLIST extend-project revision CDATA #IMPLIED>
  <!ATTLIST extend-project remote CDATA #IMPLIED>

  <!ELEMENT remove-project EMPTY>
  <!ATTLIST remove-project name  CDATA #REQUIRED>
  <!ATTLIST remove-project optional  CDATA #IMPLIED>

  <!ELEMENT repo-hooks EMPTY>
  <!ATTLIST repo-hooks in-project CDATA #REQUIRED>
  <!ATTLIST repo-hooks enabled-list CDATA #REQUIRED>

  <!ELEMENT superproject EMPTY>
  <!ATTLIST superproject name     CDATA #REQUIRED>
  <!ATTLIST superproject remote   IDREF #IMPLIED>
  <!ATTLIST superproject revision CDATA #IMPLIED>

  <!ELEMENT contactinfo EMPTY>
  <!ATTLIST contactinfo bugurl  CDATA #REQUIRED>

  <!ELEMENT include EMPTY>
  <!ATTLIST include name   CDATA #REQUIRED>
  <!ATTLIST include groups CDATA #IMPLIED>
]>
```

For compatibility purposes across repo releases, all unknown elements are
silently ignored.  However, repo reserves all possible names for itself for
future use.  If you want to use custom elements, the `x-*` namespace is
reserved for that purpose, and repo guarantees to never allocate any
corresponding names.

A description of the elements and their attributes follows.


### Element manifest

The root element of the file.

### Element notice

Arbitrary text that is displayed to users whenever `repo sync` finishes.
The content is simply passed through as it exists in the manifest.

### Element remote

One or more remote elements may be specified.  Each remote element
specifies a Git URL shared by one or more projects and (optionally)
the Gerrit review server those projects upload changes through.

Attribute `name`: A short name unique to this manifest file.  The
name specified here is used as the remote name in each project's
.git/config, and is therefore automatically available to commands
like `git fetch`, `git remote`, `git pull` and `git push`.

Attribute `alias`: The alias, if specified, is used to override
`name` to be set as the remote name in each project's .git/config.
Its value can be duplicated while attribute `name` has to be unique
in the manifest file. This helps each project to be able to have
same remote name which actually points to different remote url.

Attribute `fetch`: The Git URL prefix for all projects which use
this remote.  Each project's name is appended to this prefix to
form the actual URL used to clone the project.

Attribute `pushurl`: The Git "push" URL prefix for all projects
which use this remote.  Each project's name is appended to this
prefix to form the actual URL used to "git push" the project.
This attribute is optional; if not specified then "git push"
will use the same URL as the `fetch` attribute.

Attribute `review`: Hostname of the Gerrit server where reviews
are uploaded to by `repo upload`.  This attribute is optional;
if not specified then `repo upload` will not function.

Attribute `revision`: Name of a Git branch (e.g. `main` or
`refs/heads/main`). Remotes with their own revision will override
the default revision.

### Element default

At most one default element may be specified.  Its remote and
revision attributes are used when a project element does not
specify its own remote or revision attribute.

Attribute `remote`: Name of a previously defined remote element.
Project elements lacking a remote attribute of their own will use
this remote.

Attribute `revision`: Name of a Git branch (e.g. `main` or
`refs/heads/main`).  Project elements lacking their own
revision attribute will use this revision.

Attribute `dest-branch`: Name of a Git branch (e.g. `main`).
Project elements not setting their own `dest-branch` will inherit
this value. If this value is not set, projects will use `revision`
by default instead.

Attribute `upstream`: Name of the Git ref in which a sha1
can be found.  Used when syncing a revision locked manifest in
-c mode to avoid having to sync the entire ref space. Project elements
not setting their own `upstream` will inherit this value.

Attribute `sync-j`: Number of parallel jobs to use when synching.

Attribute `sync-c`: Set to true to only sync the given Git
branch (specified in the `revision` attribute) rather than the
whole ref space.  Project elements lacking a sync-c element of
their own will use this value.

Attribute `sync-s`: Set to true to also sync sub-projects.

Attribute `sync-tags`: Set to false to only sync the given Git
branch (specified in the `revision` attribute) rather than
the other ref tags.


### Element manifest-server

At most one manifest-server may be specified. The url attribute
is used to specify the URL of a manifest server, which is an
XML RPC service.

The manifest server should implement the following RPC methods:

    GetApprovedManifest(branch, target)

Return a manifest in which each project is pegged to a known good revision
for the current branch and target. This is used by repo sync when the
--smart-sync option is given.

The target to use is defined by environment variables TARGET_PRODUCT
and TARGET_BUILD_VARIANT. These variables are used to create a string
of the form $TARGET_PRODUCT-$TARGET_BUILD_VARIANT, e.g. passion-userdebug.
If one of those variables or both are not present, the program will call
GetApprovedManifest without the target parameter and the manifest server
should choose a reasonable default target.

    GetManifest(tag)

Return a manifest in which each project is pegged to the revision at
the specified tag. This is used by repo sync when the --smart-tag option
is given.


### Element submanifest

One or more submanifest elements may be specified.  Each element describes a
single manifest to be checked out as a child.

Attribute `name`: A unique name (within the current (sub)manifest) for this
submanifest. It acts as a default for `revision` below.  The same name can be
used for submanifests with different parent (sub)manifests.

Attribute `remote`: Name of a previously defined remote element.
If not supplied the remote given by the default element is used.

Attribute `project`: The manifest project name.  The project's name is appended
onto its remote's fetch URL to generate the actual URL to configure the Git
remote with.  The URL gets formed as:

    ${remote_fetch}/${project_name}.git

where ${remote_fetch} is the remote's fetch attribute and
${project_name} is the project's name attribute.  The suffix ".git"
is always appended as repo assumes the upstream is a forest of
bare Git repositories.  If the project has a parent element, its
name will be prefixed by the parent's.

The project name must match the name Gerrit knows, if Gerrit is
being used for code reviews.

`project` must not be empty, and may not be an absolute path or use "." or ".."
path components.  It is always interpreted relative to the remote's fetch
settings, so if a different base path is needed, declare a different remote
with the new settings needed.

If not supplied the remote and project for this manifest will be used: `remote`
cannot be supplied.

Projects from a submanifest and its submanifests are added to the
submanifest::path:<path_prefix> group.

Attribute `manifest-name`: The manifest filename in the manifest project.  If
not supplied, `default.xml` is used.

Attribute `revision`: Name of a Git branch (e.g. "main" or "refs/heads/main"),
tag (e.g. "refs/tags/stable"), or a commit hash.  If not supplied, `name` is
used.

Attribute `path`: An optional path relative to the top directory
of the repo client where the submanifest repo client top directory
should be placed.  If not supplied, `revision` is used.

`path` may not be an absolute path or use "." or ".." path components.

Attribute `groups`: List of additional groups to which all projects
in the included submanifest belong. This appends and recurses, meaning
all projects in submanifests carry all parent submanifest groups.
Same syntax as the corresponding element of `project`.

Attribute `default-groups`: The list of manifest groups to sync if no
`--groups=` parameter was specified at init.  When that list is empty, use this
list instead of "default" as the list of groups to sync.

### Element project

One or more project elements may be specified.  Each element
describes a single Git repository to be cloned into the repo
client workspace.  You may specify Git-submodules by creating a
nested project.  Git-submodules will be automatically
recognized and inherit their parent's attributes, but those
may be overridden by an explicitly specified project element.

Attribute `name`: A unique name for this project.  The project's
name is appended onto its remote's fetch URL to generate the actual
URL to configure the Git remote with.  The URL gets formed as:

    ${remote_fetch}/${project_name}.git

where ${remote_fetch} is the remote's fetch attribute and
${project_name} is the project's name attribute.  The suffix ".git"
is always appended as repo assumes the upstream is a forest of
bare Git repositories.  If the project has a parent element, its
name will be prefixed by the parent's.

The project name must match the name Gerrit knows, if Gerrit is
being used for code reviews.

"name" must not be empty, and may not be an absolute path or use "." or ".."
path components.  It is always interpreted relative to the remote's fetch
settings, so if a different base path is needed, declare a different remote
with the new settings needed.
These restrictions are not enforced for [Local Manifests].

Attribute `path`: An optional path relative to the top directory
of the repo client where the Git working directory for this project
should be placed.  If not supplied the project "name" is used.
If the project has a parent element, its path will be prefixed
by the parent's.

"path" may not be an absolute path or use "." or ".." path components.
These restrictions are not enforced for [Local Manifests].

If you want to place files into the root of the checkout (e.g. a README or
Makefile or another build script), use the [copyfile] or [linkfile] elements
instead.

Attribute `remote`: Name of a previously defined remote element.
If not supplied the remote given by the default element is used.

Attribute `revision`: Name of the Git branch the manifest wants
to track for this project.  Names can be relative to refs/heads
(e.g. just "main") or absolute (e.g. "refs/heads/main").
Tags and/or explicit SHA-1s should work in theory, but have not
been extensively tested.  If not supplied the revision given by
the remote element is used if applicable, else the default
element is used.

Attribute `dest-branch`: Name of a Git branch (e.g. `main`).
When using `repo upload`, changes will be submitted for code
review on this branch. If unspecified both here and in the
default element, `revision` is used instead.

Attribute `groups`: List of groups to which this project belongs,
whitespace or comma separated.  All projects belong to the group
"all", and each project automatically belongs to a group of
its name:`name` and path:`path`.  E.g. for
`<project name="monkeys" path="barrel-of"/>`, that project
definition is implicitly in the following manifest groups:
default, name:monkeys, and path:barrel-of.  If you place a project in the
group "notdefault", it will not be automatically downloaded by repo.
If the project has a parent element, the `name` and `path` here
are the prefixed ones.

Attribute `sync-c`: Set to true to only sync the given Git
branch (specified in the `revision` attribute) rather than the
whole ref space.

Attribute `sync-s`: Set to true to also sync sub-projects.

Attribute `upstream`: Name of the Git ref in which a sha1
can be found.  Used when syncing a revision locked manifest in
-c mode to avoid having to sync the entire ref space.

Attribute `clone-depth`: Set the depth to use when fetching this
project.  If specified, this value will override any value given
to repo init with the --depth option on the command line.

Attribute `force-path`: Set to true to force this project to create the
local mirror repository according to its `path` attribute (if supplied)
rather than the `name` attribute.  This attribute only applies to the
local mirrors syncing, it will be ignored when syncing the projects in a
client working directory.

### Element extend-project

Modify the attributes of the named project.

This element is mostly useful in a local manifest file, to modify the
attributes of an existing project without completely replacing the
existing project definition.  This makes the local manifest more robust
against changes to the original manifest.

Attribute `path`: If specified, limit the change to projects checked out
at the specified path, rather than all projects with the given name.

Attribute `dest-path`: If specified, a path relative to the top directory
of the repo client where the Git working directory for this project
should be placed.  This is used to move a project in the checkout by
overriding the existing `path` setting.

Attribute `groups`: List of additional groups to which this project
belongs.  Same syntax as the corresponding element of `project`.

Attribute `revision`: If specified, overrides the revision of the original
project.  Same syntax as the corresponding element of `project`.

Attribute `remote`: If specified, overrides the remote of the original
project.  Same syntax as the corresponding element of `project`.

### Element annotation

Zero or more annotation elements may be specified as children of a
project or remote element. Each element describes a name-value pair.
For projects, this name-value pair will be exported into each project's
environment during a 'forall' command, prefixed with `REPO__`.  In addition,
there is an optional attribute "keep" which accepts the case insensitive values
"true" (default) or "false".  This attribute determines whether or not the
annotation will be kept when exported with the manifest subcommand.

### Element copyfile

Zero or more copyfile elements may be specified as children of a
project element. Each element describes a src-dest pair of files;
the "src" file will be copied to the "dest" place during `repo sync`
command.

"src" is project relative, "dest" is relative to the top of the tree.
Copying from paths outside of the project or to paths outside of the repo
client is not allowed.

"src" and "dest" must be files.  Directories or symlinks are not allowed.
Intermediate paths must not be symlinks either.

Parent directories of "dest" will be automatically created if missing.

### Element linkfile

It's just like copyfile and runs at the same time as copyfile but
instead of copying it creates a symlink.

The symlink is created at "dest" (relative to the top of the tree) and
points to the path specified by "src" which is a path in the project.

Parent directories of "dest" will be automatically created if missing.

The symlink target may be a file or directory, but it may not point outside
of the repo client.

### Element remove-project

Deletes the named project from the internal manifest table, possibly
allowing a subsequent project element in the same manifest file to
replace the project with a different source.

This element is mostly useful in a local manifest file, where
the user can remove a project, and possibly replace it with their
own definition.

Attribute `optional`: Set to true to ignore remove-project elements with no
matching `project` element.

### Element repo-hooks

NB: See the [practical documentation](./repo-hooks.md) for using repo hooks.

Only one repo-hooks element may be specified at a time.
Attempting to redefine it will fail to parse.

Attribute `in-project`: The project where the hooks are defined.  The value
must match the `name` attribute (**not** the `path` attribute) of a previously
defined `project` element.

Attribute `enabled-list`: List of hooks to use, whitespace or comma separated.

### Element superproject

***
*Note*: This is currently a WIP.
***

NB: See the [git superprojects documentation](
https://en.wikibooks.org/wiki/Git/Submodules_and_Superprojects) for background
information.

This element is used to specify the URL of the superproject. It has "name" and
"remote" as atrributes. Only "name" is required while the others have
reasonable defaults. At most one superproject may be specified.
Attempting to redefine it will fail to parse.

Attribute `name`: A unique name for the superproject. This attribute has the
same meaning as project's name attribute. See the
[element project](#element-project) for more information.

Attribute `remote`: Name of a previously defined remote element.
If not supplied the remote given by the default element is used.

Attribute `revision`: Name of the Git branch the manifest wants
to track for this superproject. If not supplied the revision given
by the remote element is used if applicable, else the default
element is used.

### Element contactinfo

***
*Note*: This is currently a WIP.
***

This element is used to let manifest authors self-register contact info.
It has "bugurl" as a required atrribute. This element can be repeated,
and any later entries will clobber earlier ones. This would allow manifest
authors who extend manifests to specify their own contact info.

Attribute `bugurl`: The URL to file a bug against the manifest owner.

### Element include

This element provides the capability of including another manifest
file into the originating manifest.  Normal rules apply for the
target manifest to include - it must be a usable manifest on its own.

Attribute `name`: the manifest to include, specified relative to
the manifest repository's root.

"name" may not be an absolute path or use "." or ".." path components.
These restrictions are not enforced for [Local Manifests].

Attribute `groups`: List of additional groups to which all projects
in the included manifest belong. This appends and recurses, meaning
all projects in included manifests carry all parent include groups.
Same syntax as the corresponding element of `project`.

## Local Manifests {#local-manifests}

Additional remotes and projects may be added through local manifest
files stored in `$TOP_DIR/.repo/local_manifests/*.xml`.

For example:

    $ ls .repo/local_manifests
    local_manifest.xml
    another_local_manifest.xml

    $ cat .repo/local_manifests/local_manifest.xml
    <?xml version="1.0" encoding="UTF-8"?>
    <manifest>
      <project path="manifest"
               name="tools/manifest" />
      <project path="platform-manifest"
               name="platform/manifest" />
    </manifest>

Users may add projects to the local manifest(s) prior to a `repo sync`
invocation, instructing repo to automatically download and manage
these extra projects.

Manifest files stored in `$TOP_DIR/.repo/local_manifests/*.xml` will
be loaded in alphabetical order.

Projects from local manifest files are added into
local::<local manifest filename> group.

The legacy `$TOP_DIR/.repo/local_manifest.xml` path is no longer supported.


[copyfile]: #Element-copyfile
[linkfile]: #Element-linkfile
[Local Manifests]: #local-manifests
