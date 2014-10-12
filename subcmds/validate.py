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
import sys
from command import Command

class Validate(Command):
  wrapper_version = None
  wrapper_path = None

  common = False
  helpSummary = "Manifest validation utility"
  helpUsage = """
%prog [/path/to/manifest.xml]
"""
  helpDescription = """
%prog checks the correctness of manifests according to the XML
Schema of the document structure currently supported.

Without arguments, this command will validate the current
manifest.xml in use.

You can also specify the manifest.xml file to validate as an
optional argument.
"""

  def Execute(self, opt, args):
    mf = self.manifest.manifestFile
    if len(args) == 1:
      mf = args[0]
    elif len(args) > 1:
      self.Usage()

    if not self.manifest.Validate(mf):
      sys.exit(1)

