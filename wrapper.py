# -*- coding:utf-8 -*-
#
# Copyright (C) 2014 The Android Open Source Project
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

from __future__ import print_function
try:
  from importlib.machinery import SourceFileLoader
  _loader = lambda *args: SourceFileLoader(*args).load_module()
except ImportError:
  import imp
  _loader = lambda *args: imp.load_source(*args)
import os


def WrapperPath():
  return os.path.join(os.path.dirname(__file__), 'repo')


_wrapper_module = None


def Wrapper():
  global _wrapper_module
  if not _wrapper_module:
    _wrapper_module = _loader('wrapper', WrapperPath())
  return _wrapper_module
