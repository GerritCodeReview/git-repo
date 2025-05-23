# Supported Python Versions

With Python 2.7 officially going EOL on [01 Jan 2020](https://pythonclock.org/),
we need a support plan for the repo project itself.
Inevitably, there will be a long tail of users who still want to use Python 2 on
their old LTS/corp systems and have little power to change the system.

## Summary

* Python 3.6 (released Dec 2016) is required by default starting with repo-2.x.
* Older versions of Python (e.g. v2.7) may use the legacy feature-frozen branch
  based on repo-1.x.

## Overview

We provide a branch for Python 2 users that is feature-frozen.
Bugfixes may be added on a best-effort basis or from the community, but largely
no new features will be added, nor is support guaranteed.

Users can select this during `repo init` time via the [repo launcher].
Otherwise the default branches (e.g. stable & main) will be used which will
require Python 3.

This means the [repo launcher] needs to support both Python 2 & Python 3, but
since it doesn't import any other repo code, this shouldn't be too problematic.

The main branch will require Python 3.6 at a minimum.
If the system has an older version of Python 3, then users will have to select
the legacy Python 2 branch instead.

### repo hooks

Projects that use [repo hooks] run on independent schedules.
They might migrate to Python 3 earlier or later than us.
To support them, we'll probe the shebang of the hook script and if we find an
interpreter in there that indicates a different version than repo is currently
running under, we'll attempt to reexec ourselves under that.

For example, a hook with a header like `#!/usr/bin/python2` will have repo
execute `/usr/bin/python2` to execute the hook code specifically if repo is
currently running Python 3.

For more details, consult the [repo hooks] documentation.


[repo hooks]: ./repo-hooks.md
[repo launcher]: ../repo
