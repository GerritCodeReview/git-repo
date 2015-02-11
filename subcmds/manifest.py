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

from __future__ import print_function
import os
import sys
import re

from command import PagedCommand
from error import GitParallelError
from git_command import GitCommand

class Manifest(PagedCommand):
  common = False
  helpSummary = "Manifest inspection utility"
  helpUsage = """
%prog [-o {-|NAME.xml} [-r|R][--max-connection=N]]
"""
  _helpDescription = """

With the -o option, exports the current manifest for inspection.
The manifest and (if present) local_manifest.xml are combined
together to produce a single manifest file.  This file can be stored
in a Git repository for use during future 'repo init' invocations.

"""

  @property
  def helpDescription(self):
    helptext = self._helpDescription + '\n'
    r = os.path.dirname(__file__)
    r = os.path.dirname(r)
    fd = open(os.path.join(r, 'docs', 'manifest-format.txt'))
    for line in fd:
      helptext += line
    fd.close()
    return helptext

  def _Options(self, p):
    p.add_option('--max-connection',
                 dest='max_connection', default='50', type='int',
                 help='Default number of max connection for remote query')
    p.add_option('-R', '--revision-as-remote-HEAD',
                 dest='peg_remote_rev', action='store_true',
                 help='Save revisions as remote HEAD')
    p.add_option('-r', '--revision-as-HEAD',
                 dest='peg_rev', action='store_true',
                 help='Save revisions as current HEAD')
    p.add_option('--suppress-upstream-revision', dest='peg_rev_upstream',
                 default=True, action='store_false',
                 help='If in -r mode, do not write the upstream field.  '
                 'Only of use if the branch names for a sha1 manifest are '
                 'sensitive.')
    p.add_option('-o', '--output-file',
                 dest='output_file',
                 default='-',
                 help='File to save the manifest to',
                 metavar='-|NAME.xml')


  def _GetRemoteHash(self, opt):
    projects = []
    mp = self.manifest.manifestProject
    groups = mp.config.GetString('manifest.groups')
    if groups:
      groups = [x for x in re.split(r'[,\s]+', groups) if x]
    project_names = set(p.name for p in self.manifest.projects if not p.parent)
    for project_name in project_names:
      for project in self.manifest.GetProjectsWithName(project_name):
        if not project.MatchesGroups(groups) or project in projects:
          continue
        projects.append(project)

    def _GetProjectsRemoteHash(projects):
      import math
      max_connection = opt.max_connection
      execute_steps = int(math.ceil(len(projects) / float(max_connection)))

      for execute_step in xrange(execute_steps):
        output_dict = {}
        begin_idx = execute_step * max_connection
        end_idx = begin_idx + max_connection
        current_projects = projects[begin_idx:end_idx]
        for project in current_projects:
          cmd = ['ls-remote']
          cmd.append(project.remote.url)
          cmd.append(project.revisionExpr)
          p = GitCommand(project, cmd,
                         cwd=os.getcwd(),
                         capture_stdout=True,
                         capture_stderr=True)
          output_dict[project.name] = p

        for key in output_dict:
          if not output_dict[key].Wait() == 0:
            raise GitParallelError(output_dict[key].stdout.strip())
          out[key] = output_dict[key].stdout.strip().split()[0]
    out = {}
    _GetProjectsRemoteHash(projects)
    return out

  def _Output(self, opt):
    if opt.output_file == '-':
      fd = sys.stdout
    else:
      fd = open(opt.output_file, 'w')

    if opt.peg_remote_rev:
      hash_dict = self._GetRemoteHash(opt)
      self.manifest.Save(fd,
                         peg_rev=opt.peg_rev,
                         peg_rev_upstream=opt.peg_rev_upstream,
                         assigned_hash_dict=hash_dict)
    else:
      self.manifest.Save(fd,
                         peg_rev=opt.peg_rev,
                         peg_rev_upstream=opt.peg_rev_upstream)
    fd.close()

    if opt.output_file != '-':
      print('Saved manifest to %s' % opt.output_file, file=sys.stderr)

  def Execute(self, opt, args):
    if args:
      self.Usage()

    if opt.output_file is not None:
      self._Output(opt)
      return

    print('error: no operation to perform', file=sys.stderr)
    print('error: see repo help manifest', file=sys.stderr)
    sys.exit(1)
