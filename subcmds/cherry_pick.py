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

import sys, re, string, random, os
from command import Command
from git_command import GitCommand

CHANGE_ID_RE = re.compile(r'^\s*Change-Id: I([0-9a-f]{40})\s*$')

class CherryPick(Command):
  common = True
  helpSummary = "Cherry-pick a change."
  helpUsage = """
%prog <sha1>
"""
  helpDescription = """
'%prog' cherry-picks a change from one branch to another.
The change id will be updated, and a reference to the old
change id will be added.
"""

  def _Options(self, p):
    pass

  def Execute(self, opt, args):
    if not args:
      self.Usage()

    reference = args[0]

    p = GitCommand(None,
                   ['rev-parse', reference],
                   capture_stdout = True,
                   capture_stderr = True)
    if p.Wait() != 0:
      print >>sys.stdout, p.stdout
      print >>sys.stderr, p.stderr
      sys.exit(1)
    sha1 = p.stdout.strip()

    p = GitCommand(None, ['cat-file', 'commit', sha1], capture_stdout=True)
    if p.Wait() != 0:
      print >>sys.stderr, "error: Failed to retrieve old commit message"
      sys.exit(1)
    old_msg = self._StripHeader(p.stdout)

    p = GitCommand(None,
                   ['cherry-pick', sha1],
                   capture_stdout = True,
                   capture_stderr = True)
    status = p.Wait()

    print >>sys.stdout, p.stdout
    print >>sys.stderr, p.stderr

    if status == 0:
      # The cherry-pick was applied correctly. We just need to edit the
      # commit message.
      new_msg = self._Reformat(old_msg, sha1)

      p = GitCommand(None, ['commit', '--amend', '-F', '-'],
                     provide_stdin = True,
                     capture_stdout = True,
                     capture_stderr = True)
      p.stdin.write(new_msg)
      if p.Wait() != 0:
        print >>sys.stderr, "error: Failed to update commit message"
        sys.exit(1)

    else:
      print >>sys.stderr, "NOTE: When committing and editing the commit " \
                        + "message, please remove the"
      print >>sys.stderr, "old Change-Id, and add:\n"
      print >>sys.stderr, self._GetChangeId(old_msg)
      print >>sys.stderr, self._GetReference(sha1)
      print >>sys.stderr

  def _GetChangeId(self, msg):
    # Can't use write-tree (which is used traditionally) if we have a dirty
    # index, which we will have if the cherry-pick fails.
    p = GitCommand(None, ['log', '-1', '--pretty=format:%T'],
                   capture_stdout = True)
    p.Wait()
    data = "tree: %s\n" % p.stdout.strip()
    p = GitCommand(None, ['rev-parse', 'HEAD^'], capture_stdout = True)
    if p.Wait() == 0:
      data += "parent: %s\n" % p.stdout.strip()
    p = GitCommand(None, ['var', 'GIT_AUTHOR_IDENT'], capture_stdout = True)
    p.Wait()
    data += "author: %s\n" % p.stdout.strip()
    p = GitCommand(None, ['var', 'GIT_COMMITTER_IDENT'],
                   capture_stdout = True)
    p.Wait()
    data += "committer: %s\n\n" % p.stdout.strip()
    data += msg
    p = GitCommand(None, ['hash-object', '-t', 'commit', '--stdin'],
                   provide_stdin = True, capture_stdout = True)
    p.stdin.write(data)
    p.Wait()
    return "Change-Id: I" + p.stdout.strip()

  def _IsChangeId(self, line):
    return CHANGE_ID_RE.match(line)

  def _GetReference(self, sha1):
    return "(cherry picked from commit %s)" % sha1

  def _StripHeader(self, commit_msg):
    lines = commit_msg.splitlines()
    return "\n".join(lines[lines.index("")+1:])

  def _Reformat(self, old_msg, sha1):
    new_msg = []

    for line in old_msg.splitlines():
      if self._IsChangeId(line):
        line = self._GetChangeId(old_msg)
        has_added_change_id = True
      new_msg.append(line)

    # Add a blank line between the message and the change id/reference
    try:
      if new_msg[-1].strip() != "":
        new_msg.append("")
    except IndexError:
      pass

    if not has_added_change_id:
      new_msg.append(self._GetChangeId(old_msg))

    new_msg.append(self._GetReference(sha1))
    return "\n".join(new_msg)
