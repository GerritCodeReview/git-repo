# -*- coding:utf-8 -*-
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

from __future__ import print_function
import os
import re
import sys
import subprocess
import tempfile

from error import EditorError
import platform_utils


class Editor(object):
  """Manages the user's preferred text editor."""

  _editor = None
  globalConfig = None

  @classmethod
  def _GetEditor(cls):
    if cls._editor is None:
      cls._editor = cls._SelectEditor()
    return cls._editor

  @classmethod
  def _SelectEditor(cls):
    e = os.getenv('GIT_EDITOR')
    if e:
      return e

    if cls.globalConfig:
      e = cls.globalConfig.GetString('core.editor')
      if e:
        return e

    e = os.getenv('VISUAL')
    if e:
      return e

    e = os.getenv('EDITOR')
    if e:
      return e

    if os.getenv('TERM') == 'dumb':
      print(
          """No editor specified in GIT_EDITOR, core.editor, VISUAL or EDITOR.
Tried to fall back to vi but terminal is dumb.  Please configure at
least one of these before using this command.""", file=sys.stderr)
      sys.exit(1)

    return 'vi'

  @classmethod
  def EditString(cls, data):
    """Opens an editor to edit the given content.

    Args:
      data: The text to edit.

    Returns:
      New value of edited text.

    Raises:
      EditorError: The editor failed to run.
    """
    editor = cls._GetEditor()
    if editor == ':':
      return data

    fd, path = tempfile.mkstemp()
    try:
      os.write(fd, data.encode('utf-8'))
      os.close(fd)
      fd = None

      if platform_utils.isWindows():
        # Split on spaces, respecting quoted strings
        import shlex
        args = shlex.split(editor)
        shell = False
      elif re.compile("^.*[$ \t'].*$").match(editor):
        args = [editor + ' "$@"', 'sh']
        shell = True
      else:
        args = [editor]
        shell = False
      args.append(path)

      try:
        rc = subprocess.Popen(args, shell=shell).wait()
      except OSError as e:
        raise EditorError('editor failed, %s: %s %s'
                          % (str(e), editor, path))
      if rc != 0:
        raise EditorError('editor failed with exit status %d: %s %s'
                          % (rc, editor, path))

      with open(path, mode='rb') as fd2:
        return fd2.read().decode('utf-8')
    finally:
      if fd:
        os.close(fd)
      platform_utils.remove(path)
