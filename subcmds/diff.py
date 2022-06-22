# Copyright (C) 2008 The Android Open Source Project
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

import functools
import io

from command import DEFAULT_LOCAL_JOBS, PagedCommand


class Diff(PagedCommand):
  COMMON = True
  helpSummary = "Show changes between commit and working tree"
  helpUsage = """
%prog [<project>...]

The -u option causes '%prog' to generate diff output with file paths
relative to the repository root, so the output can be applied
to the Unix 'patch' command.
"""
  PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

  def _Options(self, p):
    p.add_option('-u', '--absolute',
                 dest='absolute', action='store_true',
                 help='paths are relative to the repository root')

  def _ExecuteOne(self, absolute, local, project):
    """Obtains the diff for a specific project.

    Args:
      absolute: Paths are relative to the root.
      local: a boolean, if True, the path is relative to the local
             (sub)manifest.  If false, the path is relative to the
             outermost manifest.
      project: Project to get status of.

    Returns:
      The status of the project.
    """
    buf = io.StringIO()
    ret = project.PrintWorkTreeDiff(absolute, output_redir=buf, local=local)
    return (ret, buf.getvalue())

  def Execute(self, opt, args):
    all_projects = self.GetProjects(args, all_manifests=not opt.this_manifest_only)

    def _ProcessResults(_pool, _output, results):
      ret = 0
      for (state, output) in results:
        if output:
          print(output, end='')
        if not state:
          ret = 1
      return ret

    return self.ExecuteInParallel(
        opt.jobs,
        functools.partial(self._ExecuteOne, opt.absolute, opt.this_manifest_only),
        all_projects,
        callback=_ProcessResults,
        ordered=True)
