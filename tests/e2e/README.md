# Repo End-to-End Tests

These tests run the real `repo` launcher & code (as subprocesses) against a
local git smart HTTP server.  They are hermetic: everything is served from
`127.0.0.1` out of temporary directories, and the user's git config &
environment are ignored.

They run as part of `./run_tests` by default, after the unit tests.

## Running

```sh
# Everything (unit + e2e).
./run_tests

# Only the e2e tests.
./run_tests -m e2e

# Everything but the e2e tests.
./run_tests -m 'not e2e'
```

The suite is skipped automatically when `git http-backend` isn't
available, when git is older than 2.28 (need default branch support and
superproject support), or when not run from a git checkout.
