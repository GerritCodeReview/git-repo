#!/usr/bin/env python3
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

"""The repo tool.

People shouldn't run this directly; instead, they should use the `repo` wrapper
which takes care of execing this entry point.
"""

import getpass
import json
import netrc
import optparse
import os
import shlex
import signal
import sys
import textwrap
import time
import urllib.request

from repo_logging import RepoLogger


try:
    import kerberos
except ImportError:
    kerberos = None

from color import SetDefaultColoring
from command import InteractiveCommand
from command import MirrorSafeCommand
from editor import Editor
from error import DownloadError
from error import GitcUnsupportedError
from error import InvalidProjectGroupsError
from error import ManifestInvalidRevisionError
from error import ManifestParseError
from error import NoManifestException
from error import NoSuchProjectError
from error import RepoChangedException
from error import RepoError
from error import RepoExitError
from error import RepoUnhandledExceptionError
from error import SilentRepoExitError
import event_log
from git_command import user_agent
from git_config import RepoConfig
from git_trace2_event_log import EventLog
from manifest_xml import RepoClient
from pager import RunPager
from pager import TerminatePager
from repo_trace import SetTrace
from repo_trace import SetTraceToStderr
from repo_trace import Trace
from subcmds import all_commands
from subcmds.version import Version
from wrapper import Wrapper
from wrapper import WrapperPath


logger = RepoLogger(__file__)


# NB: These do not need to be kept in sync with the repo launcher script.
# These may be much newer as it allows the repo launcher to roll between
# different repo releases while source versions might require a newer python.
#
# The soft version is when we start warning users that the version is old and
# we'll be dropping support for it.  We'll refuse to work with versions older
# than the hard version.
#
# python-3.6 is in Ubuntu Bionic.
MIN_PYTHON_VERSION_SOFT = (3, 6)
MIN_PYTHON_VERSION_HARD = (3, 6)

if sys.version_info < MIN_PYTHON_VERSION_HARD:
    logger.error(
        "repo: error: Python version is too old; "
        "Please upgrade to Python %d.%d+.",
        *MIN_PYTHON_VERSION_SOFT,
    )
    sys.exit(1)
elif sys.version_info < MIN_PYTHON_VERSION_SOFT:
    logger.error(
        "repo: warning: your Python version is no longer supported; "
        "Please upgrade to Python %d.%d+.",
        *MIN_PYTHON_VERSION_SOFT,
    )

KEYBOARD_INTERRUPT_EXIT = 128 + signal.SIGINT
MAX_PRINT_ERRORS = 5

global_options = optparse.OptionParser(
    usage="repo [-p|--paginate|--no-pager] COMMAND [ARGS]",
    add_help_option=False,
)
global_options.add_option(
    "-h", "--help", action="store_true", help="show this help message and exit"
)
global_options.add_option(
    "--help-all",
    action="store_true",
    help="show this help message with all subcommands and exit",
)
global_options.add_option(
    "-p",
    "--paginate",
    dest="pager",
    action="store_true",
    help="display command output in the pager",
)
global_options.add_option(
    "--no-pager", dest="pager", action="store_false", help="disable the pager"
)
global_options.add_option(
    "--color",
    choices=("auto", "always", "never"),
    default=None,
    help="control color usage: auto, always, never",
)
global_options.add_option(
    "--trace",
    dest="trace",
    action="store_true",
    help="trace git command execution (REPO_TRACE=1)",
)
global_options.add_option(
    "--trace-to-stderr",
    dest="trace_to_stderr",
    action="store_true",
    help="trace outputs go to stderr in addition to .repo/TRACE_FILE",
)
global_options.add_option(
    "--trace-python",
    dest="trace_python",
    action="store_true",
    help="trace python command execution",
)
global_options.add_option(
    "--time",
    dest="time",
    action="store_true",
    help="time repo command execution",
)
global_options.add_option(
    "--version",
    dest="show_version",
    action="store_true",
    help="display this version of repo",
)
global_options.add_option(
    "--show-toplevel",
    action="store_true",
    help="display the path of the top-level directory of "
    "the repo client checkout",
)
global_options.add_option(
    "--event-log",
    dest="event_log",
    action="store",
    help="filename of event log to append timeline to",
)
global_options.add_option(
    "--git-trace2-event-log",
    action="store",
    help="directory to write git trace2 event log to",
)
global_options.add_option(
    "--submanifest-path",
    action="store",
    metavar="REL_PATH",
    help="submanifest path",
)


class _Repo:
    def __init__(self, repodir):
        self.repodir = repodir
        self.commands = all_commands

    def _PrintHelp(self, short: bool = False, all_commands: bool = False):
        """Show --help screen."""
        global_options.print_help()
        print()
        if short:
            commands = " ".join(sorted(self.commands))
            wrapped_commands = textwrap.wrap(commands, width=77)
            help_commands = "".join(f"\n  {x}" for x in wrapped_commands)
            print(f"Available commands:{help_commands}")
            print("\nRun `repo help <command>` for command-specific details.")
            print("Bug reports:", Wrapper().BUG_URL)
        else:
            cmd = self.commands["help"]()
            if all_commands:
                cmd.PrintAllCommandsBody()
            else:
                cmd.PrintCommonCommandsBody()

    def _ParseArgs(self, argv):
        """Parse the main `repo` command line options."""
        for i, arg in enumerate(argv):
            if not arg.startswith("-"):
                name = arg
                glob = argv[:i]
                argv = argv[i + 1 :]
                break
        else:
            name = None
            glob = argv
            argv = []
        gopts, _gargs = global_options.parse_args(glob)

        if name:
            name, alias_args = self._ExpandAlias(name)
            argv = alias_args + argv

        return (name, gopts, argv)

    def _ExpandAlias(self, name):
        """Look up user registered aliases."""
        # We don't resolve aliases for existing subcommands.  This matches git.
        if name in self.commands:
            return name, []

        key = f"alias.{name}"
        alias = RepoConfig.ForRepository(self.repodir).GetString(key)
        if alias is None:
            alias = RepoConfig.ForUser().GetString(key)
        if alias is None:
            return name, []

        args = alias.strip().split(" ", 1)
        name = args[0]
        if len(args) == 2:
            args = shlex.split(args[1])
        else:
            args = []
        return name, args

    def _Run(self, name, gopts, argv):
        """Execute the requested subcommand."""
        result = 0

        # Handle options that terminate quickly first.
        if gopts.help or gopts.help_all:
            self._PrintHelp(short=False, all_commands=gopts.help_all)
            return 0
        elif gopts.show_version:
            # Always allow global --version regardless of subcommand validity.
            name = "version"
        elif gopts.show_toplevel:
            print(os.path.dirname(self.repodir))
            return 0
        elif not name:
            # No subcommand specified, so show the help/subcommand.
            self._PrintHelp(short=True)
            return 1

        git_trace2_event_log = EventLog()
        run = (
            lambda: self._RunLong(name, gopts, argv, git_trace2_event_log) or 0
        )
        with Trace(
            "starting new command: %s [sid=%s]",
            ", ".join([name] + argv),
            git_trace2_event_log.full_sid,
            first_trace=True,
        ):
            if gopts.trace_python:
                import trace

                tracer = trace.Trace(
                    count=False,
                    trace=True,
                    timing=True,
                    ignoredirs=set(sys.path[1:]),
                )
                result = tracer.runfunc(run)
            else:
                result = run()
        return result

    def _RunLong(self, name, gopts, argv, git_trace2_event_log):
        """Execute the (longer running) requested subcommand."""
        result = 0
        SetDefaultColoring(gopts.color)

        outer_client = RepoClient(self.repodir)
        repo_client = outer_client
        if gopts.submanifest_path:
            repo_client = RepoClient(
                self.repodir,
                submanifest_path=gopts.submanifest_path,
                outer_client=outer_client,
            )

        if Wrapper().gitc_parse_clientdir(os.getcwd()):
            logger.error("GITC is not supported.")
            raise GitcUnsupportedError()

        try:
            cmd = self.commands[name](
                repodir=self.repodir,
                client=repo_client,
                manifest=repo_client.manifest,
                outer_client=outer_client,
                outer_manifest=outer_client.manifest,
                git_event_log=git_trace2_event_log,
            )
        except KeyError:
            logger.error(
                "repo: '%s' is not a repo command.  See 'repo help'.", name
            )
            return 1

        Editor.globalConfig = cmd.client.globalConfig

        if not isinstance(cmd, MirrorSafeCommand) and cmd.manifest.IsMirror:
            logger.error("fatal: '%s' requires a working directory", name)
            return 1

        try:
            copts, cargs = cmd.OptionParser.parse_args(argv)
            copts = cmd.ReadEnvironmentOptions(copts)
        except NoManifestException as e:
            logger.error("error: in `%s`: %s", " ".join([name] + argv), e)
            logger.error(
                "error: manifest missing or unreadable -- please run init"
            )
            return 1

        if gopts.pager is not False and not isinstance(cmd, InteractiveCommand):
            config = cmd.client.globalConfig
            if gopts.pager:
                use_pager = True
            else:
                use_pager = config.GetBoolean("pager.%s" % name)
                if use_pager is None:
                    use_pager = cmd.WantPager(copts)
            if use_pager:
                RunPager(config)

        start = time.time()
        cmd_event = cmd.event_log.Add(name, event_log.TASK_COMMAND, start)
        cmd.event_log.SetParent(cmd_event)
        git_trace2_event_log.StartEvent()
        git_trace2_event_log.CommandEvent(name="repo", subcommands=[name])

        def execute_command_helper():
            """
            Execute the subcommand.
            """
            nonlocal result
            cmd.CommonValidateOptions(copts, cargs)
            cmd.ValidateOptions(copts, cargs)

            this_manifest_only = copts.this_manifest_only
            outer_manifest = copts.outer_manifest
            if cmd.MULTI_MANIFEST_SUPPORT or this_manifest_only:
                result = cmd.Execute(copts, cargs)
            elif outer_manifest and repo_client.manifest.is_submanifest:
                # The command does not support multi-manifest, we are using a
                # submanifest, and the command line is for the outermost
                # manifest. Re-run using the outermost manifest, which will
                # recurse through the submanifests.
                gopts.submanifest_path = ""
                result = self._Run(name, gopts, argv)
            else:
                # No multi-manifest support. Run the command in the current
                # (sub)manifest, and then any child submanifests.
                result = cmd.Execute(copts, cargs)
                for submanifest in repo_client.manifest.submanifests.values():
                    spec = submanifest.ToSubmanifestSpec()
                    gopts.submanifest_path = submanifest.repo_client.path_prefix
                    child_argv = argv[:]
                    child_argv.append("--no-outer-manifest")
                    # Not all subcommands support the 3 manifest options, so
                    # only add them if the original command includes them.
                    if hasattr(copts, "manifest_url"):
                        child_argv.extend(["--manifest-url", spec.manifestUrl])
                    if hasattr(copts, "manifest_name"):
                        child_argv.extend(
                            ["--manifest-name", spec.manifestName]
                        )
                    if hasattr(copts, "manifest_branch"):
                        child_argv.extend(["--manifest-branch", spec.revision])
                    result = self._Run(name, gopts, child_argv) or result

        def execute_command():
            """
            Execute the command and log uncaught exceptions.
            """
            try:
                execute_command_helper()
            except (
                KeyboardInterrupt,
                SystemExit,
                Exception,
                RepoExitError,
            ) as e:
                ok = isinstance(e, SystemExit) and not e.code
                exception_name = type(e).__name__
                if isinstance(e, RepoUnhandledExceptionError):
                    exception_name = type(e.error).__name__
                if isinstance(e, RepoExitError):
                    aggregated_errors = e.aggregate_errors or []
                    for error in aggregated_errors:
                        project = None
                        if isinstance(error, RepoError):
                            project = error.project
                        error_info = json.dumps(
                            {
                                "ErrorType": type(error).__name__,
                                "Project": str(project),
                                "Message": str(error),
                            }
                        )
                        git_trace2_event_log.ErrorEvent(
                            f"AggregateExitError:{error_info}"
                        )
                if not ok:
                    git_trace2_event_log.ErrorEvent(
                        f"RepoExitError:{exception_name}"
                    )
                raise

        try:
            execute_command()
        except (
            DownloadError,
            ManifestInvalidRevisionError,
            ManifestParseError,
            NoManifestException,
        ) as e:
            logger.error("error: in `%s`: %s", " ".join([name] + argv), e)
            if isinstance(e, NoManifestException):
                logger.error(
                    "error: manifest missing or unreadable -- please run init"
                )
            result = e.exit_code
        except NoSuchProjectError as e:
            if e.name:
                logger.error("error: project %s not found", e.name)
            else:
                logger.error("error: no project in current directory")
            result = e.exit_code
        except InvalidProjectGroupsError as e:
            if e.name:
                logger.error(
                    "error: project group must be enabled for project %s",
                    e.name,
                )
            else:
                logger.error(
                    "error: project group must be enabled for the project in "
                    "the current directory"
                )
            result = e.exit_code
        except SystemExit as e:
            if e.code:
                result = e.code
            raise
        except KeyboardInterrupt:
            result = KEYBOARD_INTERRUPT_EXIT
            raise
        except RepoExitError as e:
            result = e.exit_code
            raise
        except Exception:
            result = 1
            raise
        finally:
            finish = time.time()
            elapsed = finish - start
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            if gopts.time:
                if hours == 0:
                    print(
                        "real\t%dm%.3fs" % (minutes, seconds), file=sys.stderr
                    )
                else:
                    print(
                        "real\t%dh%dm%.3fs" % (hours, minutes, seconds),
                        file=sys.stderr,
                    )

            cmd.event_log.FinishEvent(
                cmd_event, finish, result is None or result == 0
            )
            git_trace2_event_log.DefParamRepoEvents(
                cmd.manifest.manifestProject.config.DumpConfigDict()
            )
            git_trace2_event_log.ExitEvent(result)

            if gopts.event_log:
                cmd.event_log.Write(
                    os.path.abspath(os.path.expanduser(gopts.event_log))
                )

            git_trace2_event_log.Write(gopts.git_trace2_event_log)
        return result


def _CheckWrapperVersion(ver_str, repo_path):
    """Verify the repo launcher is new enough for this checkout.

    Args:
        ver_str: The version string passed from the repo launcher when it ran
            us.
        repo_path: The path to the repo launcher that loaded us.
    """
    # Refuse to work with really old wrapper versions.  We don't test these,
    # so might as well require a somewhat recent sane version.
    # v1.15 of the repo launcher was released in ~Mar 2012.
    MIN_REPO_VERSION = (1, 15)
    min_str = ".".join(str(x) for x in MIN_REPO_VERSION)

    if not repo_path:
        repo_path = "~/bin/repo"

    if not ver_str:
        logger.error("no --wrapper-version argument")
        sys.exit(1)

    # Pull out the version of the repo launcher we know about to compare.
    exp = Wrapper().VERSION
    ver = tuple(map(int, ver_str.split(".")))

    exp_str = ".".join(map(str, exp))
    if ver < MIN_REPO_VERSION:
        logger.error(
            """
repo: error:
!!! Your version of repo %s is too old.
!!! We need at least version %s.
!!! A new version of repo (%s) is available.
!!! You must upgrade before you can continue:

    cp %s %s
""",
            ver_str,
            min_str,
            exp_str,
            WrapperPath(),
            repo_path,
        )
        sys.exit(1)

    if exp > ver:
        logger.warning(
            "\n... A new version of repo (%s) is available.", exp_str
        )
        if os.access(repo_path, os.W_OK):
            logger.warning(
                """\
... You should upgrade soon:
    cp %s %s
""",
                WrapperPath(),
                repo_path,
            )
        else:
            logger.warning(
                """\
... New version is available at: %s
... The launcher is run from: %s
!!! The launcher is not writable.  Please talk to your sysadmin or distro
!!! to get an update installed.
""",
                WrapperPath(),
                repo_path,
            )


def _CheckRepoDir(repo_dir):
    if not repo_dir:
        logger.error("no --repo-dir argument")
        sys.exit(1)


def _PruneOptions(argv, opt):
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            break
        if a.startswith("--"):
            eq = a.find("=")
            if eq > 0:
                a = a[0:eq]
        if not opt.has_option(a):
            del argv[i]
            continue
        i += 1


class _UserAgentHandler(urllib.request.BaseHandler):
    def http_request(self, req):
        req.add_header("User-Agent", user_agent.repo)
        return req

    def https_request(self, req):
        req.add_header("User-Agent", user_agent.repo)
        return req


def _AddPasswordFromUserInput(handler, msg, req):
    # If repo could not find auth info from netrc, try to get it from user input
    url = req.get_full_url()
    user, password = handler.passwd.find_user_password(None, url)
    if user is None:
        print(msg)
        try:
            user = input("User: ")
            password = getpass.getpass()
        except KeyboardInterrupt:
            return
        handler.passwd.add_password(None, url, user, password)


class _BasicAuthHandler(urllib.request.HTTPBasicAuthHandler):
    def http_error_401(self, req, fp, code, msg, headers):
        _AddPasswordFromUserInput(self, msg, req)
        return urllib.request.HTTPBasicAuthHandler.http_error_401(
            self, req, fp, code, msg, headers
        )

    def http_error_auth_reqed(self, authreq, host, req, headers):
        try:
            old_add_header = req.add_header

            def _add_header(name, val):
                val = val.replace("\n", "")
                old_add_header(name, val)

            req.add_header = _add_header
            return (
                urllib.request.AbstractBasicAuthHandler.http_error_auth_reqed(
                    self, authreq, host, req, headers
                )
            )
        except Exception:
            reset = getattr(self, "reset_retry_count", None)
            if reset is not None:
                reset()
            elif getattr(self, "retried", None):
                self.retried = 0
            raise


class _DigestAuthHandler(urllib.request.HTTPDigestAuthHandler):
    def http_error_401(self, req, fp, code, msg, headers):
        _AddPasswordFromUserInput(self, msg, req)
        return urllib.request.HTTPDigestAuthHandler.http_error_401(
            self, req, fp, code, msg, headers
        )

    def http_error_auth_reqed(self, auth_header, host, req, headers):
        try:
            old_add_header = req.add_header

            def _add_header(name, val):
                val = val.replace("\n", "")
                old_add_header(name, val)

            req.add_header = _add_header
            return (
                urllib.request.AbstractDigestAuthHandler.http_error_auth_reqed(
                    self, auth_header, host, req, headers
                )
            )
        except Exception:
            reset = getattr(self, "reset_retry_count", None)
            if reset is not None:
                reset()
            elif getattr(self, "retried", None):
                self.retried = 0
            raise


class _KerberosAuthHandler(urllib.request.BaseHandler):
    def __init__(self):
        self.retried = 0
        self.context = None
        self.handler_order = urllib.request.BaseHandler.handler_order - 50

    def http_error_401(self, req, fp, code, msg, headers):
        host = req.get_host()
        retry = self.http_error_auth_reqed(
            "www-authenticate", host, req, headers
        )
        return retry

    def http_error_auth_reqed(self, auth_header, host, req, headers):
        try:
            spn = "HTTP@%s" % host
            authdata = self._negotiate_get_authdata(auth_header, headers)

            if self.retried > 3:
                raise urllib.request.HTTPError(
                    req.get_full_url(),
                    401,
                    "Negotiate auth failed",
                    headers,
                    None,
                )
            else:
                self.retried += 1

            neghdr = self._negotiate_get_svctk(spn, authdata)
            if neghdr is None:
                return None

            req.add_unredirected_header("Authorization", neghdr)
            response = self.parent.open(req)

            srvauth = self._negotiate_get_authdata(auth_header, response.info())
            if self._validate_response(srvauth):
                return response
        except kerberos.GSSError:
            return None
        except Exception:
            self.reset_retry_count()
            raise
        finally:
            self._clean_context()

    def reset_retry_count(self):
        self.retried = 0

    def _negotiate_get_authdata(self, auth_header, headers):
        authhdr = headers.get(auth_header, None)
        if authhdr is not None:
            for mech_tuple in authhdr.split(","):
                mech, __, authdata = mech_tuple.strip().partition(" ")
                if mech.lower() == "negotiate":
                    return authdata.strip()
        return None

    def _negotiate_get_svctk(self, spn, authdata):
        if authdata is None:
            return None

        result, self.context = kerberos.authGSSClientInit(spn)
        if result < kerberos.AUTH_GSS_COMPLETE:
            return None

        result = kerberos.authGSSClientStep(self.context, authdata)
        if result < kerberos.AUTH_GSS_CONTINUE:
            return None

        response = kerberos.authGSSClientResponse(self.context)
        return "Negotiate %s" % response

    def _validate_response(self, authdata):
        if authdata is None:
            return None
        result = kerberos.authGSSClientStep(self.context, authdata)
        if result == kerberos.AUTH_GSS_COMPLETE:
            return True
        return None

    def _clean_context(self):
        if self.context is not None:
            kerberos.authGSSClientClean(self.context)
            self.context = None


def init_http():
    handlers = [_UserAgentHandler()]

    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    try:
        n = netrc.netrc()
        for host in n.hosts:
            p = n.hosts[host]
            mgr.add_password(p[1], "http://%s/" % host, p[0], p[2])
            mgr.add_password(p[1], "https://%s/" % host, p[0], p[2])
    except netrc.NetrcParseError:
        pass
    except OSError:
        pass
    handlers.append(_BasicAuthHandler(mgr))
    handlers.append(_DigestAuthHandler(mgr))
    if kerberos:
        handlers.append(_KerberosAuthHandler())

    if "http_proxy" in os.environ:
        url = os.environ["http_proxy"]
        handlers.append(
            urllib.request.ProxyHandler({"http": url, "https": url})
        )
    if "REPO_CURL_VERBOSE" in os.environ:
        handlers.append(urllib.request.HTTPHandler(debuglevel=1))
        handlers.append(urllib.request.HTTPSHandler(debuglevel=1))
    urllib.request.install_opener(urllib.request.build_opener(*handlers))


def _Main(argv):
    result = 0

    opt = optparse.OptionParser(usage="repo wrapperinfo -- ...")
    opt.add_option("--repo-dir", dest="repodir", help="path to .repo/")
    opt.add_option(
        "--wrapper-version",
        dest="wrapper_version",
        help="version of the wrapper script",
    )
    opt.add_option(
        "--wrapper-path",
        dest="wrapper_path",
        help="location of the wrapper script",
    )
    _PruneOptions(argv, opt)
    opt, argv = opt.parse_args(argv)

    _CheckWrapperVersion(opt.wrapper_version, opt.wrapper_path)
    _CheckRepoDir(opt.repodir)

    Version.wrapper_version = opt.wrapper_version
    Version.wrapper_path = opt.wrapper_path

    repo = _Repo(opt.repodir)

    try:
        init_http()
        name, gopts, argv = repo._ParseArgs(argv)

        if gopts.trace:
            SetTrace()

        if gopts.trace_to_stderr:
            SetTraceToStderr()

        result = repo._Run(name, gopts, argv) or 0
    except RepoExitError as e:
        if not isinstance(e, SilentRepoExitError):
            logger.log_aggregated_errors(e)
        result = e.exit_code
    except KeyboardInterrupt:
        print("aborted by user", file=sys.stderr)
        result = KEYBOARD_INTERRUPT_EXIT
    except RepoChangedException as rce:
        # If repo changed, re-exec ourselves.
        argv = list(sys.argv)
        argv.extend(rce.extra_args)
        try:
            os.execv(sys.executable, [sys.executable, __file__] + argv)
        except OSError as e:
            print("fatal: cannot restart repo after upgrade", file=sys.stderr)
            print("fatal: %s" % e, file=sys.stderr)
            result = 128

    TerminatePager()
    sys.exit(result)


if __name__ == "__main__":
    _Main(sys.argv[1:])
