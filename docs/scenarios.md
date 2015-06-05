repo Scenarios
==============

This document describes how to use git repo.  It describes a set of scenarios
and activities that include all features of the tool.  It does not, however,
repeat information that is available in manifest-format.md or in the `git help
SUBCMD` output.

Create a workspace, make changes, push them for review
------------------------------------------------------

All changes made in a repo client workspace are made in the context defined in
a _manifest_.  The manifest is an xml file that is managed in a git repository,
and the `git init` command takes options to specify the git url (normally a
gerrit server), the filename for the manifest (default is `default.xml`), and
the revision (default is `master`).

The manifest contains information that specifies a list of gerrit servers,
and for each server a list of repos to clone.  For details of the manifest schema, see manifest-format.md

Note that there is no necessary relationship between the gerrit server and branch used to
manage the manifest, and the gerrit servers and branches used to manage the
client workspace Git repository clones.

To create an initial unpopulated git repo client:

    repo init -u URL -m NAME.xml -b REVISION

The workspace that is created contains a clone of the manifest repo, a
clone of the repo tool itself, a symlink that identifies exactly which .xml
file contains the manifest, and nothing else.  To populate the workspace:

    repo sync

This will clone all the repos listed in the manifest and will create
clones at the paths with checked out revisions as specified in the manifest.

*repo sync* is also the command that can be used in a populated workspace,
to rebase topic branches (see below).

The repo client workspace that is initially created is not ready for
changes.  All of the Git repository clones in the workspace have *detached
HEADs* which match the head specified in the manifest.  It is possible to
commit to the detached head but it is strongly discouraged - in particular
`repo sync` will delete any changes made in this manner.

To make changes to a git repo client workspace project, use `git start` to
create one or more *topic branches*.  A topic branch always starts at the
revision specified in the manifest.  If one topic branch is created, then
five commits are made on that topic branch, and then a second topic branch
is created, the second topic branch will *not* contain any of the five
commits from the first topic branch.

To switch between topic branches on one or more projects, use `repo checkout`.

To see the current topic branches, use `repo branch` or its alias `repo
branches`.

To permanently delete a topic branch, use `repo abandon`.

To make changes on a topic branch, simply use the normal git commands, `git
add`, `git rm`, `git commit` & etc.  A topic branch is just a git branch, and
so all the git commands for manipulating branches will also work for a topic
branch.

Some repo commands for working in a repo client workspace are:

* `repo cherry-pick` will cherry-pick a change to the current topic branch.
* `repo diff` will show differences between the last commit and the working
tree, in a format suitable for the Unix 'patch' command.
* `repo grep` greps through workspace files in one or more projects looking for
matching lines.  It works in a very similar way to `git grep`.
* `repo stage` adds (or stages) files to the git index in preparation for the
next commit.  This command is very similar to `git add` and its pseudonym `git
stage`.

To pull changes and rebase topic branches in one or more projects, use `repo
sync`.

To push changes from a topic branch to a gerrit server for review, use `repo
upload`.

Once the changes have been reviewed and accepted in gerrit, the topic branches
that contained them can be cleaned up automatically with `repo prune`.


Creating and using a local mirror
---------------------------------

To create a local mirror, use `git init ... --mirror`

Note that the manifest that is used to define the mirror repo client must
define existing branches for the repos being mirrored and those branches must
exist in the repos, even though the branches are never used when creating the
repo clones.

To use a local mirror, use `git init ... --reference MIRROR`.  With this
setting, when running `repo sync`, the mirror will be checked for any objects
to be fetched prior to fetching them from the remote gerrit repos.

Using a different version of the repo tool
------------------------------------------
One of the things that the repo tool does when creating a repo client workspace
is that it clones the full repo tool into the workspace.  By default it does
this from a gerrit server and branch that is hard-coded into the repo frontend.

It is possible to override the server URL and REVISION that the repo tool
should be cloned from, by calling `git init` with the options `--repo-url=URL`
and `--repo-branch=REVISION`.  It may also be necessary to disable verification
of the repo source code with the `--no-repo-veriy` option.

Selecting a subset of repos to clone to a repo client workspace
---------------------------------------------------------------
Each project specified in a manifest can belong to one or more groups.  To
only clone repos that belong to one or more groups, use the `--groups` option.
See the `repo init --help` for details of this option.

If a group starts with 'platform-', e.g. `platform-linux` then you can use the
-p or --platform option to select repos in that group, e.g.
`git init ... --platform linux` will select projects that have the group
`platform-linux` set in the manifest.

Finding the differences between different manifests
---------------------------------------------------
To find the differences - in terms of added or removed projects and revisions -
between the workspaces that would be created by different manifests, use `repo
diffmanifest`.  This takes a manifest name and shows the differences between the
current manifest and the manifest specified on the command line.

Pulling review changes into git repo client
-------------------------------------------
It is possible to pull review changes into the git repo client projects using
`repo download`.  There are four ways to introduce review changes:

1. _default_: checkout the changes in the local project.  This will leave the
project with a *detached HEAD*; before committing any changes on this project
you should use `repo checkout` to switch to a topic branch.

2. *--cherry-pick*: this will apply the change to the local topic branch.

3. *--revert*: this will create a commit that contains the reverse of the
changes, i.e. it will undo the changes, assuming they are in the current
history.

4. *--ff-only*: this will merge the changes to your topic branch, forcing a
fast-forward merge.

repo init options
-----------------
The repo tool has a number of useful options in addition to those mentioned
above:

* *--depth=DEPTH*: passed on to `git clone` - creates a _shallow_ clone with
history truncated to the specified number of revisions.
* *--archive*: checkout an archive instead of a git repository for each
project.  See *git archive*.

repo sync options
-----------------
By default, repo sync will:

* update the manifest,

* add or remove projects based on manifest changes,

* fetch changes for all repos,

* rebase all topic branches if the tracking branch has changed.

`repo sync` actions can be adjusted with these options:

* *--local-only*: only update working tree, don't fetch
* *--network-only*: fetch only, don't update working tree
* *--detach*: detach projects back to manifest revision
* *--current-branch*:  fetch only current branch from server
* *--manifest-name=NAME.xml*: temporary manifest to use for this sync
* *--no-clone-bundle*: disable use of /clone.bundle on HTTP/HTTPS
* *--manifest-server-username=MANIFEST_SERVER_USERNAME*: username to
authenticate with the manifest server
* *--manifest-server-password=MANIFEST_SERVER_PASSWORD*: password to
authenticate with the manifest server
* *--fetch-submodules*: fetch submodules from server
* *--no-tags*: don't fetch tags
* *--smart-sync*: smart sync using manifest from a known good build.  See
the description of the element *manifest-server* in manifest-format.md.
* *--smart-tag=SMART_TAG*: smart sync using manifest from a known tag.  See
the description of the element *manifest-server* in manifest-format.md.

Utilities, status, and other tools
-------------------------
For more details on any subcmd, run `repo help SUBCMD`

* **forall**         Run a shell command in each project
* **help**           Display detailed help on a command
* **version**        Display the version of repo
* **info**           Get info on the manifest branch, current branch or unmerged branches
* **overview**       Deprecated in favor of `repo info -o`
* **list**           List projects and their associated directories
* **status**         Show the working tree status
* **manifest**       Manifest inspection utility
* **selfupdate**     Update repo to the latest version
* **rebase**         Rebase local branches on upstream branch.  This normally happens during `repo sync`
