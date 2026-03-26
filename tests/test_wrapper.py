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

import io
import os
import re
import subprocess
import sys
from unittest import mock

import pytest
import utils_for_test

import main
import wrapper


@pytest.fixture(autouse=True)
def reset_wrapper() -> None:
    """Reset the wrapper module every time."""
    wrapper.Wrapper.cache_clear()


@pytest.fixture
def repo_wrapper() -> wrapper.Wrapper:
    """Fixture for the wrapper module."""
    return wrapper.Wrapper()


class GitCheckout:
    """Class to hold git checkout info for tests."""

    def __init__(self, git_dir, rev_list):
        self.git_dir = git_dir
        self.rev_list = rev_list


@pytest.fixture(scope="module")
def git_checkout(tmp_path_factory) -> GitCheckout:
    """Fixture for tests that use a real/small git checkout.

    Create a repo to operate on, but do it once per-test-run.
    """
    tempdir = tmp_path_factory.mktemp("repo-rev-tests")
    run_git = wrapper.Wrapper().run_git

    remote = os.path.join(tempdir, "remote")
    os.mkdir(remote)

    utils_for_test.init_git_tree(remote)
    run_git("commit", "--allow-empty", "-minit", cwd=remote)
    run_git("branch", "stable", cwd=remote)
    run_git("tag", "v1.0", cwd=remote)
    run_git("commit", "--allow-empty", "-m2nd commit", cwd=remote)
    rev_list = run_git("rev-list", "HEAD", cwd=remote).stdout.splitlines()

    run_git("init", cwd=tempdir)
    run_git(
        "fetch",
        remote,
        "+refs/heads/*:refs/remotes/origin/*",
        cwd=tempdir,
    )
    yield GitCheckout(tempdir, rev_list)


class TestRepoWrapper:
    """Tests helper functions in the repo wrapper"""

    def test_version(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Make sure _Version works."""
        with pytest.raises(SystemExit) as e:
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                with mock.patch(
                    "sys.stderr", new_callable=io.StringIO
                ) as stderr:
                    repo_wrapper._Version()
        assert e.value.code == 0
        assert stderr.getvalue() == ""
        assert "repo launcher version" in stdout.getvalue()

    def test_python_constraints(self, repo_wrapper: wrapper.Wrapper) -> None:
        """The launcher should never require newer than main.py."""
        assert (
            main.MIN_PYTHON_VERSION_HARD >= repo_wrapper.MIN_PYTHON_VERSION_HARD
        )
        assert (
            main.MIN_PYTHON_VERSION_SOFT >= repo_wrapper.MIN_PYTHON_VERSION_SOFT
        )
        # Make sure the versions are themselves in sync.
        assert (
            repo_wrapper.MIN_PYTHON_VERSION_SOFT
            >= repo_wrapper.MIN_PYTHON_VERSION_HARD
        )

    def test_init_parser(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Make sure 'init' GetParser works."""
        parser = repo_wrapper.GetParser()
        opts, args = parser.parse_args([])
        assert args == []
        assert opts.manifest_url is None


class TestSetGitTrace2ParentSid:
    """Check SetGitTrace2ParentSid behavior."""

    KEY = "GIT_TRACE2_PARENT_SID"
    VALID_FORMAT = re.compile(r"^repo-[0-9]{8}T[0-9]{6}Z-P[0-9a-f]{8}$")

    def test_first_set(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Test env var not yet set."""
        env = {}
        repo_wrapper.SetGitTrace2ParentSid(env)
        assert self.KEY in env
        value = env[self.KEY]
        assert self.VALID_FORMAT.match(value)

    def test_append(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Test env var is appended."""
        env = {self.KEY: "pfx"}
        repo_wrapper.SetGitTrace2ParentSid(env)
        assert self.KEY in env
        value = env[self.KEY]
        assert value.startswith("pfx/")
        assert self.VALID_FORMAT.match(value[4:])

    def test_global_context(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check os.environ gets updated by default."""
        os.environ.pop(self.KEY, None)
        repo_wrapper.SetGitTrace2ParentSid()
        assert self.KEY in os.environ
        value = os.environ[self.KEY]
        assert self.VALID_FORMAT.match(value)


class TestRunCommand:
    """Check run_command behavior."""

    def test_capture(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check capture_output handling."""
        ret = repo_wrapper.run_command(["echo", "hi"], capture_output=True)
        # echo command appends OS specific linesep, but on Windows + Git Bash
        # we get UNIX ending, so we allow both.
        assert ret.stdout in ["hi" + os.linesep, "hi\n"]

    def test_check(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check check handling."""
        repo_wrapper.run_command(["true"], check=False)
        repo_wrapper.run_command(["true"], check=True)
        repo_wrapper.run_command(["false"], check=False)
        with pytest.raises(subprocess.CalledProcessError):
            repo_wrapper.run_command(["false"], check=True)


class TestRunGit:
    """Check run_git behavior."""

    def test_capture(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check capture_output handling."""
        ret = repo_wrapper.run_git("--version")
        assert "git" in ret.stdout

    def test_check(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check check handling."""
        with pytest.raises(repo_wrapper.CloneFailure):
            repo_wrapper.run_git("--version-asdfasdf")
        repo_wrapper.run_git("--version-asdfasdf", check=False)


class TestParseGitVersion:
    """Check ParseGitVersion behavior."""

    def test_autoload(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check we can load the version from the live git."""
        assert repo_wrapper.ParseGitVersion() is not None

    def test_bad_ver(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check handling of bad git versions."""
        assert repo_wrapper.ParseGitVersion(ver_str="asdf") is None

    def test_normal_ver(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check handling of normal git versions."""
        ret = repo_wrapper.ParseGitVersion(ver_str="git version 2.25.1")
        assert ret.major == 2
        assert ret.minor == 25
        assert ret.micro == 1
        assert ret.full == "2.25.1"

    def test_extended_ver(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check handling of extended distro git versions."""
        ret = repo_wrapper.ParseGitVersion(
            ver_str="git version 1.30.50.696.g5e7596f4ac-goog"
        )
        assert ret.major == 1
        assert ret.minor == 30
        assert ret.micro == 50
        assert ret.full == "1.30.50.696.g5e7596f4ac-goog"


class TestCheckGitVersion:
    """Check _CheckGitVersion behavior."""

    def test_unknown(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Unknown versions should abort."""
        with mock.patch.object(
            repo_wrapper, "ParseGitVersion", return_value=None
        ):
            with pytest.raises(repo_wrapper.CloneFailure):
                repo_wrapper._CheckGitVersion()

    def test_old(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Old versions should abort."""
        with mock.patch.object(
            repo_wrapper,
            "ParseGitVersion",
            return_value=repo_wrapper.GitVersion(1, 0, 0, "1.0.0"),
        ):
            with pytest.raises(repo_wrapper.CloneFailure):
                repo_wrapper._CheckGitVersion()

    def test_new(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Newer versions should run fine."""
        with mock.patch.object(
            repo_wrapper,
            "ParseGitVersion",
            return_value=repo_wrapper.GitVersion(100, 0, 0, "100.0.0"),
        ):
            repo_wrapper._CheckGitVersion()


class TestRequirements:
    """Check Requirements handling."""

    def test_missing_file(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Don't crash if the file is missing (old version)."""
        assert (
            repo_wrapper.Requirements.from_dir(utils_for_test.THIS_DIR) is None
        )
        assert (
            repo_wrapper.Requirements.from_file(
                utils_for_test.THIS_DIR / "xxxxxxxxxxxxxxxxxxxxxxxx"
            )
            is None
        )

    def test_corrupt_data(self, repo_wrapper: wrapper.Wrapper) -> None:
        """If the file can't be parsed, don't blow up."""
        assert repo_wrapper.Requirements.from_file(__file__) is None
        assert repo_wrapper.Requirements.from_data(b"x") is None

    def test_valid_data(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Make sure we can parse the file we ship."""
        assert repo_wrapper.Requirements.from_data(b"{}") is not None
        rootdir = utils_for_test.THIS_DIR.parent
        assert repo_wrapper.Requirements.from_dir(rootdir) is not None
        assert (
            repo_wrapper.Requirements.from_file(rootdir / "requirements.json")
            is not None
        )

    def test_format_ver(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check format_ver can format."""
        assert repo_wrapper.Requirements._format_ver((1, 2, 3)) == "1.2.3"
        assert repo_wrapper.Requirements._format_ver([1]) == "1"

    def test_assert_all_unknown(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_all works with incompatible file."""
        reqs = repo_wrapper.Requirements({})
        reqs.assert_all()

    def test_assert_all_new_repo(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_all accepts new enough repo."""
        reqs = repo_wrapper.Requirements({"repo": {"hard": [1, 0]}})
        reqs.assert_all()

    def test_assert_all_old_repo(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_all rejects old repo."""
        reqs = repo_wrapper.Requirements({"repo": {"hard": [99999, 0]}})
        with pytest.raises(SystemExit):
            reqs.assert_all()

    def test_assert_all_new_python(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_all accepts new enough python."""
        reqs = repo_wrapper.Requirements({"python": {"hard": sys.version_info}})
        reqs.assert_all()

    def test_assert_all_old_python(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_all rejects old python."""
        reqs = repo_wrapper.Requirements({"python": {"hard": [99999, 0]}})
        with pytest.raises(SystemExit):
            reqs.assert_all()

    def test_assert_ver_unknown(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_ver works with incompatible file."""
        reqs = repo_wrapper.Requirements({})
        reqs.assert_ver("xxx", (1, 0))

    def test_assert_ver_new(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_ver allows new enough versions."""
        reqs = repo_wrapper.Requirements(
            {"git": {"hard": [1, 0], "soft": [2, 0]}}
        )
        reqs.assert_ver("git", (1, 0))
        reqs.assert_ver("git", (1, 5))
        reqs.assert_ver("git", (2, 0))
        reqs.assert_ver("git", (2, 5))

    def test_assert_ver_old(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check assert_ver rejects old versions."""
        reqs = repo_wrapper.Requirements(
            {"git": {"hard": [1, 0], "soft": [2, 0]}}
        )
        with pytest.raises(SystemExit):
            reqs.assert_ver("git", (0, 5))


class TestNeedSetupGnuPG:
    """Check NeedSetupGnuPG behavior."""

    def test_missing_dir(self, tmp_path, repo_wrapper: wrapper.Wrapper) -> None:
        """The ~/.repoconfig tree doesn't exist yet."""
        repo_wrapper.home_dot_repo = str(tmp_path / "foo")
        assert repo_wrapper.NeedSetupGnuPG()

    def test_missing_keyring(
        self, tmp_path, repo_wrapper: wrapper.Wrapper
    ) -> None:
        """The keyring-version file doesn't exist yet."""
        repo_wrapper.home_dot_repo = str(tmp_path)
        assert repo_wrapper.NeedSetupGnuPG()

    def test_empty_keyring(
        self, tmp_path, repo_wrapper: wrapper.Wrapper
    ) -> None:
        """The keyring-version file exists, but is empty."""
        repo_wrapper.home_dot_repo = str(tmp_path)
        (tmp_path / "keyring-version").write_text("")
        assert repo_wrapper.NeedSetupGnuPG()

    def test_old_keyring(self, tmp_path, repo_wrapper: wrapper.Wrapper) -> None:
        """The keyring-version file exists, but it's old."""
        repo_wrapper.home_dot_repo = str(tmp_path)
        (tmp_path / "keyring-version").write_text("1.0\n")
        assert repo_wrapper.NeedSetupGnuPG()

    def test_new_keyring(self, tmp_path, repo_wrapper: wrapper.Wrapper) -> None:
        """The keyring-version file exists, and is up-to-date."""
        repo_wrapper.home_dot_repo = str(tmp_path)
        (tmp_path / "keyring-version").write_text("1000.0\n")
        assert not repo_wrapper.NeedSetupGnuPG()


class TestSetupGnuPG:
    """Check SetupGnuPG behavior."""

    def test_full(self, tmp_path, repo_wrapper: wrapper.Wrapper) -> None:
        """Make sure it works completely."""
        repo_wrapper.home_dot_repo = str(tmp_path)
        repo_wrapper.gpg_dir = str(tmp_path / "gnupg")
        assert repo_wrapper.SetupGnuPG(True)
        data = (tmp_path / "keyring-version").read_text()
        assert (
            ".".join(str(x) for x in repo_wrapper.KEYRING_VERSION)
            == data.strip()
        )


class TestVerifyRev:
    """Check verify_rev behavior."""

    def test_verify_passes(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check when we have a valid signed tag."""
        desc_result = subprocess.CompletedProcess([], 0, "v1.0\n", "")
        gpg_result = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(
            repo_wrapper, "run_git", side_effect=(desc_result, gpg_result)
        ):
            ret = repo_wrapper.verify_rev(
                "/", "refs/heads/stable", "1234", True
            )
            assert ret == "v1.0^0"

    def test_unsigned_commit(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check we fall back to signed tag when we have an unsigned commit."""
        desc_result = subprocess.CompletedProcess([], 0, "v1.0-10-g1234\n", "")
        gpg_result = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(
            repo_wrapper, "run_git", side_effect=(desc_result, gpg_result)
        ):
            ret = repo_wrapper.verify_rev(
                "/", "refs/heads/stable", "1234", True
            )
            assert ret == "v1.0^0"

    def test_verify_fails(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Check we fall back to signed tag when we have an unsigned commit."""
        desc_result = subprocess.CompletedProcess([], 0, "v1.0-10-g1234\n", "")
        gpg_result = RuntimeError
        with mock.patch.object(
            repo_wrapper, "run_git", side_effect=(desc_result, gpg_result)
        ):
            with pytest.raises(RuntimeError):
                repo_wrapper.verify_rev("/", "refs/heads/stable", "1234", True)


class TestResolveRepoRev:
    """Check resolve_repo_rev behavior."""

    def test_explicit_branch(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check refs/heads/branch argument."""
        rrev, lrev = repo_wrapper.resolve_repo_rev(
            git_checkout.git_dir, "refs/heads/stable"
        )
        assert rrev == "refs/heads/stable"
        assert lrev == git_checkout.rev_list[1]

        with pytest.raises(repo_wrapper.CloneFailure):
            repo_wrapper.resolve_repo_rev(
                git_checkout.git_dir, "refs/heads/unknown"
            )

    def test_explicit_tag(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check refs/tags/tag argument."""
        rrev, lrev = repo_wrapper.resolve_repo_rev(
            git_checkout.git_dir, "refs/tags/v1.0"
        )
        assert rrev == "refs/tags/v1.0"
        assert lrev == git_checkout.rev_list[1]

        with pytest.raises(repo_wrapper.CloneFailure):
            repo_wrapper.resolve_repo_rev(
                git_checkout.git_dir, "refs/tags/unknown"
            )

    def test_branch_name(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check branch argument."""
        rrev, lrev = repo_wrapper.resolve_repo_rev(
            git_checkout.git_dir, "stable"
        )
        assert rrev == "refs/heads/stable"
        assert lrev == git_checkout.rev_list[1]

        rrev, lrev = repo_wrapper.resolve_repo_rev(git_checkout.git_dir, "main")
        assert rrev == "refs/heads/main"
        assert lrev == git_checkout.rev_list[0]

    def test_tag_name(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check tag argument."""
        rrev, lrev = repo_wrapper.resolve_repo_rev(git_checkout.git_dir, "v1.0")
        assert rrev == "refs/tags/v1.0"
        assert lrev == git_checkout.rev_list[1]

    def test_full_commit(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check specific commit argument."""
        commit = git_checkout.rev_list[0]
        rrev, lrev = repo_wrapper.resolve_repo_rev(git_checkout.git_dir, commit)
        assert rrev == commit
        assert lrev == commit

    def test_partial_commit(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check specific (partial) commit argument."""
        commit = git_checkout.rev_list[0][0:20]
        rrev, lrev = repo_wrapper.resolve_repo_rev(git_checkout.git_dir, commit)
        assert rrev == git_checkout.rev_list[0]
        assert lrev == git_checkout.rev_list[0]

    def test_unknown(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Check unknown ref/commit argument."""
        with pytest.raises(repo_wrapper.CloneFailure):
            repo_wrapper.resolve_repo_rev(git_checkout.git_dir, "boooooooya")


class TestCheckRepoVerify:
    """Check check_repo_verify behavior."""

    def test_no_verify(self, repo_wrapper: wrapper.Wrapper) -> None:
        """Always fail with --no-repo-verify."""
        assert not repo_wrapper.check_repo_verify(False)

    def test_gpg_initialized(
        self,
        repo_wrapper: wrapper.Wrapper,
    ) -> None:
        """Should pass if gpg is setup already."""
        with mock.patch.object(
            repo_wrapper, "NeedSetupGnuPG", return_value=False
        ):
            assert repo_wrapper.check_repo_verify(True)

    def test_need_gpg_setup(
        self,
        repo_wrapper: wrapper.Wrapper,
    ) -> None:
        """Should pass/fail based on gpg setup."""
        with mock.patch.object(
            repo_wrapper, "NeedSetupGnuPG", return_value=True
        ):
            with mock.patch.object(repo_wrapper, "SetupGnuPG") as m:
                m.return_value = True
                assert repo_wrapper.check_repo_verify(True)

                m.return_value = False
                assert not repo_wrapper.check_repo_verify(True)


class TestCheckRepoRev:
    """Check check_repo_rev behavior."""

    def test_verify_works(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Should pass when verification passes."""
        with mock.patch.object(
            repo_wrapper, "check_repo_verify", return_value=True
        ):
            with mock.patch.object(
                repo_wrapper, "verify_rev", return_value="12345"
            ):
                rrev, lrev = repo_wrapper.check_repo_rev(
                    git_checkout.git_dir, "stable"
                )
        assert rrev == "refs/heads/stable"
        assert lrev == "12345"

    def test_verify_fails(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Should fail when verification fails."""
        with mock.patch.object(
            repo_wrapper, "check_repo_verify", return_value=True
        ):
            with mock.patch.object(
                repo_wrapper, "verify_rev", side_effect=RuntimeError
            ):
                with pytest.raises(RuntimeError):
                    repo_wrapper.check_repo_rev(git_checkout.git_dir, "stable")

    def test_verify_ignore(
        self,
        repo_wrapper: wrapper.Wrapper,
        git_checkout: GitCheckout,
    ) -> None:
        """Should pass when verification is disabled."""
        with mock.patch.object(
            repo_wrapper, "verify_rev", side_effect=RuntimeError
        ):
            rrev, lrev = repo_wrapper.check_repo_rev(
                git_checkout.git_dir, "stable", repo_verify=False
            )
        assert rrev == "refs/heads/stable"
        assert lrev == git_checkout.rev_list[1]
