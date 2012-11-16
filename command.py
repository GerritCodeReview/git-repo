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
import platform
import re
import sys

from error import NoSuchProjectError
from error import InvalidProjectGroupsError


class Command(object):
  """Base class for any command line action in repo.
  """

  common = False
  manifest = None
  _optparse = None

  def WantPager(self, opt):
    return False

  def ReadEnvironmentOptions(self, opts):
    """ Set options from environment variables. """

    env_options = self._RegisteredEnvironmentOptions()

    for env_key, opt_key in env_options.items():
      # Get the user-set option value if any
      opt_value = getattr(opts, opt_key)

      # If the value is set, it means the user has passed it as a command
      # line option, and we should use that.  Otherwise we can try to set it
      # with the value from the corresponding environment variable.
      if opt_value is not None:
        continue

      env_value = os.environ.get(env_key)
      if env_value is not None:
        setattr(opts, opt_key, env_value)

    return opts

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

  def _RegisteredEnvironmentOptions(self):
    """Get options that can be set from environment variables.

    Return a dictionary mapping environment variable name
    to option key name that it can override.

    Example: {'REPO_MY_OPTION': 'my_option'}

    Will allow the option with key value 'my_option' to be set
    from the value in the environment variable named 'REPO_MY_OPTION'.

    Note: This does not work properly for options that are explicitly
    set to None by the user, or options that are defined with a
    default value other than None.

    """
    return {}

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
    all_projects = self.manifest.projects
    result = []

    mp = self.manifest.manifestProject

    groups = mp.config.GetString('manifest.groups')
    if not groups:
      groups = 'all,-notdefault,platform-' + platform.system().lower()
    groups = [x for x in re.split(r'[,\s]+', groups) if x]

    if not args:
      for project in all_projects.values():
        if ((missing_ok or project.Exists) and
            project.MatchesGroups(groups)):
          result.append(project)
    else:
      by_path = None

      for arg in args:
        project = all_projects.get(arg)

        if not project:
          path = os.path.abspath(arg).replace('\\', '/')

          if not by_path:
            by_path = dict()
            for p in all_projects.values():
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
        if not project.MatchesGroups(groups):
          raise InvalidProjectGroupsError(arg)

        result.append(project)

    def _getpath(x):
      return x.relpath
    result.sort(key=_getpath)
    return result

# pylint: disable=W0223
# Pylint warns that the `InteractiveCommand` and `PagedCommand` classes do not
# override method `Execute` which is abstract in `Command`.  Since that method
# is always implemented in classes derived from `InteractiveCommand` and
# `PagedCommand`, this warning can be suppressed.
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

# pylint: enable=W0223

class MirrorSafeCommand(object):
  """Command permits itself to run within a mirror,
     and does not require a working directory.
  """
