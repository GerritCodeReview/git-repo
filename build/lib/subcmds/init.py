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

import os
import sys

from color import Coloring
from command import InteractiveCommand
from command import MirrorSafeCommand
from error import RepoUnhandledExceptionError
from error import UpdateManifestError
from git_command import git_require
from repo_logging import RepoLogger
from wrapper import Wrapper
from wrapper import WrapperDir


logger = RepoLogger(__file__)

_REPO_ALLOW_SHALLOW = os.environ.get("REPO_ALLOW_SHALLOW")


class Init(InteractiveCommand, MirrorSafeCommand):
    COMMON = True
    MULTI_MANIFEST_SUPPORT = True
    helpSummary = "Initialize a repo client checkout in the current directory"
    helpUsage = """
%prog [options] [manifest url]
"""
    helpDescription = """
The '%prog' command is run once to install and initialize repo.
The latest repo source code and manifest collection is downloaded
from the server and is installed in the .repo/ directory in the
current working directory.

When creating a new checkout, the manifest URL is the only required setting.
It may be specified using the --manifest-url option, or as the first optional
argument.

The optional -b argument can be used to select the manifest branch
to checkout and use.  If no branch is specified, the remote's default
branch is used.  This is equivalent to using -b HEAD.

The optional --manifest-upstream-branch argument can be used when a commit is
provided to --manifest-branch (or -b), to specify the name of the git ref in
which the commit can be found.

The optional -m argument can be used to specify an alternate manifest
to be used. If no manifest is specified, the manifest default.xml
will be used.

If the --standalone-manifest argument is set, the manifest will be downloaded
directly from the specified --manifest-url as a static file (rather than
setting up a manifest git checkout). With --standalone-manifest, the manifest
will be fully static and will not be re-downloaded during subsesquent
`repo init` and `repo sync` calls.

The --reference option can be used to point to a directory that
has the content of a --mirror sync. This will make the working
directory use as much data as possible from the local reference
directory when fetching from the server. This will make the sync
go a lot faster by reducing data traffic on the network.

The --dissociate option can be used to borrow the objects from
the directory specified with the --reference option only to reduce
network transfer, and stop borrowing from them after a first clone
is made by making necessary local copies of borrowed objects.

The --no-clone-bundle option disables any attempt to use
$URL/clone.bundle to bootstrap a new Git repository from a
resumeable bundle file on a content delivery network. This
may be necessary if there are problems with the local Python
HTTP client or proxy configuration, but the Git binary works.

# Switching Manifest Branches

To switch to another manifest branch, `repo init -b otherbranch`
may be used in an existing client.  However, as this only updates the
manifest, a subsequent `repo sync` (or `repo sync -d`) is necessary
to update the working directory files.
"""

    def _CommonOptions(self, p):
        """Disable due to re-use of Wrapper()."""

    def _Options(self, p):
        Wrapper().InitParser(p)
        m = p.add_option_group("Multi-manifest")
        m.add_option(
            "--outer-manifest",
            action="store_true",
            default=True,
            help="operate starting at the outermost manifest",
        )
        m.add_option(
            "--no-outer-manifest",
            dest="outer_manifest",
            action="store_false",
            help="do not operate on outer manifests",
        )
        m.add_option(
            "--this-manifest-only",
            action="store_true",
            default=None,
            help="only operate on this (sub)manifest",
        )
        m.add_option(
            "--no-this-manifest-only",
            "--all-manifests",
            dest="this_manifest_only",
            action="store_false",
            help="operate on this manifest and its submanifests",
        )

    def _RegisteredEnvironmentOptions(self):
        return {
            "REPO_MANIFEST_URL": "manifest_url",
            "REPO_MIRROR_LOCATION": "reference",
        }

    def _SyncManifest(self, opt):
        """Call manifestProject.Sync with arguments from opt.

        Args:
            opt: options from optparse.
        """
        # Normally this value is set when instantiating the project, but the
        # manifest project is special and is created when instantiating the
        # manifest which happens before we parse options.
        self.manifest.manifestProject.clone_depth = opt.manifest_depth
        self.manifest.manifestProject.upstream = opt.manifest_upstream_branch
        clone_filter_for_depth = (
            "blob:none" if (_REPO_ALLOW_SHALLOW == "0") else None
        )
        if not self.manifest.manifestProject.Sync(
            manifest_url=opt.manifest_url,
            manifest_branch=opt.manifest_branch,
            standalone_manifest=opt.standalone_manifest,
            groups=opt.groups,
            platform=opt.platform,
            mirror=opt.mirror,
            dissociate=opt.dissociate,
            reference=opt.reference,
            worktree=opt.worktree,
            submodules=opt.submodules,
            archive=opt.archive,
            partial_clone=opt.partial_clone,
            clone_filter=opt.clone_filter,
            partial_clone_exclude=opt.partial_clone_exclude,
            clone_filter_for_depth=clone_filter_for_depth,
            clone_bundle=opt.clone_bundle,
            git_lfs=opt.git_lfs,
            use_superproject=opt.use_superproject,
            verbose=opt.verbose,
            current_branch_only=opt.current_branch_only,
            tags=opt.tags,
            depth=opt.depth,
            git_event_log=self.git_event_log,
            manifest_name=opt.manifest_name,
        ):
            manifest_name = opt.manifest_name
            raise UpdateManifestError(
                f"Unable to sync manifest {manifest_name}"
            )

    def _Prompt(self, prompt, value):
        print("%-10s [%s]: " % (prompt, value), end="", flush=True)
        a = sys.stdin.readline().strip()
        if a == "":
            return value
        return a

    def _ShouldConfigureUser(self, opt, existing_checkout):
        gc = self.client.globalConfig
        mp = self.manifest.manifestProject

        # If we don't have local settings, get from global.
        if not mp.config.Has("user.name") or not mp.config.Has("user.email"):
            if not gc.Has("user.name") or not gc.Has("user.email"):
                return True

            mp.config.SetString("user.name", gc.GetString("user.name"))
            mp.config.SetString("user.email", gc.GetString("user.email"))

        if not opt.quiet and not existing_checkout or opt.verbose:
            print()
            print(
                "Your identity is: %s <%s>"
                % (
                    mp.config.GetString("user.name"),
                    mp.config.GetString("user.email"),
                )
            )
            print(
                "If you want to change this, please re-run 'repo init' with "
                "--config-name"
            )
        return False

    def _ConfigureUser(self, opt):
        mp = self.manifest.manifestProject

        while True:
            if not opt.quiet:
                print()
            name = self._Prompt("Your Name", mp.UserName)
            email = self._Prompt("Your Email", mp.UserEmail)

            if not opt.quiet:
                print()
            print(f"Your identity is: {name} <{email}>")
            print("is this correct [y/N]? ", end="", flush=True)
            a = sys.stdin.readline().strip().lower()
            if a in ("yes", "y", "t", "true"):
                break

        if name != mp.UserName:
            mp.config.SetString("user.name", name)
        if email != mp.UserEmail:
            mp.config.SetString("user.email", email)

    def _HasColorSet(self, gc):
        for n in ["ui", "diff", "status"]:
            if gc.Has("color.%s" % n):
                return True
        return False

    def _ConfigureColor(self):
        gc = self.client.globalConfig
        if self._HasColorSet(gc):
            return

        class _Test(Coloring):
            def __init__(self):
                Coloring.__init__(self, gc, "test color display")
                self._on = True

        out = _Test()

        print()
        print("Testing colorized output (for 'repo diff', 'repo status'):")

        for c in ["black", "red", "green", "yellow", "blue", "magenta", "cyan"]:
            out.write(" ")
            out.printer(fg=c)(" %-6s ", c)
        out.write(" ")
        out.printer(fg="white", bg="black")(" %s " % "white")
        out.nl()

        for c in ["bold", "dim", "ul", "reverse"]:
            out.write(" ")
            out.printer(fg="black", attr=c)(" %-6s ", c)
        out.nl()

        print(
            "Enable color display in this user account (y/N)? ",
            end="",
            flush=True,
        )
        a = sys.stdin.readline().strip().lower()
        if a in ("y", "yes", "t", "true", "on"):
            gc.SetString("color.ui", "auto")

    def _DisplayResult(self):
        if self.manifest.IsMirror:
            init_type = "mirror "
        else:
            init_type = ""

        print()
        print(
            "repo %shas been initialized in %s"
            % (init_type, self.manifest.topdir)
        )

        current_dir = os.getcwd()
        if current_dir != self.manifest.topdir:
            print(
                "If this is not the directory in which you want to initialize "
                "repo, please run:"
            )
            print("   rm -r %s" % os.path.join(self.manifest.topdir, ".repo"))
            print("and try again.")

    def ValidateOptions(self, opt, args):
        if opt.reference:
            opt.reference = os.path.expanduser(opt.reference)

        # Check this here, else manifest will be tagged "not new" and init won't
        # be possible anymore without removing the .repo/manifests directory.
        if opt.mirror:
            if opt.archive:
                self.OptionParser.error(
                    "--mirror and --archive cannot be used " "together."
                )
            if opt.use_superproject is not None:
                self.OptionParser.error(
                    "--mirror and --use-superproject cannot be "
                    "used together."
                )
        if opt.archive and opt.use_superproject is not None:
            self.OptionParser.error(
                "--archive and --use-superproject cannot be used " "together."
            )

        if opt.standalone_manifest and (
            opt.manifest_branch or opt.manifest_name != "default.xml"
        ):
            self.OptionParser.error(
                "--manifest-branch and --manifest-name cannot"
                " be used with --standalone-manifest."
            )

        if opt.manifest_upstream_branch and opt.manifest_branch is None:
            self.OptionParser.error(
                "--manifest-upstream-branch cannot be used without "
                "--manifest-branch."
            )

        if args:
            if opt.manifest_url:
                self.OptionParser.error(
                    "--manifest-url option and URL argument both specified: "
                    "only use one to select the manifest URL."
                )

            opt.manifest_url = args.pop(0)

            if args:
                self.OptionParser.error("too many arguments to init")

    def Execute(self, opt, args):
        wrapper = Wrapper()

        reqs = wrapper.Requirements.from_dir(WrapperDir())
        git_require(reqs.get_hard_ver("git"), fail=True)
        min_git_version_soft = reqs.get_soft_ver("git")
        if not git_require(min_git_version_soft):
            logger.warning(
                "repo: warning: git-%s+ will soon be required; "
                "please upgrade your version of git to maintain "
                "support.",
                ".".join(str(x) for x in min_git_version_soft),
            )

        rp = self.manifest.repoProject

        # Handle new --repo-url requests.
        if opt.repo_url:
            remote = rp.GetRemote("origin")
            remote.url = opt.repo_url
            remote.Save()

        # Handle new --repo-rev requests.
        if opt.repo_rev:
            try:
                remote_ref, rev = wrapper.check_repo_rev(
                    rp.worktree,
                    opt.repo_rev,
                    repo_verify=opt.repo_verify,
                    quiet=opt.quiet,
                )
            except wrapper.CloneFailure as e:
                err_msg = "fatal: double check your --repo-rev setting."
                logger.error(err_msg)
                self.git_event_log.ErrorEvent(err_msg)
                raise RepoUnhandledExceptionError(e)

            branch = rp.GetBranch("default")
            branch.merge = remote_ref
            rp.work_git.reset("--hard", rev)
            branch.Save()

        if opt.worktree:
            # Older versions of git supported worktree, but had dangerous gc
            # bugs.
            git_require((2, 15, 0), fail=True, msg="git gc worktree corruption")

        # Provide a short notice that we're reinitializing an existing checkout.
        # Sometimes developers might not realize that they're in one, or that
        # repo doesn't do nested checkouts.
        existing_checkout = self.manifest.manifestProject.Exists
        if not opt.quiet and existing_checkout:
            print(
                "repo: reusing existing repo client checkout in",
                self.manifest.topdir,
            )

        self._SyncManifest(opt)

        if os.isatty(0) and os.isatty(1) and not self.manifest.IsMirror:
            if opt.config_name or self._ShouldConfigureUser(
                opt, existing_checkout
            ):
                self._ConfigureUser(opt)
            self._ConfigureColor()

        if not opt.quiet:
            self._DisplayResult()
