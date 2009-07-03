#
# Copyright (C) 2009 The Android Open Source Project
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

from manifest_xml import XmlManifest

def ParseManifest(repodir, type=None):
  if type:
    return type(repodir)
  return XmlManifest(repodir)

_manifest = None

def GetManifest(repodir, reparse=False, type=None):
  global _manifest
  if _manifest is None \
  or reparse \
  or (type and _manifest.__class__ != type):
    _manifest = ParseManifest(repodir, type=type)
  return _manifest
