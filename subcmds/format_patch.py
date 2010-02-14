#
# Copyright (C) 2010 The Android Open Source Project
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

from command import Command
from manifest_xml import BaselineXmlManifest
import glob
import shutil
import os


class FormatPatch(Command):
  common = True
  helpSummary = "build patch sets for each project common to a manifest baseline "
  helpUsage = """
%prog <baseline manifest file name>

Provide the manifest file name documenting the baseline 

i.e. repo format-patch eclair-20091115.xml

Will generate the set of patches for each project that is common with
the baseline defined by the file .repo/manifests/eclair-20091115.xml.
"""
  def move_patch_files(self, src, to):
    files = glob.glob(src + '/' + '0*.patch')
    count = 0
    for f in files:
      count += 1
      try:
        shutil.move(f, to)
      except:
        print "no-clobber", os.path.join(to, os.path.basename(f))
    return count

  def FindBaselineProject(self, proj, baseline):
    for b in  baseline.projects:
      if baseline.projects[b].worktree == proj.worktree:
        return baseline.projects[b]
    return 

  start = 1
  
  def Execute(self, opt, args):
    base_manifest = args[-1]
    args = args[:-1]
    baseline = BaselineXmlManifest(self.repodir, base_manifest)

    for project in self.GetProjects(args):
      b = self.FindBaselineProject(project,baseline)
      print 
      if b:
        print project.worktree
        project._FormatPatch(b.revisionId, self.start)
        self.start += self.move_patch_files(project.worktree, project.manifest.topdir)
      else:
        print "NEW PROJECT " + project.worktree

