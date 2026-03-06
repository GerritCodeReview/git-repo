# Repo Tests

There is a mixture of [pytest] & [Python unittest] in here.  We adopted [pytest]
later on but didn't migrate existing tests (since they still work).  New tests
should be written using [pytest] only.

## File layout

*   `test_xxx.py`: Unittests for the `xxx` module in the main repo codebase.
    Modules that are in subdirs normalize the `/` into `_`.
    For example, [test_error.py](./test_error.py) is for the
    [error.py](../error.py) module, and
    [test_subcmds_forall.py](./test_subcmds_forall.py) is for the
    [subcmds/forall.py](../subcmds/forall.py) module.
*   [conftest.py](./conftest.py): Custom pytest fixtures for sharing.
*   [utils_for_test.py](./utils_for_test.py): Helpers for sharing in tests.


[pytest]: https://pytest.org/
[Python unittest]: https://docs.python.org/3/library/unittest.html#unittest.TestCase
