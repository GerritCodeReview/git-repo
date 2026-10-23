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

## Layout

* `harness.py`: the git server, server-side repos & the repo client.
* `test_init_sync.py`: core `repo init` & `repo sync` options.
* `test_partial_clone.py`: partial clones, incl. the standard Android
  configuration from go/repo-init & go/sync.
* `test_sync_modes.py`: `sync -n`/`-l` & the other sync flags.
* `test_groups.py`: manifest groups.
* `test_workflows.py`: multi-step workflows.
* `test_manifest_regressions.py`: manifests that broke users in the past.
