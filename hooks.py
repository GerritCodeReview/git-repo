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

import errno
import json
import os
import re
import subprocess
import sys
import traceback
import urllib.parse

from error import HookError
from git_refs import HEAD


class RepoHook(object):
  """A RepoHook contains information about a script to run as a hook.

  Hooks are used to run a python script before running an upload (for instance,
  to run presubmit checks).  Eventually, we may have hooks for other actions.

  This shouldn't be confused with files in the 'repo/hooks' directory.  Those
  files are copied into each '.git/hooks' folder for each project.  Repo-level
  hooks are associated instead with repo actions.

  Hooks are always python.  When a hook is run, we will load the hook into the
  interpreter and execute its main() function.

  Combinations of hook option flags:
  - no-verify=False, verify=False (DEFAULT):
    If stdout is a tty, can prompt about running hooks if needed.
    If user denies running hooks, the action is cancelled. If stdout is
    not a tty and we would need to prompt about hooks, action is
    cancelled.
  - no-verify=False, verify=True:
    Always run hooks with no prompt.
  - no-verify=True, verify=False:
    Never run hooks, but run action anyway (AKA bypass hooks).
  - no-verify=True, verify=True:
    Invalid
  """

  def __init__(self,
               hook_type,
               hooks_project,
               repo_topdir,
               manifest_url,
               bypass_hooks=False,
               allow_all_hooks=False,
               ignore_hooks=False,
               abort_if_user_denies=False):
    """RepoHook constructor.

    Params:
      hook_type: A string representing the type of hook.  This is also used
          to figure out the name of the file containing the hook.  For
          example: 'pre-upload'.
      hooks_project: The project containing the repo hooks.
          If you have a manifest, this is manifest.repo_hooks_project.
          OK if this is None, which will make the hook a no-op.
      repo_topdir: The top directory of the repo client checkout.
          This is the one containing the .repo directory. Scripts will
          run with CWD as this directory.
          If you have a manifest, this is manifest.topdir.
      manifest_url: The URL to the manifest git repo.
      bypass_hooks: If True, then 'Do not run the hook'.
      allow_all_hooks: If True, then 'Run the hook without prompting'.
      ignore_hooks: If True, then 'Do not abort action if hooks fail'.
      abort_if_user_denies: If True, we'll abort running the hook if the user
          doesn't allow us to run the hook.
    """
    self._hook_type = hook_type
    self._hooks_project = hooks_project
    self._repo_topdir = repo_topdir
    self._manifest_url = manifest_url
    self._bypass_hooks = bypass_hooks
    self._allow_all_hooks = allow_all_hooks
    self._ignore_hooks = ignore_hooks
    self._abort_if_user_denies = abort_if_user_denies

    # Store the full path to the script for convenience.
    if self._hooks_project:
      self._script_fullpath = os.path.join(self._hooks_project.worktree,
                                           self._hook_type + '.py')
    else:
      self._script_fullpath = None

  def _GetHash(self):
    """Return a hash of the contents of the hooks directory.

    We'll just use git to do this.  This hash has the property that if anything
    changes in the directory we will return a different has.

    SECURITY CONSIDERATION:
      This hash only represents the contents of files in the hook directory, not
      any other files imported or called by hooks.  Changes to imported files
      can change the script behavior without affecting the hash.

    Returns:
      A string representing the hash.  This will always be ASCII so that it can
      be printed to the user easily.
    """
    assert self._hooks_project, "Must have hooks to calculate their hash."

    # We will use the work_git object rather than just calling GetRevisionId().
    # That gives us a hash of the latest checked in version of the files that
    # the user will actually be executing.  Specifically, GetRevisionId()
    # doesn't appear to change even if a user checks out a different version
    # of the hooks repo (via git checkout) nor if a user commits their own revs.
    #
    # NOTE: Local (non-committed) changes will not be factored into this hash.
    # I think this is OK, since we're really only worried about warning the user
    # about upstream changes.
    return self._hooks_project.work_git.rev_parse(HEAD)

  def _GetMustVerb(self):
    """Return 'must' if the hook is required; 'should' if not."""
    if self._abort_if_user_denies:
      return 'must'
    else:
      return 'should'

  def _CheckForHookApproval(self):
    """Check to see whether this hook has been approved.

    We'll accept approval of manifest URLs if they're using secure transports.
    This way the user can say they trust the manifest hoster.  For insecure
    hosts, we fall back to checking the hash of the hooks repo.

    Note that we ask permission for each individual hook even though we use
    the hash of all hooks when detecting changes.  We'd like the user to be
    able to approve / deny each hook individually.  We only use the hash of all
    hooks because there is no other easy way to detect changes to local imports.

    Returns:
      True if this hook is approved to run; False otherwise.

    Raises:
      HookError: Raised if the user doesn't approve and abort_if_user_denies
          was passed to the consturctor.
    """
    if self._ManifestUrlHasSecureScheme():
      return self._CheckForHookApprovalManifest()
    else:
      return self._CheckForHookApprovalHash()

  def _CheckForHookApprovalHelper(self, subkey, new_val, main_prompt,
                                  changed_prompt):
    """Check for approval for a particular attribute and hook.

    Args:
      subkey: The git config key under [repo.hooks.<hook_type>] to store the
          last approved string.
      new_val: The new value to compare against the last approved one.
      main_prompt: Message to display to the user to ask for approval.
      changed_prompt: Message explaining why we're re-asking for approval.

    Returns:
      True if this hook is approved to run; False otherwise.

    Raises:
      HookError: Raised if the user doesn't approve and abort_if_user_denies
          was passed to the consturctor.
    """
    hooks_config = self._hooks_project.config
    git_approval_key = 'repo.hooks.%s.%s' % (self._hook_type, subkey)

    # Get the last value that the user approved for this hook; may be None.
    old_val = hooks_config.GetString(git_approval_key)

    if old_val is not None:
      # User previously approved hook and asked not to be prompted again.
      if new_val == old_val:
        # Approval matched.  We're done.
        return True
      else:
        # Give the user a reason why we're prompting, since they last told
        # us to "never ask again".
        prompt = 'WARNING: %s\n\n' % (changed_prompt,)
    else:
      prompt = ''

    # Prompt the user if we're not on a tty; on a tty we'll assume "no".
    if sys.stdout.isatty():
      prompt += main_prompt + ' (yes/always/NO)? '
      response = input(prompt).lower()
      print()

      # User is doing a one-time approval.
      if response in ('y', 'yes'):
        return True
      elif response == 'always':
        hooks_config.SetString(git_approval_key, new_val)
        return True

    # For anything else, we'll assume no approval.
    if self._abort_if_user_denies:
      raise HookError('You must allow the %s hook or use --no-verify.' %
                      self._hook_type)

    return False

  def _ManifestUrlHasSecureScheme(self):
    """Check if the URI for the manifest is a secure transport."""
    secure_schemes = ('file', 'https', 'ssh', 'persistent-https', 'sso', 'rpc')
    parse_results = urllib.parse.urlparse(self._manifest_url)
    return parse_results.scheme in secure_schemes

  def _CheckForHookApprovalManifest(self):
    """Check whether the user has approved this manifest host.

    Returns:
      True if this hook is approved to run; False otherwise.
    """
    return self._CheckForHookApprovalHelper(
        'approvedmanifest',
        self._manifest_url,
        'Run hook scripts from %s' % (self._manifest_url,),
        'Manifest URL has changed since %s was allowed.' % (self._hook_type,))

  def _CheckForHookApprovalHash(self):
    """Check whether the user has approved the hooks repo.

    Returns:
      True if this hook is approved to run; False otherwise.
    """
    prompt = ('Repo %s run the script:\n'
              '  %s\n'
              '\n'
              'Do you want to allow this script to run')
    return self._CheckForHookApprovalHelper(
        'approvedhash',
        self._GetHash(),
        prompt % (self._GetMustVerb(), self._script_fullpath),
        'Scripts have changed since %s was allowed.' % (self._hook_type,))

  @staticmethod
  def _ExtractInterpFromShebang(data):
    """Extract the interpreter used in the shebang.

    Try to locate the interpreter the script is using (ignoring `env`).

    Args:
      data: The file content of the script.

    Returns:
      The basename of the main script interpreter, or None if a shebang is not
      used or could not be parsed out.
    """
    firstline = data.splitlines()[:1]
    if not firstline:
      return None

    # The format here can be tricky.
    shebang = firstline[0].strip()
    m = re.match(r'^#!\s*([^\s]+)(?:\s+([^\s]+))?', shebang)
    if not m:
      return None

    # If the using `env`, find the target program.
    interp = m.group(1)
    if os.path.basename(interp) == 'env':
      interp = m.group(2)

    return interp

  def _ExecuteHookViaReexec(self, interp, context, **kwargs):
    """Execute the hook script through |interp|.

    Note: Support for this feature should be dropped ~Jun 2021.

    Args:
      interp: The Python program to run.
      context: Basic Python context to execute the hook inside.
      kwargs: Arbitrary arguments to pass to the hook script.

    Raises:
      HookError: When the hooks failed for any reason.
    """
    # This logic needs to be kept in sync with _ExecuteHookViaImport below.
    script = """
import json, os, sys
path = '''%(path)s'''
kwargs = json.loads('''%(kwargs)s''')
context = json.loads('''%(context)s''')
sys.path.insert(0, os.path.dirname(path))
data = open(path).read()
exec(compile(data, path, 'exec'), context)
context['main'](**kwargs)
""" % {
        'path': self._script_fullpath,
        'kwargs': json.dumps(kwargs),
        'context': json.dumps(context),
    }

    # We pass the script via stdin to avoid OS argv limits.  It also makes
    # unhandled exception tracebacks less verbose/confusing for users.
    cmd = [interp, '-c', 'import sys; exec(sys.stdin.read())']
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    proc.communicate(input=script.encode('utf-8'))
    if proc.returncode:
      raise HookError('Failed to run %s hook.' % (self._hook_type,))

  def _ExecuteHookViaImport(self, data, context, **kwargs):
    """Execute the hook code in |data| directly.

    Args:
      data: The code of the hook to execute.
      context: Basic Python context to execute the hook inside.
      kwargs: Arbitrary arguments to pass to the hook script.

    Raises:
      HookError: When the hooks failed for any reason.
    """
    # Exec, storing global context in the context dict.  We catch exceptions
    # and convert to a HookError w/ just the failing traceback.
    try:
      exec(compile(data, self._script_fullpath, 'exec'), context)
    except Exception:
      raise HookError('%s\nFailed to import %s hook; see traceback above.' %
                      (traceback.format_exc(), self._hook_type))

    # Running the script should have defined a main() function.
    if 'main' not in context:
      raise HookError('Missing main() in: "%s"' % self._script_fullpath)

    # Call the main function in the hook.  If the hook should cause the
    # build to fail, it will raise an Exception.  We'll catch that convert
    # to a HookError w/ just the failing traceback.
    try:
      context['main'](**kwargs)
    except Exception:
      raise HookError('%s\nFailed to run main() for %s hook; see traceback '
                      'above.' % (traceback.format_exc(), self._hook_type))

  def _ExecuteHook(self, **kwargs):
    """Actually execute the given hook.

    This will run the hook's 'main' function in our python interpreter.

    Args:
      kwargs: Keyword arguments to pass to the hook.  These are often specific
          to the hook type.  For instance, pre-upload hooks will contain
          a project_list.
    """
    # Keep sys.path and CWD stashed away so that we can always restore them
    # upon function exit.
    orig_path = os.getcwd()
    orig_syspath = sys.path

    try:
      # Always run hooks with CWD as topdir.
      os.chdir(self._repo_topdir)

      # Put the hook dir as the first item of sys.path so hooks can do
      # relative imports.  We want to replace the repo dir as [0] so
      # hooks can't import repo files.
      sys.path = [os.path.dirname(self._script_fullpath)] + sys.path[1:]

      # Initial global context for the hook to run within.
      context = {'__file__': self._script_fullpath}

      # Add 'hook_should_take_kwargs' to the arguments to be passed to main.
      # We don't actually want hooks to define their main with this argument--
      # it's there to remind them that their hook should always take **kwargs.
      # For instance, a pre-upload hook should be defined like:
      #   def main(project_list, **kwargs):
      #
      # This allows us to later expand the API without breaking old hooks.
      kwargs = kwargs.copy()
      kwargs['hook_should_take_kwargs'] = True

      # See what version of python the hook has been written against.
      data = open(self._script_fullpath).read()
      interp = self._ExtractInterpFromShebang(data)
      reexec = False
      if interp:
        prog = os.path.basename(interp)
        if prog.startswith('python2') and sys.version_info.major != 2:
          reexec = True
        elif prog.startswith('python3') and sys.version_info.major == 2:
          reexec = True

      # Attempt to execute the hooks through the requested version of Python.
      if reexec:
        try:
          self._ExecuteHookViaReexec(interp, context, **kwargs)
        except OSError as e:
          if e.errno == errno.ENOENT:
            # We couldn't find the interpreter, so fallback to importing.
            reexec = False
          else:
            raise

      # Run the hook by importing directly.
      if not reexec:
        self._ExecuteHookViaImport(data, context, **kwargs)
    finally:
      # Restore sys.path and CWD.
      sys.path = orig_syspath
      os.chdir(orig_path)

  def _CheckHook(self):
    # Bail with a nice error if we can't find the hook.
    if not os.path.isfile(self._script_fullpath):
      raise HookError('Couldn\'t find repo hook: %s' % self._script_fullpath)

  def Run(self, **kwargs):
    """Run the hook.

    If the hook doesn't exist (because there is no hooks project or because
    this particular hook is not enabled), this is a no-op.

    Args:
      user_allows_all_hooks: If True, we will never prompt about running the
          hook--we'll just assume it's OK to run it.
      kwargs: Keyword arguments to pass to the hook.  These are often specific
          to the hook type.  For instance, pre-upload hooks will contain
          a project_list.

    Returns:
      True: On success or ignore hooks by user-request
      False: The hook failed. The caller should respond with aborting the action.
        Some examples in which False is returned:
        * Finding the hook failed while it was enabled, or
        * the user declined to run a required hook (from _CheckForHookApproval)
        In all these cases the user did not pass the proper arguments to
        ignore the result through the option combinations as listed in
        AddHookOptionGroup().
    """
    # Do not do anything in case bypass_hooks is set, or
    # no-op if there is no hooks project or if hook is disabled.
    if (self._bypass_hooks or
        not self._hooks_project or
        self._hook_type not in self._hooks_project.enabled_repo_hooks):
      return True

    passed = True
    try:
      self._CheckHook()

      # Make sure the user is OK with running the hook.
      if self._allow_all_hooks or self._CheckForHookApproval():
        # Run the hook with the same version of python we're using.
        self._ExecuteHook(**kwargs)
    except SystemExit as e:
      passed = False
      print('ERROR: %s hooks exited with exit code: %s' % (self._hook_type, str(e)),
            file=sys.stderr)
    except HookError as e:
      passed = False
      print('ERROR: %s' % str(e), file=sys.stderr)

    if not passed and self._ignore_hooks:
      print('\nWARNING: %s hooks failed, but continuing anyways.' % self._hook_type,
            file=sys.stderr)
      passed = True

    return passed

  @classmethod
  def FromSubcmd(cls, manifest, opt, *args, **kwargs):
    """Method to construct the repo hook class

    Args:
      manifest: The current active manifest for this command from which we
          extract a couple of fields.
      opt: Contains the commandline options for the action of this hook.
          It should contain the options added by AddHookOptionGroup() in which
          we are interested in RepoHook execution.
    """
    for key in ('bypass_hooks', 'allow_all_hooks', 'ignore_hooks'):
      kwargs.setdefault(key, getattr(opt, key))
    kwargs.update({
        'hooks_project': manifest.repo_hooks_project,
        'repo_topdir': manifest.topdir,
        'manifest_url': manifest.manifestProject.GetRemote('origin').url,
    })
    return cls(*args, **kwargs)

  @staticmethod
  def AddOptionGroup(parser, name):
    """Help options relating to the various hooks."""

    # Note that verify and no-verify are NOT opposites of each other, which
    # is why they store to different locations. We are using them to match
    # 'git commit' syntax.
    group = parser.add_option_group(name + ' hooks')
    group.add_option('--no-verify',
                     dest='bypass_hooks', action='store_true',
                     help='Do not run the %s hook.' % name)
    group.add_option('--verify',
                     dest='allow_all_hooks', action='store_true',
                     help='Run the %s hook without prompting.' % name)
    group.add_option('--ignore-hooks',
                     action='store_true',
                     help='Do not abort if %s hooks fail.' % name)
