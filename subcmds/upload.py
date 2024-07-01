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

import copy
import functools
import optparse
import re
import sys
from typing import List

from command import DEFAULT_LOCAL_JOBS
from command import InteractiveCommand
from editor import Editor
from error import GitError
from error import SilentRepoExitError
from error import UploadError
from git_command import GitCommand
from git_refs import R_HEADS
from hooks import RepoHook
from project import ReviewableBranch
from repo_logging import RepoLogger
from subcmds.sync import LocalSyncState


_DEFAULT_UNUSUAL_COMMIT_THRESHOLD = 5
logger = RepoLogger(__file__)


class UploadExitError(SilentRepoExitError):
    """Indicates that there is an upload command error requiring a sys exit."""


def _VerifyPendingCommits(branches: List[ReviewableBranch]) -> bool:
    """Perform basic safety checks on the given set of branches.

    Ensures that each branch does not have a "large" number of commits
    and, if so, prompts the user to confirm they want to proceed with
    the upload.

    Returns true if all branches pass the safety check or the user
    confirmed. Returns false if the upload should be aborted.
    """

    # Determine if any branch has a suspicious number of commits.
    many_commits = False
    for branch in branches:
        # Get the user's unusual threshold for the branch.
        #
        # Each branch may be configured to have a different threshold.
        remote = branch.project.GetBranch(branch.name).remote
        key = f"review.{remote.review}.uploadwarningthreshold"
        threshold = branch.project.config.GetInt(key)
        if threshold is None:
            threshold = _DEFAULT_UNUSUAL_COMMIT_THRESHOLD

        # If the branch has more commits than the threshold, show a warning.
        if len(branch.commits) > threshold:
            many_commits = True
            break

    # If any branch has many commits, prompt the user.
    if many_commits:
        if len(branches) > 1:
            logger.warning(
                "ATTENTION: One or more branches has an unusually high number "
                "of commits."
            )
        else:
            logger.warning(
                "ATTENTION: You are uploading an unusually high number of "
                "commits."
            )
        logger.warning(
            "YOU PROBABLY DO NOT MEAN TO DO THIS. (Did you rebase across "
            "branches?)"
        )
        answer = input(
            "If you are sure you intend to do this, type 'yes': "
        ).strip()
        return answer == "yes"

    return True


def _die(fmt, *args):
    msg = fmt % args
    logger.error("error: %s", msg)
    raise UploadExitError(msg)


def _SplitEmails(values):
    result = []
    for value in values:
        result.extend([s.strip() for s in value.split(",")])
    return result


class Upload(InteractiveCommand):
    COMMON = True
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

While most normal Gerrit options have dedicated command line options,
direct access to the Gerit options is available via --push-options.
This is useful when Gerrit has newer functionality that %prog doesn't
yet support, or doesn't have plans to support.  See the Push Options
documentation for more details:
https://gerrit-review.googlesource.com/Documentation/user-upload.html#push_options

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

review.URL.uploadwarningthreshold:

Repo will warn you if you are attempting to upload a large number
of commits in one or more branches. By default, the threshold
is five commits. This option allows you to override the warning
threshold to a different value.

# References

Gerrit Code Review:  https://www.gerritcodereview.com/

"""
    PARALLEL_JOBS = DEFAULT_LOCAL_JOBS

    def _Options(self, p):
        p.add_option(
            "-t",
            "--topic-branch",
            dest="auto_topic",
            action="store_true",
            help="set the topic to the local branch name",
        )
        p.add_option(
            "--topic",
            help="set topic for the change",
        )
        p.add_option(
            "--hashtag",
            "--ht",
            dest="hashtags",
            action="append",
            default=[],
            help="add hashtags (comma delimited) to the review",
        )
        p.add_option(
            "--hashtag-branch",
            "--htb",
            action="store_true",
            help="add local branch name as a hashtag",
        )
        p.add_option(
            "-l",
            "--label",
            dest="labels",
            action="append",
            default=[],
            help="add a label when uploading",
        )
        p.add_option(
            "--pd",
            "--patchset-description",
            dest="patchset_description",
            help="description for patchset",
        )
        p.add_option(
            "--re",
            "--reviewers",
            type="string",
            action="append",
            dest="reviewers",
            help="request reviews from these people",
        )
        p.add_option(
            "--cc",
            type="string",
            action="append",
            dest="cc",
            help="also send email to these email addresses",
        )
        p.add_option(
            "--br",
            "--branch",
            type="string",
            action="store",
            dest="branch",
            help="(local) branch to upload",
        )
        p.add_option(
            "-c",
            "--current-branch",
            dest="current_branch",
            action="store_true",
            help="upload current git branch",
        )
        p.add_option(
            "--no-current-branch",
            dest="current_branch",
            action="store_false",
            help="upload all git branches",
        )
        # Turn this into a warning & remove this someday.
        p.add_option(
            "--cbr",
            dest="current_branch",
            action="store_true",
            help=optparse.SUPPRESS_HELP,
        )
        p.add_option(
            "--ne",
            "--no-emails",
            action="store_false",
            dest="notify",
            default=True,
            help="do not send e-mails on upload",
        )
        p.add_option(
            "-p",
            "--private",
            action="store_true",
            dest="private",
            default=False,
            help="upload as a private change (deprecated; use --wip)",
        )
        p.add_option(
            "-w",
            "--wip",
            action="store_true",
            dest="wip",
            default=False,
            help="upload as a work-in-progress change",
        )
        p.add_option(
            "-r",
            "--ready",
            action="store_true",
            default=False,
            help="mark change as ready (clears work-in-progress setting)",
        )
        p.add_option(
            "-o",
            "--push-option",
            type="string",
            action="append",
            dest="push_options",
            default=[],
            help="additional push options to transmit",
        )
        p.add_option(
            "-D",
            "--destination",
            "--dest",
            type="string",
            action="store",
            dest="dest_branch",
            metavar="BRANCH",
            help="submit for review on this target branch",
        )
        p.add_option(
            "-n",
            "--dry-run",
            dest="dryrun",
            default=False,
            action="store_true",
            help="do everything except actually upload the CL",
        )
        p.add_option(
            "-y",
            "--yes",
            default=False,
            action="store_true",
            help="answer yes to all safe prompts",
        )
        p.add_option(
            "--ignore-untracked-files",
            action="store_true",
            default=False,
            help="ignore untracked files in the working copy",
        )
        p.add_option(
            "--no-ignore-untracked-files",
            dest="ignore_untracked_files",
            action="store_false",
            help="always ask about untracked files in the working copy",
        )
        p.add_option(
            "--no-cert-checks",
            dest="validate_certs",
            action="store_false",
            default=True,
            help="disable verifying ssl certs (unsafe)",
        )
        RepoHook.AddOptionGroup(p, "pre-upload")

    def _SingleBranch(self, opt, branch, people):
        project = branch.project
        name = branch.name
        remote = project.GetBranch(name).remote

        key = "review.%s.autoupload" % remote.review
        answer = project.config.GetBoolean(key)

        if answer is False:
            _die("upload blocked by %s = false" % key)

        if answer is None:
            date = branch.date
            commit_list = branch.commits

            destination = (
                opt.dest_branch or project.dest_branch or project.revisionExpr
            )
            print(
                "Upload project %s/ to remote branch %s%s:"
                % (
                    project.RelPath(local=opt.this_manifest_only),
                    destination,
                    " (private)" if opt.private else "",
                )
            )
            print(
                "  branch %s (%2d commit%s, %s):"
                % (
                    name,
                    len(commit_list),
                    len(commit_list) != 1 and "s" or "",
                    date,
                )
            )
            for commit in commit_list:
                print("         %s" % commit)

            print("to %s (y/N)? " % remote.review, end="", flush=True)
            if opt.yes:
                print("<--yes>")
                answer = True
            else:
                answer = sys.stdin.readline().strip().lower()
                answer = answer in ("y", "yes", "1", "true", "t")
            if not answer:
                _die("upload aborted by user")

        # Perform some basic safety checks prior to uploading.
        if not opt.yes and not _VerifyPendingCommits([branch]):
            _die("upload aborted by user")

        self._UploadAndReport(opt, [branch], people)

    def _MultipleBranches(self, opt, pending, people):
        projects = {}
        branches = {}

        script = []
        script.append("# Uncomment the branches to upload:")
        for project, avail in pending:
            project_path = project.RelPath(local=opt.this_manifest_only)
            script.append("#")
            script.append(f"# project {project_path}/:")

            b = {}
            for branch in avail:
                if branch is None:
                    continue
                name = branch.name
                date = branch.date
                commit_list = branch.commits

                if b:
                    script.append("#")
                destination = (
                    opt.dest_branch
                    or project.dest_branch
                    or project.revisionExpr
                )
                script.append(
                    "#  branch %s (%2d commit%s, %s) to remote branch %s:"
                    % (
                        name,
                        len(commit_list),
                        len(commit_list) != 1 and "s" or "",
                        date,
                        destination,
                    )
                )
                for commit in commit_list:
                    script.append("#         %s" % commit)
                b[name] = branch

            projects[project_path] = project
            branches[project_path] = b
        script.append("")

        script = Editor.EditString("\n".join(script)).split("\n")

        project_re = re.compile(r"^#?\s*project\s*([^\s]+)/:$")
        branch_re = re.compile(r"^\s*branch\s*([^\s(]+)\s*\(.*")

        project = None
        todo = []

        for line in script:
            m = project_re.match(line)
            if m:
                name = m.group(1)
                project = projects.get(name)
                if not project:
                    _die("project %s not available for upload", name)
                continue

            m = branch_re.match(line)
            if m:
                name = m.group(1)
                if not project:
                    _die("project for branch %s not in script", name)
                project_path = project.RelPath(local=opt.this_manifest_only)
                branch = branches[project_path].get(name)
                if not branch:
                    _die("branch %s not in %s", name, project_path)
                todo.append(branch)
        if not todo:
            _die("nothing uncommented for upload")

        # Perform some basic safety checks prior to uploading.
        if not opt.yes and not _VerifyPendingCommits(todo):
            _die("upload aborted by user")

        self._UploadAndReport(opt, todo, people)

    def _AppendAutoList(self, branch, people):
        """
        Appends the list of reviewers in the git project's config.
        Appends the list of users in the CC list in the git project's config if
        a non-empty reviewer list was found.
        """
        name = branch.name
        project = branch.project

        key = "review.%s.autoreviewer" % project.GetBranch(name).remote.review
        raw_list = project.config.GetString(key)
        if raw_list is not None:
            people[0].extend([entry.strip() for entry in raw_list.split(",")])

        key = "review.%s.autocopy" % project.GetBranch(name).remote.review
        raw_list = project.config.GetString(key)
        if raw_list is not None and len(people[0]) > 0:
            people[1].extend([entry.strip() for entry in raw_list.split(",")])

    def _FindGerritChange(self, branch):
        last_pub = branch.project.WasPublished(branch.name)
        if last_pub is None:
            return ""

        refs = branch.GetPublishedRefs()
        try:
            # refs/changes/XYZ/N --> XYZ
            return refs.get(last_pub).split("/")[-2]
        except (AttributeError, IndexError):
            return ""

    def _UploadBranch(self, opt, branch, original_people):
        """Upload Branch."""
        people = copy.deepcopy(original_people)
        self._AppendAutoList(branch, people)

        # Check if topic branches should be sent to the server during
        # upload.
        if opt.topic is None:
            if opt.auto_topic is not True:
                key = "review.%s.uploadtopic" % branch.project.remote.review
                opt.auto_topic = branch.project.config.GetBoolean(key)
            if opt.auto_topic:
                opt.topic = branch.name

        def _ExpandCommaList(value):
            """Split |value| up into comma delimited entries."""
            if not value:
                return
            for ret in value.split(","):
                ret = ret.strip()
                if ret:
                    yield ret

        # Check if hashtags should be included.
        key = "review.%s.uploadhashtags" % branch.project.remote.review
        hashtags = set(_ExpandCommaList(branch.project.config.GetString(key)))
        for tag in opt.hashtags:
            hashtags.update(_ExpandCommaList(tag))
        if opt.hashtag_branch:
            hashtags.add(branch.name)

        # Check if labels should be included.
        key = "review.%s.uploadlabels" % branch.project.remote.review
        labels = set(_ExpandCommaList(branch.project.config.GetString(key)))
        for label in opt.labels:
            labels.update(_ExpandCommaList(label))

        # Handle e-mail notifications.
        if opt.notify is False:
            notify = "NONE"
        else:
            key = "review.%s.uploadnotify" % branch.project.remote.review
            notify = branch.project.config.GetString(key)

        destination = opt.dest_branch or branch.project.dest_branch

        if branch.project.dest_branch and not opt.dest_branch:
            merge_branch = self._GetMergeBranch(
                branch.project, local_branch=branch.name
            )

            full_dest = destination
            if not full_dest.startswith(R_HEADS):
                full_dest = R_HEADS + full_dest

            # If the merge branch of the local branch is different from
            # the project's revision AND destination, this might not be
            # intentional.
            if (
                merge_branch
                and merge_branch != branch.project.revisionExpr
                and merge_branch != full_dest
            ):
                print(
                    f"For local branch {branch.name}: merge branch "
                    f"{merge_branch} does not match destination branch "
                    f"{destination}"
                )
                print("skipping upload.")
                print(
                    f"Please use `--destination {destination}` if this "
                    "is intentional"
                )
                branch.uploaded = False
                return

        branch.UploadForReview(
            people,
            dryrun=opt.dryrun,
            topic=opt.topic,
            hashtags=hashtags,
            labels=labels,
            private=opt.private,
            notify=notify,
            wip=opt.wip,
            ready=opt.ready,
            dest_branch=destination,
            validate_certs=opt.validate_certs,
            push_options=opt.push_options,
            patchset_description=opt.patchset_description,
        )

        branch.uploaded = True

    def _UploadAndReport(self, opt, todo, people):
        have_errors = False
        aggregate_errors = []
        for branch in todo:
            try:
                self._UploadBranch(opt, branch, people)
            except (UploadError, GitError) as e:
                self.git_event_log.ErrorEvent(f"upload error: {e}")
                branch.error = e
                aggregate_errors.append(e)
                branch.uploaded = False
                have_errors = True

        print(file=sys.stderr)
        print("-" * 70, file=sys.stderr)

        if have_errors:
            for branch in todo:
                if not branch.uploaded:
                    if len(str(branch.error)) <= 30:
                        fmt = " (%s)"
                    else:
                        fmt = "\n       (%s)"
                    print(
                        ("[FAILED] %-15s %-15s" + fmt)
                        % (
                            branch.project.RelPath(local=opt.this_manifest_only)
                            + "/",
                            branch.name,
                            str(branch.error),
                        ),
                        file=sys.stderr,
                    )
            print()

        for branch in todo:
            if branch.uploaded:
                print(
                    "[OK    ] %-15s %s"
                    % (
                        branch.project.RelPath(local=opt.this_manifest_only)
                        + "/",
                        branch.name,
                    ),
                    file=sys.stderr,
                )

        if have_errors:
            raise UploadExitError(aggregate_errors=aggregate_errors)

    def _GetMergeBranch(self, project, local_branch=None):
        if local_branch is None:
            p = GitCommand(
                project,
                ["rev-parse", "--abbrev-ref", "HEAD"],
                capture_stdout=True,
                capture_stderr=True,
            )
            p.Wait()
            local_branch = p.stdout.strip()
        p = GitCommand(
            project,
            ["config", "--get", "branch.%s.merge" % local_branch],
            capture_stdout=True,
            capture_stderr=True,
        )
        p.Wait()
        merge_branch = p.stdout.strip()
        return merge_branch

    @staticmethod
    def _GatherOne(opt, project):
        """Figure out the upload status for |project|."""
        if opt.current_branch:
            cbr = project.CurrentBranch
            up_branch = project.GetUploadableBranch(cbr)
            avail = [up_branch] if up_branch else None
        else:
            avail = project.GetUploadableBranches(opt.branch)
        return (project, avail)

    def Execute(self, opt, args):
        projects = self.GetProjects(
            args, all_manifests=not opt.this_manifest_only
        )

        def _ProcessResults(_pool, _out, results):
            pending = []
            for result in results:
                project, avail = result
                if avail is None:
                    logger.error(
                        'repo: error: %s: Unable to upload branch "%s". '
                        "You might be able to fix the branch by running:\n"
                        "  git branch --set-upstream-to m/%s",
                        project.RelPath(local=opt.this_manifest_only),
                        project.CurrentBranch,
                        project.manifest.branch,
                    )
                elif avail:
                    pending.append(result)
            return pending

        pending = self.ExecuteInParallel(
            opt.jobs,
            functools.partial(self._GatherOne, opt),
            projects,
            callback=_ProcessResults,
        )

        if not pending:
            if opt.branch is None:
                logger.error("repo: error: no branches ready for upload")
            else:
                logger.error(
                    'repo: error: no branches named "%s" ready for upload',
                    opt.branch,
                )
            return 1

        manifests = {
            project.manifest.topdir: project.manifest
            for (project, available) in pending
        }
        ret = 0
        for manifest in manifests.values():
            pending_proj_names = [
                project.name
                for (project, available) in pending
                if project.manifest.topdir == manifest.topdir
            ]
            pending_worktrees = [
                project.worktree
                for (project, available) in pending
                if project.manifest.topdir == manifest.topdir
            ]
            hook = RepoHook.FromSubcmd(
                hook_type="pre-upload",
                manifest=manifest,
                opt=opt,
                abort_if_user_denies=True,
            )
            if not hook.Run(
                project_list=pending_proj_names, worktree_list=pending_worktrees
            ):
                if LocalSyncState(manifest).IsPartiallySynced():
                    logger.error(
                        "Partially synced tree detected. Syncing all projects "
                        "may resolve issues you're seeing."
                    )
                ret = 1
        if ret:
            return ret

        reviewers = _SplitEmails(opt.reviewers) if opt.reviewers else []
        cc = _SplitEmails(opt.cc) if opt.cc else []
        people = (reviewers, cc)

        if len(pending) == 1 and len(pending[0][1]) == 1:
            self._SingleBranch(opt, pending[0][1][0], people)
        else:
            self._MultipleBranches(opt, pending, people)
