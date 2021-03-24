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
import multiprocessing
import os
import sys

from command import Command, DEFAULT_LOCAL_JOBS, WORKER_BATCH_SIZE
from git_config import IsImmutable
from git_command import git
import gitc_utils
from progress import Progress
from project import SyncBuffer


class Start(Command):
  common = True
  helpSummary = "Start a new branch for development"
  helpUsage = """
%prog <newbranchname> [--all | <project>...]
"""
  helpDescription = """
'%prog' begins a new branch of development, starting from the
revision specified in the manifest.
"""
  PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

  def _Options(self, p):
    super()._Options(p)
    p.add_option('--all',
                 dest='all', action='store_true',
                 help='begin branch in all projects')
    p.add_option('-r', '--rev', '--revision', dest='revision',
                 help='point branch at this revision instead of upstream')
    p.add_option('--head', '--HEAD',
                 dest='revision', action='store_const', const='HEAD',
                 help='abbreviation for --rev HEAD')

  def ValidateOptions(self, opt, args):
    if not args:
      self.Usage()

    nb = args[0]
    if not git.check_ref_format('heads/%s' % nb):
      self.OptionParser.error("'%s' is not a valid name" % nb)

  def _ExecuteOne(self, opt, nb, project):
    """Start one project."""
    # If the current revision is immutable, such as a SHA1, a tag or
    # a change, then we can't push back to it. Substitute with
    # dest_branch, if defined; or with manifest default revision instead.
    branch_merge = ''
    if IsImmutable(project.revisionExpr):
      if project.dest_branch:
        branch_merge = project.dest_branch
      else:
        branch_merge = self.manifest.default.revisionExpr

    try:
      ret = project.StartBranch(
          nb, branch_merge=branch_merge, revision=opt.revision)
    except Exception as e:
      print('error: unable to checkout %s: %s' % (project.name, e), file=sys.stderr)
      ret = False
    return (ret, project)

  def Execute(self, opt, args):
    nb = args[0]
    err = []
    projects = []
    if not opt.all:
      projects = args[1:]
      if len(projects) < 1:
        projects = ['.']  # start it in the local project by default

    all_projects = self.GetProjects(projects,
                                    missing_ok=bool(self.gitc_manifest))

    # This must happen after we find all_projects, since GetProjects may need
    # the local directory, which will disappear once we save the GITC manifest.
    if self.gitc_manifest:
      gitc_projects = self.GetProjects(projects, manifest=self.gitc_manifest,
                                       missing_ok=True)
      for project in gitc_projects:
        if project.old_revision:
          project.already_synced = True
        else:
          project.already_synced = False
          project.old_revision = project.revisionExpr
        project.revisionExpr = None
      # Save the GITC manifest.
      gitc_utils.save_manifest(self.gitc_manifest)

      # Make sure we have a valid CWD
      if not os.path.exists(os.getcwd()):
        os.chdir(self.manifest.topdir)

      pm = Progress('Syncing %s' % nb, len(all_projects))
      for project in all_projects:
        gitc_project = self.gitc_manifest.paths[project.relpath]
        # Sync projects that have not been opened.
        if not gitc_project.already_synced:
          proj_localdir = os.path.join(self.gitc_manifest.gitc_client_dir,
                                       project.relpath)
          project.worktree = proj_localdir
          if not os.path.exists(proj_localdir):
            os.makedirs(proj_localdir)
          project.Sync_NetworkHalf()
          sync_buf = SyncBuffer(self.manifest.manifestProject.config)
          project.Sync_LocalHalf(sync_buf)
          project.revisionId = gitc_project.old_revision
        pm.update()
      pm.end()

    def _ProcessResults(results):
      for (result, project) in results:
        if not result:
          err.append(project)
        pm.update()

    pm = Progress('Starting %s' % nb, len(all_projects))
    # NB: Multiprocessing is heavy, so don't spin it up for one job.
    if len(all_projects) == 1 or opt.jobs == 1:
      _ProcessResults(self._ExecuteOne(opt, nb, x) for x in all_projects)
    else:
      with multiprocessing.Pool(opt.jobs) as pool:
        results = pool.imap_unordered(
            functools.partial(self._ExecuteOne, opt, nb), all_projects,
            chunksize=WORKER_BATCH_SIZE)
        _ProcessResults(results)
    pm.end()

    if err:
      for p in err:
        print("error: %s/: cannot start %s" % (p.relpath, nb),
              file=sys.stderr)
      sys.exit(1)
