# repo hooks

[TOC]

Repo provides a mechanism to hook specific stages of the runtime with custom
python modules.  All the hooks live in one git project which is checked out by
the manifest (specified during `repo init`), and the manifest itself defines
which hooks are registered.

A complete example can be found in the Android project.  It can be easily
re-used by any repo based project and is not specific to Android.<br>
https://android.googlesource.com/platform/tools/repohooks

## Approvals

When a hook is processed the first time, the user is prompted for approval.
We don't want to execute arbitrary code without explicit consent.  For manifests
fetched via secure protocols (e.g. https://), the user is prompted once.  For
insecure protocols (e.g. http://), the user is prompted whenever the registered
repohooks project is updated and that hooks is triggered.

## Manifest Settings

For the full syntax, see the [repo manifest format](./manifest-format.txt).

Here's a short example from
[Android](https://android.googlesource.com/platform/manifest/+/master/default.xml).
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
you want your hook to trigger a failure, it should call `sys.exit()`.

Output (stdout & stderr) are not filtered in any way.  Hooks should generally
not be too verbose.  A short summary is nice, and some status information when
long running operations occur, but long/verbose output should be used only if
the hook ultimately fails.

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
