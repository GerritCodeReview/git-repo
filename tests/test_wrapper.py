# Copyright (C) 2015 The Android Open Source Project
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

"""Unittests for the wrapper.py module."""

from io import StringIO
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

import git_command
import main
import wrapper


def fixture(*paths):
  """Return a path relative to tests/fixtures.
  """
  return os.path.join(os.path.dirname(__file__), 'fixtures', *paths)


class RepoWrapperTestCase(unittest.TestCase):
  """TestCase for the wrapper module."""

  def setUp(self):
    """Load the wrapper module every time."""
    wrapper.Wrapper.cache_clear()
    self.wrapper = wrapper.Wrapper()


class RepoWrapperUnitTest(RepoWrapperTestCase):
  """Tests helper functions in the repo wrapper
  """

  def test_version(self):
    """Make sure _Version works."""
    with self.assertRaises(SystemExit) as e:
      with mock.patch('sys.stdout', new_callable=StringIO) as stdout:
        with mock.patch('sys.stderr', new_callable=StringIO) as stderr:
          self.wrapper._Version()
    self.assertEqual(0, e.exception.code)
    self.assertEqual('', stderr.getvalue())
    self.assertIn('repo launcher version', stdout.getvalue())

  def test_python_constraints(self):
    """The launcher should never require newer than main.py."""
    self.assertGreaterEqual(main.MIN_PYTHON_VERSION_HARD,
                            self.wrapper.MIN_PYTHON_VERSION_HARD)
    self.assertGreaterEqual(main.MIN_PYTHON_VERSION_SOFT,
                            self.wrapper.MIN_PYTHON_VERSION_SOFT)
    # Make sure the versions are themselves in sync.
    self.assertGreaterEqual(self.wrapper.MIN_PYTHON_VERSION_SOFT,
                            self.wrapper.MIN_PYTHON_VERSION_HARD)

  def test_init_parser(self):
    """Make sure 'init' GetParser works."""
    parser = self.wrapper.GetParser(gitc_init=False)
    opts, args = parser.parse_args([])
    self.assertEqual([], args)
    self.assertIsNone(opts.manifest_url)

  def test_gitc_init_parser(self):
    """Make sure 'gitc-init' GetParser works."""
    parser = self.wrapper.GetParser(gitc_init=True)
    opts, args = parser.parse_args([])
    self.assertEqual([], args)
    self.assertIsNone(opts.manifest_file)

  def test_get_gitc_manifest_dir_no_gitc(self):
    """
    Test reading a missing gitc config file
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('missing_gitc_config')
    val = self.wrapper.get_gitc_manifest_dir()
    self.assertEqual(val, '')

  def test_get_gitc_manifest_dir(self):
    """
    Test reading the gitc config file and parsing the directory
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('gitc_config')
    val = self.wrapper.get_gitc_manifest_dir()
    self.assertEqual(val, '/test/usr/local/google/gitc')

  def test_gitc_parse_clientdir_no_gitc(self):
    """
    Test parsing the gitc clientdir without gitc running
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('missing_gitc_config')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/something'), None)
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test'), 'test')

  def test_gitc_parse_clientdir(self):
    """
    Test parsing the gitc clientdir
    """
    self.wrapper.GITC_CONFIG_FILE = fixture('gitc_config')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/something'), None)
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test/'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/test/extra'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/test'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/test/'), 'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/test/extra'),
                     'test')
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/gitc/manifest-rw/'), None)
    self.assertEqual(self.wrapper.gitc_parse_clientdir('/test/usr/local/google/gitc/'), None)


class SetGitTrace2ParentSid(RepoWrapperTestCase):
  """Check SetGitTrace2ParentSid behavior."""

  KEY = 'GIT_TRACE2_PARENT_SID'
  VALID_FORMAT = re.compile(r'^repo-[0-9]{8}T[0-9]{6}Z-P[0-9a-f]{8}$')

  def test_first_set(self):
    """Test env var not yet set."""
    env = {}
    self.wrapper.SetGitTrace2ParentSid(env)
    self.assertIn(self.KEY, env)
    value = env[self.KEY]
    self.assertRegex(value, self.VALID_FORMAT)

  def test_append(self):
    """Test env var is appended."""
    env = {self.KEY: 'pfx'}
    self.wrapper.SetGitTrace2ParentSid(env)
    self.assertIn(self.KEY, env)
    value = env[self.KEY]
    self.assertTrue(value.startswith('pfx/'))
    self.assertRegex(value[4:], self.VALID_FORMAT)

  def test_global_context(self):
    """Check os.environ gets updated by default."""
    os.environ.pop(self.KEY, None)
    self.wrapper.SetGitTrace2ParentSid()
    self.assertIn(self.KEY, os.environ)
    value = os.environ[self.KEY]
    self.assertRegex(value, self.VALID_FORMAT)


class RunCommand(RepoWrapperTestCase):
  """Check run_command behavior."""

  def test_capture(self):
    """Check capture_output handling."""
    ret = self.wrapper.run_command(['echo', 'hi'], capture_output=True)
    # echo command appends OS specific linesep, but on Windows + Git Bash
    # we get UNIX ending, so we allow both.
    self.assertIn(ret.stdout, ['hi' + os.linesep, 'hi\n'])

  def test_check(self):
    """Check check handling."""
    self.wrapper.run_command(['true'], check=False)
    self.wrapper.run_command(['true'], check=True)
    self.wrapper.run_command(['false'], check=False)
    with self.assertRaises(self.wrapper.RunError):
      self.wrapper.run_command(['false'], check=True)


class RunGit(RepoWrapperTestCase):
  """Check run_git behavior."""

  def test_capture(self):
    """Check capture_output handling."""
    ret = self.wrapper.run_git('--version')
    self.assertIn('git', ret.stdout)

  def test_check(self):
    """Check check handling."""
    with self.assertRaises(self.wrapper.CloneFailure):
      self.wrapper.run_git('--version-asdfasdf')
    self.wrapper.run_git('--version-asdfasdf', check=False)


class ParseGitVersion(RepoWrapperTestCase):
  """Check ParseGitVersion behavior."""

  def test_autoload(self):
    """Check we can load the version from the live git."""
    ret = self.wrapper.ParseGitVersion()
    self.assertIsNotNone(ret)

  def test_bad_ver(self):
    """Check handling of bad git versions."""
    ret = self.wrapper.ParseGitVersion(ver_str='asdf')
    self.assertIsNone(ret)

  def test_normal_ver(self):
    """Check handling of normal git versions."""
    ret = self.wrapper.ParseGitVersion(ver_str='git version 2.25.1')
    self.assertEqual(2, ret.major)
    self.assertEqual(25, ret.minor)
    self.assertEqual(1, ret.micro)
    self.assertEqual('2.25.1', ret.full)

  def test_extended_ver(self):
    """Check handling of extended distro git versions."""
    ret = self.wrapper.ParseGitVersion(
        ver_str='git version 1.30.50.696.g5e7596f4ac-goog')
    self.assertEqual(1, ret.major)
    self.assertEqual(30, ret.minor)
    self.assertEqual(50, ret.micro)
    self.assertEqual('1.30.50.696.g5e7596f4ac-goog', ret.full)


class CheckGitVersion(RepoWrapperTestCase):
  """Check _CheckGitVersion behavior."""

  def test_unknown(self):
    """Unknown versions should abort."""
    with mock.patch.object(self.wrapper, 'ParseGitVersion', return_value=None):
      with self.assertRaises(self.wrapper.CloneFailure):
        self.wrapper._CheckGitVersion()

  def test_old(self):
    """Old versions should abort."""
    with mock.patch.object(
        self.wrapper, 'ParseGitVersion',
        return_value=self.wrapper.GitVersion(1, 0, 0, '1.0.0')):
      with self.assertRaises(self.wrapper.CloneFailure):
        self.wrapper._CheckGitVersion()

  def test_new(self):
    """Newer versions should run fine."""
    with mock.patch.object(
        self.wrapper, 'ParseGitVersion',
        return_value=self.wrapper.GitVersion(100, 0, 0, '100.0.0')):
      self.wrapper._CheckGitVersion()


class Requirements(RepoWrapperTestCase):
  """Check Requirements handling."""

  def test_missing_file(self):
    """Don't crash if the file is missing (old version)."""
    testdir = os.path.dirname(os.path.realpath(__file__))
    self.assertIsNone(self.wrapper.Requirements.from_dir(testdir))
    self.assertIsNone(self.wrapper.Requirements.from_file(
        os.path.join(testdir, 'xxxxxxxxxxxxxxxxxxxxxxxx')))

  def test_corrupt_data(self):
    """If the file can't be parsed, don't blow up."""
    self.assertIsNone(self.wrapper.Requirements.from_file(__file__))
    self.assertIsNone(self.wrapper.Requirements.from_data(b'x'))

  def test_valid_data(self):
    """Make sure we can parse the file we ship."""
    self.assertIsNotNone(self.wrapper.Requirements.from_data(b'{}'))
    rootdir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    self.assertIsNotNone(self.wrapper.Requirements.from_dir(rootdir))
    self.assertIsNotNone(self.wrapper.Requirements.from_file(os.path.join(
        rootdir, 'requirements.json')))

  def test_format_ver(self):
    """Check format_ver can format."""
    self.assertEqual('1.2.3', self.wrapper.Requirements._format_ver((1, 2, 3)))
    self.assertEqual('1', self.wrapper.Requirements._format_ver([1]))

  def test_assert_all_unknown(self):
    """Check assert_all works with incompatible file."""
    reqs = self.wrapper.Requirements({})
    reqs.assert_all()

  def test_assert_all_new_repo(self):
    """Check assert_all accepts new enough repo."""
    reqs = self.wrapper.Requirements({'repo': {'hard': [1, 0]}})
    reqs.assert_all()

  def test_assert_all_old_repo(self):
    """Check assert_all rejects old repo."""
    reqs = self.wrapper.Requirements({'repo': {'hard': [99999, 0]}})
    with self.assertRaises(SystemExit):
      reqs.assert_all()

  def test_assert_all_new_python(self):
    """Check assert_all accepts new enough python."""
    reqs = self.wrapper.Requirements({'python': {'hard': sys.version_info}})
    reqs.assert_all()

  def test_assert_all_old_python(self):
    """Check assert_all rejects old python."""
    reqs = self.wrapper.Requirements({'python': {'hard': [99999, 0]}})
    with self.assertRaises(SystemExit):
      reqs.assert_all()

  def test_assert_ver_unknown(self):
    """Check assert_ver works with incompatible file."""
    reqs = self.wrapper.Requirements({})
    reqs.assert_ver('xxx', (1, 0))

  def test_assert_ver_new(self):
    """Check assert_ver allows new enough versions."""
    reqs = self.wrapper.Requirements({'git': {'hard': [1, 0], 'soft': [2, 0]}})
    reqs.assert_ver('git', (1, 0))
    reqs.assert_ver('git', (1, 5))
    reqs.assert_ver('git', (2, 0))
    reqs.assert_ver('git', (2, 5))

  def test_assert_ver_old(self):
    """Check assert_ver rejects old versions."""
    reqs = self.wrapper.Requirements({'git': {'hard': [1, 0], 'soft': [2, 0]}})
    with self.assertRaises(SystemExit):
      reqs.assert_ver('git', (0, 5))


class NeedSetupGnuPG(RepoWrapperTestCase):
  """Check NeedSetupGnuPG behavior."""

  def test_missing_dir(self):
    """The ~/.repoconfig tree doesn't exist yet."""
    with tempfile.TemporaryDirectory(prefix='repo-tests') as tempdir:
      self.wrapper.home_dot_repo = os.path.join(tempdir, 'foo')
      self.assertTrue(self.wrapper.NeedSetupGnuPG())

  def test_missing_keyring(self):
    """The keyring-version file doesn't exist yet."""
    with tempfile.TemporaryDirectory(prefix='repo-tests') as tempdir:
      self.wrapper.home_dot_repo = tempdir
      self.assertTrue(self.wrapper.NeedSetupGnuPG())

  def test_empty_keyring(self):
    """The keyring-version file exists, but is empty."""
    with tempfile.TemporaryDirectory(prefix='repo-tests') as tempdir:
      self.wrapper.home_dot_repo = tempdir
      with open(os.path.join(tempdir, 'keyring-version'), 'w'):
        pass
      self.assertTrue(self.wrapper.NeedSetupGnuPG())

  def test_old_keyring(self):
    """The keyring-version file exists, but it's old."""
    with tempfile.TemporaryDirectory(prefix='repo-tests') as tempdir:
      self.wrapper.home_dot_repo = tempdir
      with open(os.path.join(tempdir, 'keyring-version'), 'w') as fp:
        fp.write('1.0\n')
      self.assertTrue(self.wrapper.NeedSetupGnuPG())

  def test_new_keyring(self):
    """The keyring-version file exists, and is up-to-date."""
    with tempfile.TemporaryDirectory(prefix='repo-tests') as tempdir:
      self.wrapper.home_dot_repo = tempdir
      with open(os.path.join(tempdir, 'keyring-version'), 'w') as fp:
        fp.write('1000.0\n')
      self.assertFalse(self.wrapper.NeedSetupGnuPG())


class SetupGnuPG(RepoWrapperTestCase):
  """Check SetupGnuPG behavior."""

  def test_full(self):
    """Make sure it works completely."""
    with tempfile.TemporaryDirectory(prefix='repo-tests') as tempdir:
      self.wrapper.home_dot_repo = tempdir
      self.wrapper.gpg_dir = os.path.join(self.wrapper.home_dot_repo, 'gnupg')
      self.assertTrue(self.wrapper.SetupGnuPG(True))
      with open(os.path.join(tempdir, 'keyring-version'), 'r') as fp:
        data = fp.read()
      self.assertEqual('.'.join(str(x) for x in self.wrapper.KEYRING_VERSION),
                       data.strip())


class VerifyRev(RepoWrapperTestCase):
  """Check verify_rev behavior."""

  def test_verify_passes(self):
    """Check when we have a valid signed tag."""
    desc_result = self.wrapper.RunResult(0, 'v1.0\n', '')
    gpg_result = self.wrapper.RunResult(0, '', '')
    with mock.patch.object(self.wrapper, 'run_git',
                           side_effect=(desc_result, gpg_result)):
      ret = self.wrapper.verify_rev('/', 'refs/heads/stable', '1234', True)
      self.assertEqual('v1.0^0', ret)

  def test_unsigned_commit(self):
    """Check we fall back to signed tag when we have an unsigned commit."""
    desc_result = self.wrapper.RunResult(0, 'v1.0-10-g1234\n', '')
    gpg_result = self.wrapper.RunResult(0, '', '')
    with mock.patch.object(self.wrapper, 'run_git',
                           side_effect=(desc_result, gpg_result)):
      ret = self.wrapper.verify_rev('/', 'refs/heads/stable', '1234', True)
      self.assertEqual('v1.0^0', ret)

  def test_verify_fails(self):
    """Check we fall back to signed tag when we have an unsigned commit."""
    desc_result = self.wrapper.RunResult(0, 'v1.0-10-g1234\n', '')
    gpg_result = Exception
    with mock.patch.object(self.wrapper, 'run_git',
                           side_effect=(desc_result, gpg_result)):
      with self.assertRaises(Exception):
        self.wrapper.verify_rev('/', 'refs/heads/stable', '1234', True)


class GitCheckoutTestCase(RepoWrapperTestCase):
  """Tests that use a real/small git checkout."""

  GIT_DIR = None
  REV_LIST = None

  @classmethod
  def setUpClass(cls):
    # Create a repo to operate on, but do it once per-class.
    cls.tempdirobj = tempfile.TemporaryDirectory(prefix='repo-rev-tests')
    cls.GIT_DIR = cls.tempdirobj.name
    run_git = wrapper.Wrapper().run_git

    remote = os.path.join(cls.GIT_DIR, 'remote')
    os.mkdir(remote)

    # Tests need to assume, that main is default branch at init,
    # which is not supported in config until 2.28.
    if git_command.git_require((2, 28, 0)):
      initstr = '--initial-branch=main'
    else:
      # Use template dir for init.
      templatedir = tempfile.mkdtemp(prefix='.test-template')
      with open(os.path.join(templatedir, 'HEAD'), 'w') as fp:
        fp.write('ref: refs/heads/main\n')
      initstr = '--template=' + templatedir

    run_git('init', initstr, cwd=remote)
    run_git('commit', '--allow-empty', '-minit', cwd=remote)
    run_git('branch', 'stable', cwd=remote)
    run_git('tag', 'v1.0', cwd=remote)
    run_git('commit', '--allow-empty', '-m2nd commit', cwd=remote)
    cls.REV_LIST = run_git('rev-list', 'HEAD', cwd=remote).stdout.splitlines()

    run_git('init', cwd=cls.GIT_DIR)
    run_git('fetch', remote, '+refs/heads/*:refs/remotes/origin/*', cwd=cls.GIT_DIR)

  @classmethod
  def tearDownClass(cls):
    if not cls.tempdirobj:
      return

    cls.tempdirobj.cleanup()


class ResolveRepoRev(GitCheckoutTestCase):
  """Check resolve_repo_rev behavior."""

  def test_explicit_branch(self):
    """Check refs/heads/branch argument."""
    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, 'refs/heads/stable')
    self.assertEqual('refs/heads/stable', rrev)
    self.assertEqual(self.REV_LIST[1], lrev)

    with self.assertRaises(self.wrapper.CloneFailure):
      self.wrapper.resolve_repo_rev(self.GIT_DIR, 'refs/heads/unknown')

  def test_explicit_tag(self):
    """Check refs/tags/tag argument."""
    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, 'refs/tags/v1.0')
    self.assertEqual('refs/tags/v1.0', rrev)
    self.assertEqual(self.REV_LIST[1], lrev)

    with self.assertRaises(self.wrapper.CloneFailure):
      self.wrapper.resolve_repo_rev(self.GIT_DIR, 'refs/tags/unknown')

  def test_branch_name(self):
    """Check branch argument."""
    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, 'stable')
    self.assertEqual('refs/heads/stable', rrev)
    self.assertEqual(self.REV_LIST[1], lrev)

    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, 'main')
    self.assertEqual('refs/heads/main', rrev)
    self.assertEqual(self.REV_LIST[0], lrev)

  def test_tag_name(self):
    """Check tag argument."""
    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, 'v1.0')
    self.assertEqual('refs/tags/v1.0', rrev)
    self.assertEqual(self.REV_LIST[1], lrev)

  def test_full_commit(self):
    """Check specific commit argument."""
    commit = self.REV_LIST[0]
    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, commit)
    self.assertEqual(commit, rrev)
    self.assertEqual(commit, lrev)

  def test_partial_commit(self):
    """Check specific (partial) commit argument."""
    commit = self.REV_LIST[0][0:20]
    rrev, lrev = self.wrapper.resolve_repo_rev(self.GIT_DIR, commit)
    self.assertEqual(self.REV_LIST[0], rrev)
    self.assertEqual(self.REV_LIST[0], lrev)

  def test_unknown(self):
    """Check unknown ref/commit argument."""
    with self.assertRaises(self.wrapper.CloneFailure):
      self.wrapper.resolve_repo_rev(self.GIT_DIR, 'boooooooya')


class CheckRepoVerify(RepoWrapperTestCase):
  """Check check_repo_verify behavior."""

  def test_no_verify(self):
    """Always fail with --no-repo-verify."""
    self.assertFalse(self.wrapper.check_repo_verify(False))

  def test_gpg_initialized(self):
    """Should pass if gpg is setup already."""
    with mock.patch.object(self.wrapper, 'NeedSetupGnuPG', return_value=False):
      self.assertTrue(self.wrapper.check_repo_verify(True))

  def test_need_gpg_setup(self):
    """Should pass/fail based on gpg setup."""
    with mock.patch.object(self.wrapper, 'NeedSetupGnuPG', return_value=True):
      with mock.patch.object(self.wrapper, 'SetupGnuPG') as m:
        m.return_value = True
        self.assertTrue(self.wrapper.check_repo_verify(True))

        m.return_value = False
        self.assertFalse(self.wrapper.check_repo_verify(True))


class CheckRepoRev(GitCheckoutTestCase):
  """Check check_repo_rev behavior."""

  def test_verify_works(self):
    """Should pass when verification passes."""
    with mock.patch.object(self.wrapper, 'check_repo_verify', return_value=True):
      with mock.patch.object(self.wrapper, 'verify_rev', return_value='12345'):
        rrev, lrev = self.wrapper.check_repo_rev(self.GIT_DIR, 'stable')
    self.assertEqual('refs/heads/stable', rrev)
    self.assertEqual('12345', lrev)

  def test_verify_fails(self):
    """Should fail when verification fails."""
    with mock.patch.object(self.wrapper, 'check_repo_verify', return_value=True):
      with mock.patch.object(self.wrapper, 'verify_rev', side_effect=Exception):
        with self.assertRaises(Exception):
          self.wrapper.check_repo_rev(self.GIT_DIR, 'stable')

  def test_verify_ignore(self):
    """Should pass when verification is disabled."""
    with mock.patch.object(self.wrapper, 'verify_rev', side_effect=Exception):
      rrev, lrev = self.wrapper.check_repo_rev(self.GIT_DIR, 'stable', repo_verify=False)
    self.assertEqual('refs/heads/stable', rrev)
    self.assertEqual(self.REV_LIST[1], lrev)
