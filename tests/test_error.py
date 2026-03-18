# Copyright (C) 2021 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unittests for the error.py module."""

import inspect
import pickle
from typing import Iterator, Type

import pytest

import command
import error
import fetch
import git_command
import project
from subcmds import all_modules


_IMPORTS = all_modules + [
    error,
    project,
    git_command,
    fetch,
    command,
]


def get_exceptions() -> Iterator[Type[Exception]]:
    """Return all our custom exceptions."""
    for entry in _IMPORTS:
        for name in dir(entry):
            cls = getattr(entry, name)
            if isinstance(cls, type) and issubclass(cls, Exception):
                yield cls


def test_exception_lookup() -> None:
    """Make sure our introspection logic works."""
    classes = list(get_exceptions())
    assert error.HookError in classes
    # Don't assert the exact number to avoid being a change-detector test.
    assert len(classes) > 10


@pytest.mark.parametrize("cls", get_exceptions())
def test_pickle(cls: Type[Exception]) -> None:
    """Try to pickle all the exceptions."""
    args = inspect.getfullargspec(cls.__init__).args[1:]
    obj = cls(*args)
    p = pickle.dumps(obj)
    try:
        newobj = pickle.loads(p)
    except Exception as e:
        pytest.fail(
            f"Class {cls} is unable to be pickled: {e}\n"
            "Incomplete super().__init__(...) call?"
        )
    assert isinstance(newobj, cls)
    assert str(obj) == str(newobj)
