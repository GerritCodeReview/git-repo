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

"""Helper tool for signing repo launcher scripts correctly.

This is intended to be run only by the official Repo release managers.
"""

import argparse
import os
import subprocess
import sys

import util


def sign(opts):
  """Sign the launcher!"""
  output = ''
  for key in opts.keys:
    # We use ! at the end of the key so that gpg uses this specific key.
    # Otherwise it uses the key as a lookup into the overall key and uses the
    # default signing key.  i.e. It will see that KEYID_RSA is a subkey of
    # another key, and use the primary key to sign instead of the subkey.
    cmd = ['gpg', '--homedir', opts.gpgdir, '-u', f'{key}!', '--batch', '--yes',
           '--armor', '--detach-sign', '--output', '-', opts.launcher]
    ret = util.run(opts, cmd, encoding='utf-8', stdout=subprocess.PIPE)
    output += ret.stdout

  # Save the combined signatures into one file.
  with open(f'{opts.launcher}.asc', 'w', encoding='utf-8') as fp:
    fp.write(output)


def check(opts):
  """Check the signature."""
  util.run(opts, ['gpg', '--verify', f'{opts.launcher}.asc'])


def postmsg(opts):
  """Helpful info to show at the end for release manager."""
  print(f"""
Repo launcher bucket:
  gs://git-repo-downloads/

To upload this launcher directly:
  gsutil cp -a public-read {opts.launcher} {opts.launcher}.asc gs://git-repo-downloads/

NB: You probably want to upload it with a specific version first, e.g.:
  gsutil cp -a public-read {opts.launcher} gs://git-repo-downloads/repo-3.0
  gsutil cp -a public-read {opts.launcher}.asc gs://git-repo-downloads/repo-3.0.asc
""")


def get_parser():
  """Get a CLI parser."""
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('-n', '--dry-run',
                      dest='dryrun', action='store_true',
                      help='show everything that would be done')
  parser.add_argument('--gpgdir',
                      default=os.path.join(util.HOMEDIR, '.gnupg', 'repo'),
                      help='path to dedicated gpg dir with release keys '
                           '(default: ~/.gnupg/repo/)')
  parser.add_argument('--keyid', dest='keys', default=[], action='append',
                      help='alternative signing keys to use')
  parser.add_argument('launcher',
                      default=os.path.join(util.TOPDIR, 'repo'), nargs='?',
                      help='the launcher script to sign')
  return parser


def main(argv):
  """The main func!"""
  parser = get_parser()
  opts = parser.parse_args(argv)

  if not os.path.exists(opts.gpgdir):
    parser.error(f'--gpgdir does not exist: {opts.gpgdir}')
  if not os.path.exists(opts.launcher):
    parser.error(f'launcher does not exist: {opts.launcher}')

  opts.launcher = os.path.relpath(opts.launcher)
  print(f'Signing "{opts.launcher}" launcher script and saving to '
        f'"{opts.launcher}.asc"')

  if opts.keys:
    print(f'Using custom keys to sign: {" ".join(opts.keys)}')
  else:
    print('Using official Repo release keys to sign')
    opts.keys = [util.KEYID_DSA, util.KEYID_RSA, util.KEYID_ECC]
    util.import_release_key(opts)

  sign(opts)
  check(opts)
  postmsg(opts)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
