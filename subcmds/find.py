#
# Copyright (C) 2012 The Android Open Source Project
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

import re
from command import PagedCommand
from color import Coloring

class _Coloring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, "repofind")

class Find(PagedCommand):
  common = True
  helpSummary = "Quickly find project name and mount path for a project"
  helpUsage = "%prog str1 [str2]..."
  helpDescription = """
    %prog can be used to quickly find the project name or the
    mount path for a project or part of a project name.

    Examples:
    # %prog find wpa

    This will find all projects where the project name or the mount path
    includes the string wpa.

    # %prog find kernel

    Will find both the standard kernel as well as the qemu kernel in prebuilts.

    # %prog find wpa kernel

    Will find all projects where the name or path includes either wpa or kernel.

  """

  def Execute(self, opt, args):
    self.out = _Coloring(self.manifest.globalConfig)
    self.text = self.out.printer('text')

    for project in self.GetProjects(''):
      for arg in args:
        pattern = r'.*%s.*' % arg
        matchName = re.search(pattern, project.name, re.IGNORECASE)
        matchPath = re.search(pattern, project.worktree, re.IGNORECASE)
        if matchName or matchPath:
          self.text(project.name)
          self.out.nl()
          self.text(project.worktree)
          self.out.nl()
          self.out.nl()
