repo Client Structure
================

A repo client is a directory structure that contains Git repository clones defined
in the manifest, along with the manifest itself, a clone of the manifest Git
repository, and a clone of the repo Git repository.

The root directory of a repo client contains the **repo client workspace** and the **repo client
private directory**.  The repo client workspace contains Git repository clones
as described in the manifest; the repo client private directory is the
directory **.repo** at the root of the repo client workspace.

The repo client structure is designed to support multiple copies of the same
project at different paths in the workspace.  For example the manifest might
contain...

    <project name="hellow" path="master" revision="master">
    <project name="hellow" path="integration" revision="integration">

In this case the remote repo named hellow will exist twice in the repo client
workspace - once in a directory named *master* with version *master* checked
out, and once in a directory named *integration* with version *integration*
checked out.

repo Client Workspace
---------------------

The repo client workspace contains Git repository clones as described in the
manifest.

Each clone is a clone of the repo named for the *name* attribute of the project,
from the remote named for the *remote* attribute, and is stored in a directory
named for the *path* attribute of the project or if *path* is not set then *name*.

Many of the key .git directories in the clones are really symlinks back to
a central clone of the repo held in the repo client private directory.  This
is done so that it is possible to have multiple clones of the same repo,
without the clones getting out of sync with each other.

Each clone initially has no local heads and has a detached HEAD.
As topic branches are created, they become local branches.  Each clone has a
complete set of remote branches for the remote specified in the manigest.

repo Client Private Directory
-----------------------------

The repo client private directory is named `.repo` and is directly under
the root of the repo client workspace.  It contains:

* **manifest.git**: a bare clone of the manifest repo.

* **manifests**: a repo created from manifest.git by symlinking most files
from manifest.git.  The working tree of this repo has the correct
head checked out.

* **manifest.xml**: a symlink to the manifest in **manifests**

* **project.list**: a text file containing a list of the local project paths
(note - not the project names).

* **project-objects**: bare Git repository clones for all projects listed in the manifest, stored by
the project name.  Note that if the same project is listed multiple times in the manifest with a
different path each time, it will only have one bare clone in **project-objects**.

* **projects**: This directory contains bare repositories created by partially copying files from the appropriate
Git repository in **project-objects**, and partially by symlinking from there.  The repos in **projects** 
are named for the path for each project rather than the name.

* **repo**: This is a clone of the repo tool Git repository.

* **repo/hooks**: This directory contains .git hooks that are copied to all Git repository
clones in the repo client workspace.  Note that the commit-msg hook is **not** copied
to the manifest repo clone.

* **local_manifests**: This optional directory can contain one or more .xml
manifest files which will override or add to the loaded manifest.  See
manifest-format.md for details.

* **local_manifest.xml**: This optional file can contain settings which will
override or add to the loaded manifest.  See manifest-format.md for details.
The use of this file is deprecated.