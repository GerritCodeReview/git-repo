#
# Copyright (C) 2011 The Android Open Source Project
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

import sys
import os

from command import Command
from git_command import git
from project import HEAD

class Channel(Command):
  common = False
  helpSummary = "Select which channel of repo to use."
  helpUsage = """
%prog
"""
  helpDescription = """
The '%prog' command handles which branch of repo that is going to be used.
This can either be set as argument to 'repo init' when creating a new
workspace, or using this command to set the default channel and to change
an existing workspace
  """

  def _Options(self, p):
    p.add_option('--set-default',
                dest='default_repo_branch', metavar='DEFAULT_CHANNEL',
                help='Sets the default repo channel')
    p.add_option('--set',
                dest='repo_branch', metavar='WORKSPACE_CHANNEL',
                help='Sets the repo channel for the current workspace')
    p.add_option('-l', '--list',
                dest='list_channels', action='store_true',
                help='Lists the available channels')
    p.add_option('-s', '--status',
                dest='show_status', action='store_true',
                help='Shows which channel that is currently used')

  def GetChannelList(self, rp):
    channel_str = rp.work_git.for_each_ref('--format="%(refname)"')
    line = channel_str.replace('\"','')
    channels = line.split()
    return channels

  def ChannelExists(self, rp, channel_name):
    channel_list = self.GetChannelList(rp)
    for channel in channel_list:
      if channel.endswith(channel_name):
          return channel
    return None

  def DisplayChannels(self, rp):
    channelList = self.GetChannelList(rp)
    channelList.remove('refs/remotes/origin/HEAD')
    channelList.remove('refs/heads/default')

    for channel in channelList:
      if channel.find('/tags/') == -1:
        channelParts = channel.split('/')
        print channelParts[-1]

  def DisplayStatus(self, rp):
    rem = rp.GetRemote(rp.remote.name)
    default_branch_file = os.path.expanduser('~/.repoconfig/default_channel')
    if not os.path.exists(default_branch_file):
      branch = 'stable'
    else:
      fh = open(default_branch_file,'r')
      branch = fh.readline()
      fh.close()

    print 'Current setup'
    print 'repo channel in current workspace: %s' % rp.work_git.symbolic_ref(HEAD)
    print '       (from %s)' % rem.url
    print 'repo global default channel %s\n' % branch

  def Execute(self, opt, args):
    mn = self.manifest
    default_branch_file = os.path.expanduser('~/.repoconfig/default_channel')
    rp = mn.repoProject

    if opt.show_status:
      self.DisplayStatus(rp)

    if opt.list_channels:
      print 'Available channels:'
      self.DisplayChannels(rp)

    if opt.default_repo_branch:
      ref_name = self.ChannelExists(rp, opt.default_repo_branch)
      if ref_name:
        print 'Switching repo default channel to: %s' % opt.default_repo_branch
        fh = open(default_branch_file,'w')
        fh.write(opt.default_repo_branch)
        fh.close()
      else:
        print 'Channel name: %s does not exist' % opt.default_repo_branch
        sys.exit(28)
      print '\n'

    if opt.repo_branch:
      ref_name = self.ChannelExists(rp, opt.repo_branch)
      if ref_name:
        print 'Switching repo in current workspace to channel: %s' % opt.repo_branch
        rp.work_git.checkout(ref_name)
        sys.exit()
      else:
        print 'Channel name: %s does not exist' % opt.repo_branch
        sys.exit(28)
      print '\n'
