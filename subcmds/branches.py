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
from color import Coloring
from command import Command

class BranchColoring(Coloring):
  def __init__(self, config):
    Coloring.__init__(self, config, 'branch')
    self.current = self.printer('current', fg='green')
    self.local   = self.printer('local')
    self.notinproject = self.printer('notinproject', fg='red')

class BranchInfo(object):
  def __init__(self, name):
    self.name = name
    self.current = 0
    self.published = 0
    self.published_equal = 0
    self.projects = []

  def add(self, b):
    if b.current:
      self.current += 1
    if b.published:
      self.published += 1
    if b.revision == b.published:
      self.published_equal += 1
    self.projects.append(b)

  @property
  def IsCurrent(self):
    return self.current > 0

  @property
  def IsPublished(self):
    return self.published > 0

  @property
  def IsPublishedEqual(self):
    return self.published_equal == len(self.projects)


class Branches(Command):
  common = True
  helpSummary = "View current topic branches"
  helpUsage = """
%prog [<project>...]

Summarizes the currently available topic branches.
"""

  def _Options(self, p):
    p.add_option('-a', '--all',
                 dest='all', action='store_true',
                 help='show all branches, not just the majority')

  def Execute(self, opt, args):
    projects = self.GetProjects(args)
    out = BranchColoring(self.manifest.manifestProject.config)
    all = {}
    project_cnt = len(projects)

    for project in projects:
      for name, b in project.GetBranches().iteritems():
        b.project = project
        if name not in all:
          all[name] = BranchInfo(name)
        all[name].add(b)

    names = all.keys()
    names.sort()

    if not opt.all and not args:
      # No -a and no specific projects listed; try to filter the
      # results down to only the majority of projects.
      #
      n = []
      for name in names:
        i = all[name]
        if i.IsCurrent \
        or 80 <= (100 * len(i.projects)) / project_cnt:
          n.append(name)
      names = n

    width = 25
    for name in names:
      if width < len(name):
        width = len(name)

    for name in names:
      i = all[name]
      in_cnt = len(i.projects)

      if i.IsCurrent:
        current = '*'
        hdr = out.current
      else:
        current = ' '
        hdr = out.local

      if i.IsPublishedEqual:
        published = 'P'
      elif i.IsPublished:
        published = 'p'
      else:
        published = ' '

      hdr('%c%c %-*s' % (current, published, width, name))
      out.write(' |')

      if in_cnt < project_cnt and (in_cnt == 1 or opt.all):
        fmt = out.write
        paths = []
        if in_cnt < project_cnt - in_cnt: 
          type = 'in'
          for b in i.projects:
            paths.append(b.project.relpath)
        else:
          fmt = out.notinproject
          type = 'not in'
          have = set()
          for b in i.projects:
            have.add(b.project)
          for p in projects:
            paths.append(p.relpath)

        s = ' %s %s' % (type, ', '.join(paths))
        if width + 7 + len(s) < 80:
          fmt(s)
        else:
          out.nl()
          fmt('    %s:' % type)
          for p in paths:
            out.nl()
            fmt('      %s' % p)
      out.nl()
