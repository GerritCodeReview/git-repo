#!/usr/bin/env python3
# Copyright (C) 2020 Google Inc.
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
import re
import subprocess
import sys


assert sys.version_info >= (3, 6), 'This module requires Python 3.6+'


TOPDIR = os.path.dirname(os.path.abspath(__file__))
HOMEDIR = os.path.expanduser('~')


# These are the release keys we sign with.
KEYID_DSA = '8BB9AD793E8E6153AF0F9A4416530D5E920F5C65'
KEYID_RSA = 'A34A13BE8E76BFF46A0C022DA2E75A824AAB9624'
KEYID_ECC = 'E1F9040D7A3F6DAFAC897CD3D3B95DA243E48A39'


def cmdstr(cmd):
  """Get a nicely quoted shell command."""
  ret = []
  for arg in cmd:
    if not re.match(r'^[a-zA-Z0-9/_.=-]+$', arg):
      arg = f'"{arg}"'
    ret.append(arg)
  return ' '.join(ret)


def run(opts, cmd, **kwargs):
  """Helper around subprocess.run to include logging."""
  print('+', cmdstr(cmd))
  if opts.dryrun:
    cmd = ['true', '--'] + cmd
  return subprocess.run(cmd, **kwargs)


def sign(opts):
  """Sign the launcher!"""
  output = ''
  for key in (KEYID_DSA, KEYID_RSA, KEYID_ECC):
    # We use ! at the end of the key so that gpg uses this specific key.
    # Otherwise it uses the key as a lookup into the overall key and uses the
    # default signing key.  i.e. It will see that KEYID_RSA is a subkey of
    # another key, and use the primary key to sign instead of the subkey.
    cmd = ['gpg', '--homedir', opts.gpgdir, '-u', f'{key}!', '--batch', '--yes',
           '--armor', '--detach-sign', '--output', '-', opts.launcher]
    output += run(opts, cmd, encoding='utf-8', stdout=subprocess.PIPE).stdout

  # Save the combined signatures into one file.
  with open(f'{opts.launcher}.asc', 'w', encoding='utf-8') as fp:
    fp.write(output)


def check(opts):
  """Check the signature."""
  run(opts, ['gpg', '--verify', f'{opts.launcher}.asc'])


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
                      default=os.path.join(HOMEDIR, '.gnupg', 'repo'),
                      help='path to dedicated gpg dir with release keys '
                           '(default: ~/.gnupg/repo/)')
  parser.add_argument('launcher',
                      default=os.path.join(TOPDIR, 'repo'), nargs='?',
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

  sign(opts)
  check(opts)
  postmsg(opts)

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
