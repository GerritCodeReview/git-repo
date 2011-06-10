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

class Manifest(PagedCommand):
  common = False
  helpSummary = "Manifest inspection utility"
  helpUsage = """
%prog [-o {-|NAME.xml} [-r] [--intersect MANIFEST.xml [--derive-from-target]]]
"""
  _helpDescription = """

With the -o option, exports the current manifest for inspection.
The manifest and (if present) local_manifest.xml are combined
together to produce a single manifest file.  This file can be stored
in a Git repository for use during future 'repo init' invocations.

"""

  @property
  def helpDescription(self):
    help = self._helpDescription + '\n'
    r = os.path.dirname(__file__)
    r = os.path.dirname(r)
    fd = open(os.path.join(r, 'docs', 'manifest-format.txt'))
    for line in fd:
      help += line
    fd.close()
    return help

  def _Options(self, p):
    p.add_option('-r', '--revision-as-HEAD',
                 dest='peg_rev', action='store_true',
                 help='Save revisions as current HEAD')
    p.add_option('-o', '--output-file',
                 dest='output_file',
                 help='File to save the manifest to',
                 metavar='-|NAME.xml')
    p.add_option('-i', '--intersect-manifest', dest='intersect_manifest',
                 action='store',
                 help='Manifest to perform an intersection '
                 'against.  If -r is specified, intersect behaviour '
                 'is behaved to generate the merge-base as HEAD.')
    p.add_option('-d', '--derive-from-target',
                 default=False, action='store_true',
                 help="normally --intersect-manifest just derives from the "
                 "checked out manifest, filtering that manifest.  This option "
                 "inverts the behaviour; essentially mapping the target into "
                 "into the checked out manifest.  Primarily of use when "
                 "trying to generate intersections for use with the release "
                 "subcommand.  Essentially, think of it this way- without this, "
                 "it'll modify the checked out manifest into an intersection.  "
                 "With this option on, it modifies the target manifest into an "
                 "intersection")

  def _Output(self, opt, manifest):
    if opt.output_file == '-':
      fd = sys.stdout
    else:
      fd = open(opt.output_file, 'w')
    manifest.Save(fd,
                       peg_rev = opt.peg_rev)
    fd.close()
    if opt.output_file != '-':
      print >>sys.stderr, 'Saved manifest to %s' % opt.output_file

  def intersect_manifest(self, source, target, source_is_authorative=True, intersect_rev=False):
    target_paths = dict((p.relpath, p) for p in target.projects.itervalues())
    for source_name, source_p in source.projects.items():
      intersecting_p = target_paths.get(source_p.relpath)
      if intersecting_p is None:
        del source.projects[source_name]
        continue
      elif intersect_rev:
        if source_is_authorative:
          remote_name = source_p.remote.name
        else:
          remote_name = intersecting_p.remote.name
        ref1 = 'remotes/%s/%s' % (remote_name, source_p.revisionExpr)
        ref2 = 'remotes/%s/%s' % (remote_name, intersecting_p.revisionExpr)
        rev = source_p.work_git.merge_base(ref1, ref2)
        source_p.revisionExpr = rev
    return source

  def Execute(self, opt, args):
    if args:
      self.Usage()

    manifest = self.manifest
    if opt.intersect_manifest is not None:
      masking_manifest = XmlManifest(manifest.repodir)
      # note we're exploiting an underlying os.path.join behaviour;
      # join("/dar/foon", "/absolute") == "/absolute"
      masking_manifest.Override(os.path.abspath(opt.intersect_manifest))
      if opt.derive_from_target:
        args = [masking_manifest, manifest]
      else:
        args = [manifest, masking_manifest]
      manifest = self.intersect_manifest(intersect_rev=opt.peg_rev,
        source_is_authorative=not opt.derive_from_target, *args)
      # note that intersect_manifest will rewrite the revision targets
      # as such, peg_rev is no longer needed (it does the exact wrong thing actually)
      # we honor it's intent, while suppressing the save's behaviour since we
      # don't need it converting HEAD to a sha1 (we've already forced the sha1)
      opt.peg_rev = False
    elif opt.derive_from_target:
      print >>sys.stderr, ("--derive-from-target shouldn't be used without "
        "--intersect-manifest")
      sys.exit(1)

    if opt.output_file is not None:
      self._Output(opt, manifest)
      return

    print >>sys.stderr, 'error: no operation to perform'
    print >>sys.stderr, 'error: see repo help manifest'
    sys.exit(1)
