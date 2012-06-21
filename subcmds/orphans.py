from command import PagedCommand
import os
import glob

def _checkdirs(dirs, proj_dirs, proj_dirs_parents):
  for item in dirs:
    if not os.path.isdir(item):
      print item
      continue
    if item in proj_dirs:
      continue
    if item in proj_dirs_parents:
      _checkdirs(glob.glob('%s/.*' % item) + \
                 glob.glob('%s/*'  % item), \
                 proj_dirs, proj_dirs_parents)
      continue
    print '%s/' % item


class Orphans(PagedCommand):
  helpSummary = "Show directories and files not managed by repo"
  helpUsage = """
%prog
"""
  helpDescription = """
'%prog' searches the working tree for files and directories that
are not managed as projects.  The list is simply printed
"""

  def Execute(self, opt, args):
    os.chdir(self.manifest.topdir)
    proj_dirs = set()
    proj_dirs_parents = set()
    for project in self.GetProjects(None, missing_ok=True):
      proj_dirs.add(project.relpath)
      (head,tail) = os.path.split(project.relpath)
      while head != "":
        proj_dirs_parents.add(head)
        (head,tail) = os.path.split(head)
    proj_dirs.add('.repo')
    _checkdirs(glob.glob('.*') + \
               glob.glob('*'), \
               proj_dirs, proj_dirs_parents)
