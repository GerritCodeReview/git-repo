#
# Copyright (C) 2015 The Android Open Source Project
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

from __future__ import absolute_import

import errno
import logging
import logging.handlers
import os

from .pyversion import is_python3

if is_python3():
  basestring = str

_root_name = 'repo'
_log_dir = "logs"


def logger_options(g_opts):
  """Adds the logger options to the global options.

  Args:
    g_opts: Instance of optparse.OptionParser.
  """
  g_opts.add_option('--log-level',
                    dest='log_level', default='INFO',
                    choices=('none', 'debug', 'info', 'warning',
                             'error', 'critical'),
                    help='Set the log level.')
  g_opts.add_option('--store-no-log', default=True,
                    dest='store_log', action='store_false',
                    help='Disable storing log in file')


def build_logger(g_opts, repodir=None):
  """Build the base repo logger.

  Args:
    g_opts (object): contains values all the options from Optparse.
  Kwargs:
    repodir (str): Path of the repo directory. Guessed if not set.

  Returns (Logger): Root repo Logger object that has just been built.
  """
  logger = get_logger()
  logger.setLevel(1)  # Set 1 in case of custom levels

  if g_opts.store_log:
    # Guess the location if not provided
    if repodir is None:
      repodir = os.path.dirname(os.path.dirname(
                                os.path.realpath(__file__)))
    log_dir = '/'.join((repodir, _log_dir))
    try:
      os.makedirs(log_dir)
    except OSError as e:
      # bail if we can't make the directory
      if e.errno != errno.EEXIST:
        raise
    log_file = '/'.join((log_dir, 'debug.log'))
    fh = logging.handlers.TimedRotatingFileHandler(
        filename=log_file,
        when='D',
        backupCount=5
    )
    fh.setLevel(1)  # As above, catch custom levels
    logger.addHandler(fh)
    # TODO: add formatter

  log_level = g_opts.log_level.upper()
  if log_level == 'NONE':
    # no need for a StreamHandler
    return logger

  # TODO: add a second StreamHandler, and filter them to redirect
  #       to stdout and stderr appropriately.
  # TODO: add appropriate formatting.
  log_level = getattr(logging, log_level, logging.INFO)
  sh = logging.StreamHandler()
  sh.setLevel(log_level)
  logger.addHandler(sh)
  return logger


def get_logger(name=None):
  """Gets a logger that inherits from the base repo logger.

  Kwargs:
    name (str): dot-joined name.
    name (list): dot-joined name, split where dots would be.

  Returns (Logger): Logger whose namespace is based on the repo root name.
  """
  if name is None:
    return logging.getLogger(name=_root_name)

  # assume it's a list/tuple
  if not isinstance(name, basestring):
    name = '.'.join(name)

  name = '.'.join((_root_name, name))
  return logging.getLogger(name=name)
