# Copyright 2019 The Android Open Source Project
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

"""Unittests for the git_command.py module."""

import io
import os
import re
import subprocess
import unittest
from unittest import mock

import pytest

import git_command
import wrapper


class GitCommandTest(unittest.TestCase):
    """Tests the GitCommand class (via git_command.git)."""

    def setUp(self):
        def realpath_mock(val):
            return val

        mock.patch.object(
            os.path, "realpath", side_effect=realpath_mock
        ).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_alternative_setting_when_matching(self):
        r = git_command._build_env(
            objdir=os.path.join("zap", "objects"), gitdir="zap"
        )

        self.assertIsNone(r.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"))
        self.assertEqual(
            r.get("GIT_OBJECT_DIRECTORY"), os.path.join("zap", "objects")
        )

    def test_alternative_setting_when_different(self):
        r = git_command._build_env(
            objdir=os.path.join("wow", "objects"), gitdir="zap"
        )

        self.assertEqual(
            r.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"),
            os.path.join("zap", "objects"),
        )
        self.assertEqual(
            r.get("GIT_OBJECT_DIRECTORY"), os.path.join("wow", "objects")
        )


class GitCommandWaitTest(unittest.TestCase):
    """Tests the GitCommand class .Wait()"""

    def setUp(self):
        class MockPopen:
            rc = 0

            def __init__(self):
                self.stdout = io.BufferedReader(io.BytesIO())
                self.stderr = io.BufferedReader(io.BytesIO())

            def communicate(
                self, input: str = None, timeout: float = None
            ) -> [str, str]:
                """Mock communicate fn."""
                return ["", ""]

            def wait(self, timeout=None):
                return self.rc

        self.popen = popen = MockPopen()

        def popen_mock(*args, **kwargs):
            return popen

        def realpath_mock(val):
            return val

        mock.patch.object(subprocess, "Popen", side_effect=popen_mock).start()

        mock.patch.object(
            os.path, "realpath", side_effect=realpath_mock
        ).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_raises_when_verify_non_zero_result(self):
        self.popen.rc = 1
        r = git_command.GitCommand(None, ["status"], verify_command=True)
        with self.assertRaises(git_command.GitCommandError):
            r.Wait()

    def test_returns_when_no_verify_non_zero_result(self):
        self.popen.rc = 1
        r = git_command.GitCommand(None, ["status"], verify_command=False)
        self.assertEqual(1, r.Wait())

    def test_default_returns_non_zero_result(self):
        self.popen.rc = 1
        r = git_command.GitCommand(None, ["status"])
        self.assertEqual(1, r.Wait())


class GitCommandStreamLogsTest(unittest.TestCase):
    """Tests the GitCommand class stderr log streaming cases."""

    def setUp(self):
        self.mock_process = mock.MagicMock()
        self.mock_process.communicate.return_value = (None, None)
        self.mock_process.wait.return_value = 0

        self.mock_popen = mock.MagicMock()
        self.mock_popen.return_value = self.mock_process
        mock.patch("subprocess.Popen", self.mock_popen).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_does_not_stream_logs_when_input_is_set(self):
        git_command.GitCommand(None, ["status"], input="foo")

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
        )
        self.mock_process.communicate.assert_called_once_with(input="foo")
        self.mock_process.stderr.read1.assert_not_called()

    def test_does_not_stream_logs_when_stdout_is_set(self):
        git_command.GitCommand(None, ["status"], capture_stdout=True)

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=None,
        )
        self.mock_process.communicate.assert_called_once_with(input=None)
        self.mock_process.stderr.read1.assert_not_called()

    def test_does_not_stream_logs_when_stderr_is_set(self):
        git_command.GitCommand(None, ["status"], capture_stderr=True)

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=None,
            stdout=None,
            stderr=subprocess.PIPE,
        )
        self.mock_process.communicate.assert_called_once_with(input=None)
        self.mock_process.stderr.read1.assert_not_called()

    def test_does_not_stream_logs_when_merge_output_is_set(self):
        git_command.GitCommand(None, ["status"], merge_output=True)

        self.mock_popen.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            env=mock.ANY,
            encoding="utf-8",
            errors="backslashreplace",
            stdin=None,
            stdout=None,
            stderr=subprocess.STDOUT,
        )
        self.mock_process.communicate.assert_called_once_with(input=None)
        self.mock_process.stderr.read1.assert_not_called()

    @mock.patch("sys.stderr")
    def test_streams_stderr_when_no_stream_is_set(self, mock_stderr):
        logs = "\n".join(
            [
                "Enumerating objects: 5, done.",
                "Counting objects: 100% (5/5), done.",
                "Writing objects: 100% (3/3), 330 bytes | 330 KiB/s, done.",
                "remote: Processing changes: refs: 1, new: 1, done ",
                "remote: SUCCESS",
            ]
        )
        self.mock_process.stderr = io.BufferedReader(
            io.BytesIO(bytes(logs, "utf-8"))
        )

        cmd = git_command.GitCommand(None, ["push"])

        self.mock_popen.assert_called_once_with(
            ["git", "push"],
            cwd=None,
            env=mock.ANY,
            stdin=None,
            stdout=None,
            stderr=subprocess.PIPE,
        )
        self.mock_process.communicate.assert_not_called()
        mock_stderr.write.assert_called_once_with(logs)
        self.assertEqual(cmd.stderr, logs)


class GitCallUnitTest(unittest.TestCase):
    """Tests the _GitCall class (via git_command.git)."""

    def test_version_tuple(self):
        """Check git.version_tuple() handling."""
        ver = git_command.git.version_tuple()
        self.assertIsNotNone(ver)

        # We don't dive too deep into the values here to avoid having to update
        # whenever git versions change.  We do check relative to this min
        # version as this is what `repo` itself requires via MIN_GIT_VERSION.
        MIN_GIT_VERSION = (2, 10, 2)
        self.assertTrue(isinstance(ver.major, int))
        self.assertTrue(isinstance(ver.minor, int))
        self.assertTrue(isinstance(ver.micro, int))

        self.assertGreater(ver.major, MIN_GIT_VERSION[0] - 1)
        self.assertGreaterEqual(ver.micro, 0)
        self.assertGreaterEqual(ver.major, 0)

        self.assertGreaterEqual(ver, MIN_GIT_VERSION)
        self.assertLess(ver, (9999, 9999, 9999))

        self.assertNotEqual("", ver.full)


class UserAgentUnitTest(unittest.TestCase):
    """Tests the UserAgent function."""

    def test_smoke_os(self):
        """Make sure UA OS setting returns something useful."""
        os_name = git_command.user_agent.os
        # We can't dive too deep because of OS/tool differences, but we can
        # check the general form.
        m = re.match(r"^[^ ]+$", os_name)
        self.assertIsNotNone(m)

    @pytest.mark.skip_cq("TODO(b/266734831): Find out why this fails in CQ")
    def test_smoke_repo(self):
        """Make sure repo UA returns something useful."""
        ua = git_command.user_agent.repo
        # We can't dive too deep because of OS/tool differences, but we can
        # check the general form.
        m = re.match(r"^git-repo/[^ ]+ ([^ ]+) git/[^ ]+ Python/[0-9.]+", ua)
        self.assertIsNotNone(m)

    @pytest.mark.skip_cq("TODO(b/266734831): Find out why this fails in CQ")
    def test_smoke_git(self):
        """Make sure git UA returns something useful."""
        ua = git_command.user_agent.git
        # We can't dive too deep because of OS/tool differences, but we can
        # check the general form.
        m = re.match(r"^git/[^ ]+ ([^ ]+) git-repo/[^ ]+", ua)
        self.assertIsNotNone(m)


class GitRequireTests(unittest.TestCase):
    """Test the git_require helper."""

    def setUp(self):
        self.wrapper = wrapper.Wrapper()
        ver = self.wrapper.GitVersion(1, 2, 3, 4)
        mock.patch.object(
            git_command.git, "version_tuple", return_value=ver
        ).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_older_nonfatal(self):
        """Test non-fatal require calls with old versions."""
        self.assertFalse(git_command.git_require((2,)))
        self.assertFalse(git_command.git_require((1, 3)))
        self.assertFalse(git_command.git_require((1, 2, 4)))
        self.assertFalse(git_command.git_require((1, 2, 3, 5)))

    def test_newer_nonfatal(self):
        """Test non-fatal require calls with newer versions."""
        self.assertTrue(git_command.git_require((0,)))
        self.assertTrue(git_command.git_require((1, 0)))
        self.assertTrue(git_command.git_require((1, 2, 0)))
        self.assertTrue(git_command.git_require((1, 2, 3, 0)))

    def test_equal_nonfatal(self):
        """Test require calls with equal values."""
        self.assertTrue(git_command.git_require((1, 2, 3, 4), fail=False))
        self.assertTrue(git_command.git_require((1, 2, 3, 4), fail=True))

    def test_older_fatal(self):
        """Test fatal require calls with old versions."""
        with self.assertRaises(git_command.GitRequireError) as e:
            git_command.git_require((2,), fail=True)
            self.assertNotEqual(0, e.code)

    def test_older_fatal_msg(self):
        """Test fatal require calls with old versions and message."""
        with self.assertRaises(git_command.GitRequireError) as e:
            git_command.git_require((2,), fail=True, msg="so sad")
            self.assertNotEqual(0, e.code)


class GitCommandErrorTest(unittest.TestCase):
    """Test for the GitCommandError class."""

    def test_augument_stderr(self):
        self.assertEqual(
            git_command.GitCommandError(
                git_stderr="couldn't find remote ref refs/heads/foo"
            ).suggestion,
            "Check if the provided ref exists in the remote.",
        )

        self.assertEqual(
            git_command.GitCommandError(
                git_stderr="'foobar' does not appear to be a git repository"
            ).suggestion,
            "Are you running this repo command outside of a repo workspace?",
        )
