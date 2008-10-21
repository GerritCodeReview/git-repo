#
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

import os
import sys
import tempfile

from command import Command
from error import GitError, NoSuchProjectError
from git_config import IsId
from import_tar import ImportTar
from import_zip import ImportZip
from project import Project
from remote import Remote

def _ToCommit(project, rev):
  return project.bare_git.rev_parse('--verify', '%s^0' % rev)

def _Missing(project, rev):
  return project._revlist('--objects', rev, '--not', '--all')


class ComputeSnapshotCheck(Command):
  common = False
  helpSummary = "Compute the check value for a new snapshot"
  helpUsage = """
%prog -p NAME -v VERSION -s FILE [options]
"""
  helpDescription = """
%prog computes and then displays the proper check value for a
snapshot, so it can be pasted into the manifest file for a project.
"""

  def _Options(self, p):
    g = p.add_option_group('Snapshot description options')
    g.add_option('-p', '--project',
                 dest='project', metavar='NAME',
                 help='destination project name')
    g.add_option('-v', '--version',
                 dest='version', metavar='VERSION',
                 help='upstream version/revision identifier')
    g.add_option('-s', '--snapshot',
                 dest='snapshot', metavar='PATH',
                 help='local tarball path')
    g.add_option('--new-project',
                 dest='new_project', action='store_true',
                 help='destinition is a new project')
    g.add_option('--keep',
                 dest='keep_git', action='store_true',
                 help='keep the temporary git repository')

    g = p.add_option_group('Base revision grafting options')
    g.add_option('--prior',
                 dest='prior', metavar='COMMIT',
                 help='prior revision checksum')

    g = p.add_option_group('Path mangling options')
    g.add_option('--strip-prefix',
                 dest='strip_prefix', metavar='PREFIX',
                 help='remove prefix from all paths on import')
    g.add_option('--insert-prefix',
                 dest='insert_prefix', metavar='PREFIX',
                 help='insert prefix before all paths on import')


  def _Compute(self, opt):
    try:
      real_project = self.GetProjects([opt.project])[0]
    except NoSuchProjectError:
      if opt.new_project:
        print >>sys.stderr, \
          "warning: project '%s' does not exist" % opt.project
      else:
        raise NoSuchProjectError(opt.project)

    self._tmpdir = tempfile.mkdtemp()
    project = Project(manifest = self.manifest,
                      name = opt.project,
                      remote = Remote('origin'),
                      gitdir = os.path.join(self._tmpdir, '.git'),
                      worktree = self._tmpdir,
                      relpath = opt.project,
                      revision = 'refs/heads/master')
    project._InitGitDir()

    url = 'file://%s' % os.path.abspath(opt.snapshot)

    imp = None
    for cls in [ImportTar, ImportZip]:
      if cls.CanAccept(url):
        imp = cls()
        break
    if not imp:
      print >>sys.stderr, 'error: %s unsupported' % opt.snapshot
      sys.exit(1)

    imp.SetProject(project)
    imp.SetVersion(opt.version)
    imp.AddUrl(url)

    if opt.prior:
      if opt.new_project:
        if not IsId(opt.prior):
          print >>sys.stderr, 'error: --prior=%s not valid' % opt.prior
          sys.exit(1)
      else:
        try:
          opt.prior = _ToCommit(real_project, opt.prior)
          missing = _Missing(real_project, opt.prior)
        except GitError, e:
          print >>sys.stderr,\
            'error: --prior=%s not valid\n%s' \
            % (opt.prior, e)
          sys.exit(1)
        if missing:
          print >>sys.stderr,\
            'error: --prior=%s is valid, but is not reachable' \
            % opt.prior
          sys.exit(1)
      imp.SetParent(opt.prior)

    src = opt.strip_prefix
    dst = opt.insert_prefix
    if src or dst:
      if src is None:
        src = ''
      if dst is None:
        dst = ''
      imp.RemapPath(src, dst)
    commitId = imp.Import()

    print >>sys.stderr,"%s\t%s" % (commitId, imp.version)
    return project

  def Execute(self, opt, args):
    if args \
       or not opt.project \
       or not opt.version \
       or not opt.snapshot:
      self.Usage()

    success = False
    project = None
    try:
      self._tmpdir = None
      project = self._Compute(opt)
    finally:
      if project and opt.keep_git:
        print 'GIT_DIR = %s' % (project.gitdir)
      elif self._tmpdir:
        for root, dirs, files in os.walk(self._tmpdir, topdown=False):
          for name in files:
            os.remove(os.path.join(root, name))
          for name in dirs:
            os.rmdir(os.path.join(root, name))
        os.rmdir(self._tmpdir)

