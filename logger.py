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

import errno
import inspect
import logging
import logging.handlers
import os
import sys

from pyversion import is_python3

if is_python3():
  basestring = str

ROOT_NAME = 'repo'
LOG_DIR = 'logs'


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
  g_opts.add_option('--no-logging', default=False,
                    dest='no_logging', action='store_true',
                    help='Disable storing log in file')


def build_logger(g_opts, repodir=None):
  """Build the base repo logger.

  Args:
    g_opts (object): contains values all the options from Optparse.
  Kwargs:
    repodir (str): Path of the repo directory. Guessed if not set.

  Returns (Logger): Root repo Logger object that has just been built.
  """
  logger = _get_logger()

  log_level = g_opts.log_level.upper()
  if log_level == 'NONE':
    # no need for any Handlers
    logger.setLevel(logging.NOTSET)
    return logger
  logger.setLevel(log_level)

  log_level = getattr(logging, log_level, logging.INFO)

  if not g_opts.no_logging:
    # Guess the location if not provided
    if repodir is None:
      repodir = os.path.dirname(os.path.dirname(
                                os.path.realpath(__file__)))
    log_dir = os.path.join(repodir, LOG_DIR)

    try:
      os.makedirs(log_dir)
    except OSError as e:
      # bail if we can't make the directory
      if e.errno != errno.EEXIST:
        raise
    log_file = os.path.join(log_dir, 'repo.log')

    fh = logging.handlers.RotatingFileHandler(filename=log_file, backupCount=5)
    fh.doRollover()  # Force a fresh log for new instance of repo.
    fh.setLevel(log_level)  # As above, catch custom levels
    logger.addHandler(fh)
    # TODO: add formatter

  # TODO: add appropriate formatting.
  sh = logging.StreamHandler()
  sh.setLevel(log_level)
  logger.addHandler(sh)

  if log_level < logging.WARNING:
    # Everything else will go to stdout
    sh.setLevel(logging.WARNING)

    # add stdout for anything less than WARNINGS
    sh_out = logging.StreamHandler(stream=sys.stdout)
    sh_out.setLevel(log_level)
    sh_out.addFilter(StreamStdOutFilter())
    logger.addHandler(sh_out)
  return logger


def _get_logger(name=None):
  """Gets a logger that inherits from the base repo logger.

  Kwargs:
    name (str): dot-joined name.
    name (list): dot-joined name, split where dots would be.

  Returns (Logger): Logger whose namespace is based on the repo root name.
  """
  if name is None:
    return logging.getLogger(name=ROOT_NAME)

  # assume it's a list/tuple
  if not isinstance(name, basestring):
    name = '.'.join(name)

  name = '.'.join((ROOT_NAME, name))
  return logging.getLogger(name=name)


def get_logger(name=None):
  """Wraps _get_logger to automatically create names if name is None
  """
  if name is None:
    file_name = inspect.stack()[1][1]
    name = os.path.splitext(file_name)[0]
  return _get_logger(name=name)


class StreamStdOutFilter(object):
  """Filter Stdout stream
  """
  def __init__(self, level=logging.WARNING):
    # level is the upper bound limit, not inclusive.
    self.level = level

  def filter(self, record):
    return record.levelno < self.level
