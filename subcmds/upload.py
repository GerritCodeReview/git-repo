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
import copy
import re
import sys

from command import InteractiveCommand
from editor import Editor
from error import HookError, UploadError
from git_command import GitCommand
from project import RepoHook

from pyversion import is_python3
if not is_python3():
  input = raw_input  # noqa: F821
else:
  unicode = str

UNUSUAL_COMMIT_THRESHOLD = 5


def _ConfirmManyUploads(multiple_branches=False):
  if multiple_branches:
    print('ATTENTION: One or more branches has an unusually high number '
          'of commits.')
  else:
    print('ATTENTION: You are uploading an unusually high number of commits.')
  print('YOU PROBABLY DO NOT MEAN TO DO THIS. (Did you rebase across '
        'branches?)')
  answer = input("If you are sure you intend to do this, type 'yes': ").strip()
  return answer == "yes"


def _die(fmt, *args):
  msg = fmt % args
  print('error: %s' % msg, file=sys.stderr)
  sys.exit(1)


def _SplitEmails(values):
  result = []
  for value in values:
    result.extend([s.strip() for s in value.split(',')])
  return result


class Upload(InteractiveCommand):
  common = True
  helpSummary = "Upload changes for code review"
  helpUsage = """
%prog [--re --cc] [<project>]...
"""
  helpDescription = """
The '%prog' command is used to send changes to the Gerrit Code
Review system.  It searches for topic branches in local projects
that have not yet been published for review.  If multiple topic
branches are found, '%prog' opens an editor to allow the user to
select which branches to upload.

'%prog' searches for uploadable changes in all projects listed at
the command line.  Projects can be specified either by name, or by
a relative or absolute path to the project's local directory. If no
projects are specified, '%prog' will search for uploadable changes
in all projects listed in the manifest.

If the --reviewers or --cc options are passed, those emails are
added to the respective list of users, and emails are sent to any
new users.  Users passed as --reviewers must already be registered
with the code review system, or the upload will fail.

# Configuration

review.URL.autoupload:

To disable the "Upload ... (y/N)?" prompt, you can set a per-project
or global Git configuration option.  If review.URL.autoupload is set
to "true" then repo will assume you always answer "y" at the prompt,
and will not prompt you further.  If it is set to "false" then repo
will assume you always answer "n", and will abort.

review.URL.autoreviewer:

To automatically append a user or mailing list to reviews, you can set
a per-project or global Git option to do so.

review.URL.autocopy:

To automatically copy a user or mailing list to all uploaded reviews,
you can set a per-project or global Git option to do so. Specifically,
review.URL.autocopy can be set to a comma separated list of reviewers
who you always want copied on all uploads with a non-empty --re
argument.

review.URL.username:

Override the username used to connect to Gerrit Code Review.
By default the local part of the email address is used.

The URL must match the review URL listed in the manifest XML file,
or in the .git/config within the project.  For example:

  [remote "origin"]
    url = git://git.example.com/project.git
    review = http://review.example.com/

  [review "http://review.example.com/"]
    autoupload = true
    autocopy = johndoe@company.com,my-team-alias@company.com

review.URL.uploadtopic:

To add a topic branch whenever uploading a commit, you can set a
per-project or global Git option to do so. If review.URL.uploadtopic
is set to "true" then repo will assume you always want the equivalent
of the -t option to the repo command. If unset or set to "false" then
repo will make use of only the command line option.

review.URL.uploadhashtags:

To add hashtags whenever uploading a commit, you can set a per-project
or global Git option to do so. The value of review.URL.uploadhashtags
will be used as comma delimited hashtags like the --hashtag option.

review.URL.uploadlabels:

To add labels whenever uploading a commit, you can set a per-project
or global Git option to do so. The value of review.URL.uploadlabels
will be used as comma delimited labels like the --label option.

review.URL.uploadnotify:

Control e-mail notifications when uploading.
https://gerrit-review.googlesource.com/Documentation/user-upload.html#notify

# References

Gerrit Code Review:  https://www.gerritcodereview.com/

"""

  def _Options(self, p):
    p.add_option('-t',
                 dest='auto_topic', action='store_true',
                 help='Send local branch name to Gerrit Code Review')
    p.add_option('--hashtag', '--ht',
                 dest='hashtags', action='append', default=[],
                 help='Add hashtags (comma delimited) to the review.')
    p.add_option('--hashtag-branch', '--htb',
                 action='store_true',
                 help='Add local branch name as a hashtag.')
    p.add_option('-l', '--label',
                 dest='labels', action='append', default=[],
                 help='Add a label when uploading.')
    p.add_option('--re', '--reviewers',
                 type='string', action='append', dest='reviewers',
                 help='Request reviews from these people.')
    p.add_option('--cc',
                 type='string', action='append', dest='cc',
                 help='Also send email to these email addresses.')
    p.add_option('--br',
                 type='string', action='store', dest='branch',
                 help='Branch to upload.')
    p.add_option('--cbr', '--current-branch',
                 dest='current_branch', action='store_true',
                 help='Upload current git branch.')
    p.add_option('--ne', '--no-emails',
                 action='store_false', dest='notify', default=True,
                 help='If specified, do not send emails on upload.')
    p.add_option('-p', '--private',
                 action='store_true', dest='private', default=False,
                 help='If specified, upload as a private change.')
    p.add_option('-w', '--wip',
                 action='store_true', dest='wip', default=False,
                 help='If specified, upload as a work-in-progress change.')
    p.add_option('-o', '--push-option',
                 type='string', action='append', dest='push_options',
                 default=[],
                 help='Additional push options to transmit')
    p.add_option('-D', '--destination', '--dest',
                 type='string', action='store', dest='dest_branch',
                 metavar='BRANCH',
                 help='Submit for review on this target branch.')
    p.add_option('-n', '--dry-run',
                 dest='dryrun', default=False, action='store_true',
                 help='Do everything except actually upload the CL.')
    p.add_option('-y', '--yes',
                 default=False, action='store_true',
                 help='Answer yes to all safe prompts.')
    p.add_option('--no-cert-checks',
                 dest='validate_certs', action='store_false', default=True,
                 help='Disable verifying ssl certs (unsafe).')

    # Options relating to upload hook.  Note that verify and no-verify are NOT
    # opposites of each other, which is why they store to different locations.
    # We are using them to match 'git commit' syntax.
    #
    # Combinations:
    # - no-verify=False, verify=False (DEFAULT):
    #   If stdout is a tty, can prompt about running upload hooks if needed.
    #   If user denies running hooks, the upload is cancelled.  If stdout is
    #   not a tty and we would need to prompt about upload hooks, upload is
    #   cancelled.
    # - no-verify=False, verify=True:
    #   Always run upload hooks with no prompt.
    # - no-verify=True, verify=False:
    #   Never run upload hooks, but upload anyway (AKA bypass hooks).
    # - no-verify=True, verify=True:
    #   Invalid
    g = p.add_option_group('Upload hooks')
    g.add_option('--no-verify',
                 dest='bypass_hooks', action='store_true',
                 help='Do not run the upload hook.')
    g.add_option('--verify',
                 dest='allow_all_hooks', action='store_true',
                 help='Run the upload hook without prompting.')
    g.add_option('--ignore-hooks',
                 dest='ignore_hooks', action='store_true',
                 help='Do not abort uploading if upload hooks fail.')

  def _SingleBranch(self, opt, branch, people):
    project = branch.project
    name = branch.name
    remote = project.GetBranch(name).remote

    key = 'review.%s.autoupload' % remote.review
    answer = project.config.GetBoolean(key)

    if answer is False:
      _die("upload blocked by %s = false" % key)

    if answer is None:
      date = branch.date
      commit_list = branch.commits

      destination = opt.dest_branch or project.dest_branch or project.revisionExpr
      print('Upload project %s/ to remote branch %s%s:' %
            (project.relpath, destination, ' (private)' if opt.private else ''))
      print('  branch %s (%2d commit%s, %s):' % (
          name,
          len(commit_list),
          len(commit_list) != 1 and 's' or '',
          date))
      for commit in commit_list:
        print('         %s' % commit)

      print('to %s (y/N)? ' % remote.review, end='')
      # TODO: When we require Python 3, use flush=True w/print above.
      sys.stdout.flush()
      if opt.yes:
        print('<--yes>')
        answer = True
      else:
        answer = sys.stdin.readline().strip().lower()
        answer = answer in ('y', 'yes', '1', 'true', 't')

    if answer:
      if len(branch.commits) > UNUSUAL_COMMIT_THRESHOLD:
        answer = _ConfirmManyUploads()

    if answer:
      self._UploadAndReport(opt, [branch], people)
    else:
      _die("upload aborted by user")

  def _MultipleBranches(self, opt, pending, people):
    projects = {}
    branches = {}

    script = []
    script.append('# Uncomment the branches to upload:')
    for project, avail in pending:
      script.append('#')
      script.append('# project %s/:' % project.relpath)

      b = {}
      for branch in avail:
        if branch is None:
          continue
        name = branch.name
        date = branch.date
        commit_list = branch.commits

        if b:
          script.append('#')
        destination = opt.dest_branch or project.dest_branch or project.revisionExpr
        script.append('#  branch %s (%2d commit%s, %s) to remote branch %s:' % (
                      name,
                      len(commit_list),
                      len(commit_list) != 1 and 's' or '',
                      date,
                      destination))
        for commit in commit_list:
          script.append('#         %s' % commit)
        b[name] = branch

      projects[project.relpath] = project
      branches[project.name] = b
    script.append('')

    script = Editor.EditString("\n".join(script)).split("\n")

    project_re = re.compile(r'^#?\s*project\s*([^\s]+)/:$')
    branch_re = re.compile(r'^\s*branch\s*([^\s(]+)\s*\(.*')

    project = None
    todo = []

    for line in script:
      m = project_re.match(line)
      if m:
        name = m.group(1)
        project = projects.get(name)
        if not project:
          _die('project %s not available for upload', name)
        continue

      m = branch_re.match(line)
      if m:
        name = m.group(1)
        if not project:
          _die('project for branch %s not in script', name)
        branch = branches[project.name].get(name)
        if not branch:
          _die('branch %s not in %s', name, project.relpath)
        todo.append(branch)
    if not todo:
      _die("nothing uncommented for upload")

    many_commits = False
    for branch in todo:
      if len(branch.commits) > UNUSUAL_COMMIT_THRESHOLD:
        many_commits = True
        break
    if many_commits:
      if not _ConfirmManyUploads(multiple_branches=True):
        _die("upload aborted by user")

    self._UploadAndReport(opt, todo, people)

  def _AppendAutoList(self, branch, people):
    """
    Appends the list of reviewers in the git project's config.
    Appends the list of users in the CC list in the git project's config if a
    non-empty reviewer list was found.
    """
    name = branch.name
    project = branch.project

    key = 'review.%s.autoreviewer' % project.GetBranch(name).remote.review
    raw_list = project.config.GetString(key)
    if raw_list is not None:
      people[0].extend([entry.strip() for entry in raw_list.split(',')])

    key = 'review.%s.autocopy' % project.GetBranch(name).remote.review
    raw_list = project.config.GetString(key)
    if raw_list is not None and len(people[0]) > 0:
      people[1].extend([entry.strip() for entry in raw_list.split(',')])

  def _FindGerritChange(self, branch):
    last_pub = branch.project.WasPublished(branch.name)
    if last_pub is None:
      return ""

    refs = branch.GetPublishedRefs()
    try:
      # refs/changes/XYZ/N --> XYZ
      return refs.get(last_pub).split('/')[-2]
    except (AttributeError, IndexError):
      return ""

  def _UploadAndReport(self, opt, todo, original_people):
    have_errors = False
    for branch in todo:
      try:
        people = copy.deepcopy(original_people)
        self._AppendAutoList(branch, people)

        # Check if there are local changes that may have been forgotten
        changes = branch.project.UncommitedFiles()
        if changes:
          key = 'review.%s.autoupload' % branch.project.remote.review
          answer = branch.project.config.GetBoolean(key)

          # if they want to auto upload, let's not ask because it could be automated
          if answer is None:
            print()
            print('Uncommitted changes in %s (did you forget to amend?):'
                  % branch.project.name)
            print('\n'.join(changes))
            print('Continue uploading? (y/N) ', end='')
            # TODO: When we require Python 3, use flush=True w/print above.
            sys.stdout.flush()
            if opt.yes:
              print('<--yes>')
              a = 'yes'
            else:
              a = sys.stdin.readline().strip().lower()
            if a not in ('y', 'yes', 't', 'true', 'on'):
              print("skipping upload", file=sys.stderr)
              branch.uploaded = False
              branch.error = 'User aborted'
              continue

        # Check if topic branches should be sent to the server during upload
        if opt.auto_topic is not True:
          key = 'review.%s.uploadtopic' % branch.project.remote.review
          opt.auto_topic = branch.project.config.GetBoolean(key)

        def _ExpandCommaList(value):
          """Split |value| up into comma delimited entries."""
          if not value:
            return
          for ret in value.split(','):
            ret = ret.strip()
            if ret:
              yield ret

        # Check if hashtags should be included.
        key = 'review.%s.uploadhashtags' % branch.project.remote.review
        hashtags = set(_ExpandCommaList(branch.project.config.GetString(key)))
        for tag in opt.hashtags:
          hashtags.update(_ExpandCommaList(tag))
        if opt.hashtag_branch:
          hashtags.add(branch.name)

        # Check if labels should be included.
        key = 'review.%s.uploadlabels' % branch.project.remote.review
        labels = set(_ExpandCommaList(branch.project.config.GetString(key)))
        for label in opt.labels:
          labels.update(_ExpandCommaList(label))
        # Basic sanity check on label syntax.
        for label in labels:
          if not re.match(r'^.+[+-][0-9]+$', label):
            print('repo: error: invalid label syntax "%s": labels use forms '
                  'like CodeReview+1 or Verified-1' % (label,), file=sys.stderr)
            sys.exit(1)

        # Handle e-mail notifications.
        if opt.notify is False:
          notify = 'NONE'
        else:
          key = 'review.%s.uploadnotify' % branch.project.remote.review
          notify = branch.project.config.GetString(key)

        destination = opt.dest_branch or branch.project.dest_branch

        # Make sure our local branch is not setup to track a different remote branch
        merge_branch = self._GetMergeBranch(branch.project)
        if destination:
          full_dest = 'refs/heads/%s' % destination
          if not opt.dest_branch and merge_branch and merge_branch != full_dest:
            print('merge branch %s does not match destination branch %s'
                  % (merge_branch, full_dest))
            print('skipping upload.')
            print('Please use `--destination %s` if this is intentional'
                  % destination)
            branch.uploaded = False
            continue

        branch.UploadForReview(people,
                               dryrun=opt.dryrun,
                               auto_topic=opt.auto_topic,
                               hashtags=hashtags,
                               labels=labels,
                               private=opt.private,
                               notify=notify,
                               wip=opt.wip,
                               dest_branch=destination,
                               validate_certs=opt.validate_certs,
                               push_options=opt.push_options)

        branch.uploaded = True
      except UploadError as e:
        branch.error = e
        branch.uploaded = False
        have_errors = True

    print(file=sys.stderr)
    print('----------------------------------------------------------------------', file=sys.stderr)

    if have_errors:
      for branch in todo:
        if not branch.uploaded:
          if len(str(branch.error)) <= 30:
            fmt = ' (%s)'
          else:
            fmt = '\n       (%s)'
          print(('[FAILED] %-15s %-15s' + fmt) % (
              branch.project.relpath + '/',
              branch.name,
              str(branch.error)),
              file=sys.stderr)
      print()

    for branch in todo:
      if branch.uploaded:
        print('[OK    ] %-15s %s' % (
            branch.project.relpath + '/',
            branch.name),
            file=sys.stderr)

    if have_errors:
      sys.exit(1)

  def _GetMergeBranch(self, project):
    p = GitCommand(project,
                   ['rev-parse', '--abbrev-ref', 'HEAD'],
                   capture_stdout=True,
                   capture_stderr=True)
    p.Wait()
    local_branch = p.stdout.strip()
    p = GitCommand(project,
                   ['config', '--get', 'branch.%s.merge' % local_branch],
                   capture_stdout=True,
                   capture_stderr=True)
    p.Wait()
    merge_branch = p.stdout.strip()
    return merge_branch

  def Execute(self, opt, args):
    project_list = self.GetProjects(args)
    pending = []
    reviewers = []
    cc = []
    branch = None

    if opt.branch:
      branch = opt.branch

    for project in project_list:
      if opt.current_branch:
        cbr = project.CurrentBranch
        up_branch = project.GetUploadableBranch(cbr)
        if up_branch:
          avail = [up_branch]
        else:
          avail = None
          print('ERROR: Current branch (%s) not uploadable. '
                'You may be able to type '
                '"git branch --set-upstream-to m/master" to fix '
                'your branch.' % str(cbr),
                file=sys.stderr)
      else:
        avail = project.GetUploadableBranches(branch)
      if avail:
        pending.append((project, avail))

    if not pending:
      if branch is None:
        print('repo: error: no branches ready for upload', file=sys.stderr)
      else:
        print('repo: error: no branches named "%s" ready for upload' %
              (branch,), file=sys.stderr)
      return 1

    if not opt.bypass_hooks:
      hook = RepoHook('pre-upload', self.manifest.repo_hooks_project,
                      self.manifest.topdir,
                      self.manifest.manifestProject.GetRemote('origin').url,
                      abort_if_user_denies=True)
      pending_proj_names = [project.name for (project, available) in pending]
      pending_worktrees = [project.worktree for (project, available) in pending]
      passed = True
      try:
        hook.Run(opt.allow_all_hooks, project_list=pending_proj_names,
                 worktree_list=pending_worktrees)
      except SystemExit:
        passed = False
        if not opt.ignore_hooks:
          raise
      except HookError as e:
        passed = False
        print("ERROR: %s" % str(e), file=sys.stderr)

      if not passed:
        if opt.ignore_hooks:
          print('\nWARNING: pre-upload hooks failed, but uploading anyways.',
                file=sys.stderr)
        else:
          return

    if opt.reviewers:
      reviewers = _SplitEmails(opt.reviewers)
    if opt.cc:
      cc = _SplitEmails(opt.cc)
    people = (reviewers, cc)

    if len(pending) == 1 and len(pending[0][1]) == 1:
      self._SingleBranch(opt, pending[0][1][0], people)
    else:
      self._MultipleBranches(opt, pending, people)
