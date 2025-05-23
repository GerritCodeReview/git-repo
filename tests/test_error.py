# Copyright 2021 The Android Open Source Project
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
import unittest

import error


class PickleTests(unittest.TestCase):
  """Make sure all our custom exceptions can be pickled."""

  def getExceptions(self):
    """Return all our custom exceptions."""
    for name in dir(error):
      cls = getattr(error, name)
      if isinstance(cls, type) and issubclass(cls, Exception):
        yield cls

  def testExceptionLookup(self):
    """Make sure our introspection logic works."""
    classes = list(self.getExceptions())
    self.assertIn(error.HookError, classes)
    # Don't assert the exact number to avoid being a change-detector test.
    self.assertGreater(len(classes), 10)

  def testPickle(self):
    """Try to pickle all the exceptions."""
    for cls in self.getExceptions():
      args = inspect.getfullargspec(cls.__init__).args[1:]
      obj = cls(*args)
      p = pickle.dumps(obj)
      try:
        newobj = pickle.loads(p)
      except Exception as e:  # pylint: disable=broad-except
        self.fail('Class %s is unable to be pickled: %s\n'
                  'Incomplete super().__init__(...) call?' % (cls, e))
      self.assertIsInstance(newobj, cls)
      self.assertEqual(str(obj), str(newobj))
