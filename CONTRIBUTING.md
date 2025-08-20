# Submitting Changes

Here's a short overview of the process.

*   Make small logical changes.
*   [Provide a meaningful commit message][commit-message-style].
*   Make sure all code is under the Apache License, 2.0.
*   Publish your changes for review.
    *   `git push origin HEAD:refs/for/main`
*   Make corrections if requested.
*   [Verify your changes on Gerrit.](#verify)
*   [Send to the commit queue for testing & merging.](#cq)

[TOC]

## Long Version

I wanted a file describing how to submit patches for repo,
so I started with the one found in the core Git distribution
(Documentation/SubmittingPatches), which itself was based on the
patch submission guidelines for the Linux kernel.

However there are some differences, so please review and familiarize
yourself with the following relevant bits.


## Make separate commits for logically separate changes.

Unless your patch is really trivial, you should not be sending out a patch that
was generated between your working tree and your commit head.
Instead, always make a commit with a complete
[commit message][commit-message-style] and generate a series of patches from
your repository.
It is a good discipline.

Describe the technical detail of the change(s).

If your description starts to get too long, that's a sign that you
probably need to split up your commit to finer grained pieces.


## Linting and formatting code

Lint any changes by running:
```sh
$ tox -e lint -- file.py
```

And format with:
```sh
$ tox -e format -- file.py
```

Or format everything:
```sh
$ tox -e format
```

Repo uses [black](https://black.readthedocs.io/) with line length of 80 as its
formatter and flake8 as its linter. Repo also follows
[Google's Python Style Guide].

There should be no new errors or warnings introduced.

Warnings that cannot be avoided without going against the Google Style Guide
may be suppressed inline individally using a `# noqa` comment as described
in the [flake8 documentation].

If there are many occurrences of the same warning, these may be suppressed for
the entire project in the included `.flake8` file.

[Google's Python Style Guide]: https://google.github.io/styleguide/pyguide.html
[PEP 8]: https://www.python.org/dev/peps/pep-0008/
[flake8 documentation]: https://flake8.pycqa.org/en/3.1.1/user/ignoring-errors.html#in-line-ignoring-errors

## Running tests

We use [pytest](https://pytest.org/) and [tox](https://tox.readthedocs.io/) for
running tests.  You should make sure to install those first.

To run the full suite against all supported Python versions, simply execute:
```sh
$ tox -p auto
```

We have [`./run_tests`](./run_tests) which is a simple wrapper around `pytest`:
```sh
# Run the full suite against the default Python version.
$ ./run_tests
# List each test as it runs.
$ ./run_tests -v

# Run a specific unittest module (and all tests in it).
$ ./run_tests tests/test_git_command.py

# Run a specific testsuite in a specific unittest module.
$ ./run_tests tests/test_editor.py::EditString

# Run a single test.
$ ./run_tests tests/test_editor.py::EditString::test_cat_editor

# List all available tests.
$ ./run_tests --collect-only

# Run a single test using substring match.
$ ./run_tests -k test_cat_editor
```

The coverage isn't great currently, but it should still be run for all commits.
Adding more unittests for changes you make would be greatly appreciated :).
Check out the [tests/](./tests/) subdirectory for more details.


## Check the license

repo is licensed under the Apache License, 2.0.

Because of this licensing model *every* file within the project
*must* list the license that covers it in the header of the file.
Any new contributions to an existing file *must* be submitted under
the current license of that file.  Any new files *must* clearly
indicate which license they are provided under in the file header.

Please verify that you are legally allowed and willing to submit your
changes under the license covering each file *prior* to submitting
your patch.  It is virtually impossible to remove a patch once it
has been applied and pushed out.


## Sending your patches.

Do not email your patches to anyone.

Instead, login to the Gerrit Code Review tool at:

  https://gerrit-review.googlesource.com/

Ensure you have completed one of the necessary contributor
agreements, providing documentation to the project maintainers that
they have right to redistribute your work under the Apache License:

  https://gerrit-review.googlesource.com/#/settings/agreements

Ensure you have obtained an HTTP password to authenticate:

  https://gerrit-review.googlesource.com/new-password

Ensure that you have the local commit hook installed to automatically
add a ChangeId to your commits:

    curl -Lo `git rev-parse --git-dir`/hooks/commit-msg https://gerrit-review.googlesource.com/tools/hooks/commit-msg
    chmod +x `git rev-parse --git-dir`/hooks/commit-msg

If you have already committed your changes you will need to amend the commit
to get the ChangeId added.

    git commit --amend

Push your patches over HTTPS to the review server, possibly through
a remembered remote to make this easier in the future:

    git config remote.review.url https://gerrit-review.googlesource.com/git-repo
    git config remote.review.push HEAD:refs/for/main

    git push review

You will be automatically emailed a copy of your commits, and any
comments made by the project maintainers.


## Make changes if requested

The project maintainer who reviews your changes might request changes to your
commit. If you make the requested changes you will need to amend your commit
and push it to the review server again.


## Verify your changes on Gerrit {#verify}

After you receive a Code-Review+2 from the maintainer, select the Verified
button on the Gerrit page for the change. This verifies that you have tested
your changes and notifies the maintainer that they are ready to be submitted.

## Merge your changes via the commit queue {#cq}

Once a change is ready to be merged, select the Commit-Queue+2 setting on the
Gerrit page for it. This tells the CI system to test the change, and if it
passes all the checks, automatically merges it.

[commit-message-style]: https://chris.beams.io/posts/git-commit/
