# repo hooks

[TOC]

Repo provides a mechanism to hook specific stages of the runtime with custom
python modules.  All the hooks live in one git project which is checked out by
the manifest (specified during `repo init`), and the manifest itself defines
which hooks are registered.

These are useful to run linters, check formatting, and run quick unittests
before allowing a step to proceed (e.g. before uploading a commit to Gerrit).

A complete example can be found in the Android project.  It can be easily
re-used by any repo based project and is not specific to Android.<br>
https://android.googlesource.com/platform/tools/repohooks

## Approvals

When a hook is processed the first time, the user is prompted for approval.
We don't want to execute arbitrary code without explicit consent.  For manifests
fetched via secure protocols (e.g. https://), the user is prompted once.  For
insecure protocols (e.g. http://), the user is prompted whenever the registered
repohooks project is updated and a hook is triggered.

## Manifest Settings

For the full syntax, see the [repo manifest format](./manifest-format.md).

Here's a short example from
[Android](https://android.googlesource.com/platform/manifest/+/HEAD/default.xml).
The `<project>` line checks out the repohooks git repo to the local
`tools/repohooks/` path.  The `<repo-hooks>` line says to look in the project
with the name `platform/tools/repohooks` for hooks to run during the
`pre-upload` phase.

```xml
<project path="tools/repohooks" name="platform/tools/repohooks" />
<repo-hooks in-project="platform/tools/repohooks" enabled-list="pre-upload" />
```

## Source Layout

The repohooks git repo should have a python file with the same name as the hook.
So if you want to support the `pre-upload` hook, you'll need to create a file
named `pre-upload.py`.  Repo will dynamically load that module when processing
the hook and then call the `main` function in it.

Hooks should have their `main` accept `**kwargs` for future compatibility.

## Runtime

Hook return values are ignored.

Any uncaught exceptions from the hook will cause the step to fail.  This is
intended as a fallback safety check though rather than the normal flow.  If
you want your hook to trigger a failure, it should call `sys.exit()` (after
displaying relevant diagnostics).

Output (stdout & stderr) are not filtered in any way.  Hooks should generally
not be too verbose.  A short summary is nice, and some status information when
long running operations occur, but long/verbose output should be used only if
the hook ultimately fails.

The hook runs from the top level of the repo client where the operation is
started.
For example, if the repo client is under `~/tree/`, then that is where the hook
runs, even if you ran repo in a git repository at `~/tree/src/foo/`, or in a
subdirectory of that git repository in `~/tree/src/foo/bar/`.
Hooks frequently start off by doing a `os.chdir` to the specific project they're
called on (see below) and then changing back to the original dir when they're
finished.

Python's `sys.path` is modified so that the top of repohooks directory comes
first.  This should help simplify the hook logic to easily allow importing of
local modules.

Repo does not modify the state of the git checkout.  This means that the hooks
might be running in a dirty git repo with many commits and checked out to the
latest one.  If the hook wants to operate on specific git commits, it needs to
manually discover the list of pending commits, extract the diff/commit, and
then check it directly.  Hooks should not normally modify the active git repo
(such as checking out a specific commit to run checks) without first prompting
the user.  Although user interaction is discouraged in the common case, it can
be useful when deploying automatic fixes.

### Shebang Handling

*** note
This is intended as a transitional feature.  Hooks are expected to eventually
migrate to Python 3 only as Python 2 is EOL & deprecated.
***

If the hook is written against a specific version of Python (either 2 or 3),
the script can declare that explicitly.  Repo will then attempt to execute it
under the right version of Python regardless of the version repo itself might
be executing under.

Here are the shebangs that are recognized.

* `#!/usr/bin/env python` & `#!/usr/bin/python`: The hook is compatible with
  Python 2 & Python 3.  For maximum compatibility, these are recommended.
* `#!/usr/bin/env python2` & `#!/usr/bin/python2`: The hook requires Python 2.
  Version specific names like `python2.7` are also recognized.
* `#!/usr/bin/env python3` & `#!/usr/bin/python3`: The hook requires Python 3.
  Version specific names like `python3.6` are also recognized.

If no shebang is detected, or does not match the forms above, we assume that the
hook is compatible with both Python 2 & Python 3 as if `#!/usr/bin/python` was
used.

## Hooks

Here are all the points available for hooking.

### pre-upload

This hook runs when people run `repo upload`.

The `pre-upload.py` file should be defined like:

```py
def main(project_list, worktree_list=None, **kwargs):
    """Main function invoked directly by repo.

    We must use the name "main" as that is what repo requires.

    Args:
      project_list: List of projects to run on.
      worktree_list: A list of directories.  It should be the same length as
          project_list, so that each entry in project_list matches with a
          directory in worktree_list.  If None, we will attempt to calculate
          the directories automatically.
      kwargs: Leave this here for forward-compatibility.
    """
```
