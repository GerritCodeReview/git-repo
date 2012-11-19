#
# Copyright (C) 2012 The Android Open Source Project
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
import subprocess
import urlparse

from error import GerritError
from trace import IsTrace, Trace

SSH = 'ssh'

class GerritCommand(object):
  def __init__(self,
      reviewUrl = None,
      cmdv = None,
      provide_stdin = False,
      capture_stdout = False,
      capture_stderr = False):

    if reviewUrl is None:
      raise GerritError('No reviewUrl')

    try:
      url = urlparse.urlparse(reviewUrl)
      url = url.netloc.split(':')
      url = ["-p %s" % url[1], url[0]]
    except:
      raise GerritError('ReviewUrl malformed %s' % reviewUrl)

    env = os.environ.copy()
    command = [SSH]
    command.extend(url)
    command.extend(['gerrit'])
    if not cmdv is None:
      command.extend(cmdv)

    if provide_stdin:
      stdin = subprocess.PIPE
    else:
      stdin = None

    if capture_stdout:
      stdout = subprocess.PIPE
    else:
      stdout = None

    if capture_stderr:
      stderr = subprocess.PIPE
    else:
      stderr = None

    if IsTrace():
      dbg = ': '
      dbg += ' '.join(command)
      if stdin == subprocess.PIPE:
        dbg += ' 0<|'
      if stdout == subprocess.PIPE:
        dbg += ' 1>|'
      if stderr == subprocess.PIPE:
        dbg += ' 2>|'
      Trace('%s', dbg)

    try:
      p = subprocess.Popen(command,
          env = env,
          stdin = stdin,
          stdout = stdout,
          stderr = stderr)
    except Exception, e:
      raise GerritError('%s: %s' % (command, e))

    self.process = p
    self.stdin = p.stdin

  def Wait(self):
    p = self.process
    (self.stdout, self.stderr) = p.communicate()
    return p.returncode
