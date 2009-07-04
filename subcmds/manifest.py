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

import os
import sys

from command import PagedCommand
from manifest_xml import XmlManifest

def _doc(name):
  r = os.path.dirname(__file__)
  r = os.path.dirname(r)
  fd = open(os.path.join(r, 'docs', name))
  try:
    return fd.read()
  finally:
    fd.close()

class Manifest(PagedCommand):
  common = False
  helpSummary = "Manifest inspection utility"
  helpUsage = """
%prog [options]
"""
  _xmlHelp = """

With the -o option, exports the current manifest for inspection.
The manifest and (if present) local_manifest.xml are combined
together to produce a single manifest file.  This file can be stored
in a Git repository for use during future 'repo init' invocations.

"""

  @property
  def helpDescription(self):
    help = ''
    if isinstance(self.manifest, XmlManifest):
      help += self._xmlHelp + '\n' + _doc('manifest_xml.txt')
    if isinstance(self.manifest, SubmoduleManifest):
      help += _doc('manifest_submodule.txt')
    return help

  def _Options(self, p):
    if isinstance(self.manifest, XmlManifest):
      p.add_option('-r', '--revision-as-HEAD',
                   dest='peg_rev', action='store_true',
                   help='Save revisions as current HEAD')
      p.add_option('-o', '--output-file',
                   dest='output_file',
                   help='File to save the manifest to',
                   metavar='-|NAME.xml')

  def _Output(self, opt):
    if opt.output_file == '-':
      fd = sys.stdout
    else:
      fd = open(opt.output_file, 'w')
    self.manifest.Save(fd,
                       peg_rev = opt.peg_rev)
    fd.close()
    if opt.output_file != '-':
      print >>sys.stderr, 'Saved manifest to %s' % opt.output_file

  def Execute(self, opt, args):
    if args:
      self.Usage()

    if  isinstance(self.manifest, XmlManifest) \
    and opt.output_file is not None:
        self._Output(opt)
        return

    print >>sys.stderr, 'error: no operation to perform'
    print >>sys.stderr, 'error: see repo help manifest'
    sys.exit(1)
