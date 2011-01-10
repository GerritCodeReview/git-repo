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
import optparse
import sys

from error import NoSuchProjectError

class Command(object):
  """Base class for any command line action in repo.
  """

  common = False
  manifest = None
  _optparse = None

  def WantPager(self, opt):
    return False

  @property
  def OptionParser(self):
    if self._optparse is None:
      try:
        me = 'repo %s' % self.NAME
        usage = self.helpUsage.strip().replace('%prog', me)
      except AttributeError:
        usage = 'repo %s' % self.NAME
      self._optparse = optparse.OptionParser(usage = usage)
      self._Options(self._optparse)
    return self._optparse

  def _Options(self, p):
    """Initialize the option parser.
    """

  def Usage(self):
    """Display usage and terminate.
    """
    self.OptionParser.print_usage()
    sys.exit(1)

  def Execute(self, opt, args):
    """Perform the action, after option parsing is complete.
    """
    raise NotImplementedError
 
  def GetProjects(self, args, missing_ok=False):
    """A list of projects that match the arguments.
    """
    all = self.manifest.projects
    result = []

    if not args:
      for project in all.values():
        if missing_ok or project.Exists:
          result.append(project)
    else:
      by_path = None

      for arg in args:
        project = all.get(arg)

        if not project:
          path = os.path.abspath(arg).replace('\\', '/')

          if not by_path:
            by_path = dict()
            for p in all.values():
              by_path[p.worktree] = p

          if os.path.exists(path):
            oldpath = None
            while path \
              and path != oldpath \
              and path != self.manifest.topdir:
              try:
                project = by_path[path]
                break
              except KeyError:
                oldpath = path
                path = os.path.dirname(path)
          else:
            try:
              project = by_path[path]
            except KeyError:
              pass

        if not project:
          raise NoSuchProjectError(arg)
        if not missing_ok and not project.Exists:
          raise NoSuchProjectError(arg)

        result.append(project)

    def _getpath(x):
      return x.relpath
    result.sort(key=_getpath)
    return result

class InteractiveCommand(Command):
  """Command which requires user interaction on the tty and
     must not run within a pager, even if the user asks to.
  """
  def WantPager(self, opt):
    return False

class PagedCommand(Command):
  """Command which defaults to output in a pager, as its
     display tends to be larger than one screen full.
  """
  def WantPager(self, opt):
    return True

class MirrorSafeCommand(object):
  """Command permits itself to run within a mirror,
     and does not require a working directory.
  """
