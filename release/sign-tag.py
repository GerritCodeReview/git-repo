#!/usr/bin/env python3
# Copyright (C) 2020 The Android Open Source Project
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

"""Helper tool for signing repo release tags correctly.

This is intended to be run only by the official Repo release managers, but it
could be run by people maintaining their own fork of the project.

NB: Avoid new releases on off-hours.  If something goes wrong, staff/oncall need
to be active in order to respond quickly & effectively.  Recommend sticking to:
* Mon - Thu, 9:00 - 14:00 PT (i.e. MTV time)
* Avoid US holidays (and large international ones if possible)
* Follow the normal Google production freeze schedule
"""

import argparse
import os
import re
import subprocess
import sys

import util


# We currently sign with the old DSA key as it's been around the longest.
# We should transition to RSA by Jun 2020, and ECC by Jun 2021.
KEYID = util.KEYID_DSA

# Regular expression to validate tag names.
RE_VALID_TAG = r'^v([0-9]+[.])+[0-9]+$'


def sign(opts):
  """Tag the commit & sign it!"""
  # We use ! at the end of the key so that gpg uses this specific key.
  # Otherwise it uses the key as a lookup into the overall key and uses the
  # default signing key.  i.e. It will see that KEYID_RSA is a subkey of
  # another key, and use the primary key to sign instead of the subkey.
  cmd = ['git', 'tag', '-s', opts.tag, '-u', f'{opts.key}!',
         '-m', f'repo {opts.tag}', opts.commit]

  key = 'GNUPGHOME'
  print('+', f'export {key}="{opts.gpgdir}"')
  oldvalue = os.getenv(key)
  os.putenv(key, opts.gpgdir)
  util.run(opts, cmd)
  if oldvalue is None:
    os.unsetenv(key)
  else:
    os.putenv(key, oldvalue)


def check(opts):
  """Check the signature."""
  util.run(opts, ['git', 'tag', '--verify', opts.tag])


def postmsg(opts):
  """Helpful info to show at the end for release manager."""
  cmd = ['git', 'rev-parse', 'remotes/origin/stable']
  ret = util.run(opts, cmd, encoding='utf-8', stdout=subprocess.PIPE)
  current_release = ret.stdout.strip()

  cmd = ['git', 'log', '--format=%h (%aN) %s', '--no-merges',
         f'remotes/origin/stable..{opts.tag}']
  ret = util.run(opts, cmd, encoding='utf-8', stdout=subprocess.PIPE)
  shortlog = ret.stdout.strip()

  print(f"""
Here's the short log since the last release.
{shortlog}

To push release to the public:
  git push origin {opts.commit}:stable {opts.tag} -n
NB: People will start upgrading to this version immediately.

To roll back a release:
  git push origin --force {current_release}:stable -n
""")


def get_parser():
  """Get a CLI parser."""
  parser = argparse.ArgumentParser(
      description=__doc__,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('-n', '--dry-run',
                      dest='dryrun', action='store_true',
                      help='show everything that would be done')
  parser.add_argument('--gpgdir',
                      default=os.path.join(util.HOMEDIR, '.gnupg', 'repo'),
                      help='path to dedicated gpg dir with release keys '
                           '(default: ~/.gnupg/repo/)')
  parser.add_argument('-f', '--force', action='store_true',
                      help='force signing of any tag')
  parser.add_argument('--keyid', dest='key',
                      help='alternative signing key to use')
  parser.add_argument('tag',
                      help='the tag to create (e.g. "v2.0")')
  parser.add_argument('commit', default='HEAD', nargs='?',
                      help='the commit to tag')
  return parser


def main(argv):
  """The main func!"""
  parser = get_parser()
  opts = parser.parse_args(argv)

  if not os.path.exists(opts.gpgdir):
    parser.error(f'--gpgdir does not exist: {opts.gpgdir}')

  if not opts.force and not re.match(RE_VALID_TAG, opts.tag):
    parser.error(f'tag "{opts.tag}" does not match regex "{RE_VALID_TAG}"; '
                 'use --force to sign anyways')

  if opts.key:
    print(f'Using custom key to sign: {opts.key}')
  else:
    print('Using official Repo release key to sign')
    opts.key = KEYID
    util.import_release_key(opts)

  sign(opts)
  check(opts)
  postmsg(opts)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
