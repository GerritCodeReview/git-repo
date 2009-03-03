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

import sys
from command import Command

class ExportManifest(Command):
  common = False
  helpSummary = "Export the current manifest"
  helpUsage = """
%prog [-o default.xml]
"""
  helpDescription = """
Exports the current manifest as a flat XML file

The manifest and (if present) local_manifest.xml are combined
together to produce a single manifest file.  This file can be
stored in a Git repository for use during future 'repo init'.
"""

  def _Options(self, p):
    p.add_option('-r',
                 dest='peg_rev', action='store_true',
                 help='Fix revision to the current commit')
    p.add_option('-o', '--output-file',
                 dest='output_file',
                 help='File to save the manifest to', metavar='FILE')

  def Execute(self, opt, args):
    fd = sys.stdout
    if opt.output_file:
      fd = open(opt.output_file, 'w')

    self.manifest.Save(fd,
                       peg_rev = opt.peg_rev)
    fd.close()
