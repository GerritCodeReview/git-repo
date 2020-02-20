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

"""Random utility code for release tools."""

import os
import re
import subprocess
import sys


assert sys.version_info >= (3, 6), 'This module requires Python 3.6+'


TOPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def run(opts, cmd, check=True, **kwargs):
  """Helper around subprocess.run to include logging."""
  print('+', cmdstr(cmd))
  if opts.dryrun:
    cmd = ['true', '--'] + cmd
  try:
    return subprocess.run(cmd, check=check, **kwargs)
  except subprocess.CalledProcessError as e:
    print(f'aborting: {e}', file=sys.stderr)
    sys.exit(1)


def import_release_key(opts):
  """Import the public key of the official release repo signing key."""
  # Extract the key from our repo launcher.
  launcher = getattr(opts, 'launcher', os.path.join(TOPDIR, 'repo'))
  print(f'Importing keys from "{launcher}" launcher script')
  with open(launcher, encoding='utf-8') as fp:
    data = fp.read()

  keys = re.findall(
      r'\n-----BEGIN PGP PUBLIC KEY BLOCK-----\n[^-]*'
      r'\n-----END PGP PUBLIC KEY BLOCK-----\n', data, flags=re.M)
  run(opts, ['gpg', '--import'], input='\n'.join(keys).encode('utf-8'))

  print('Marking keys as fully trusted')
  run(opts, ['gpg', '--import-ownertrust'],
      input=f'{KEYID_DSA}:6:\n'.encode('utf-8'))
