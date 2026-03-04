import unittest
from unittest import mock

import main


class RepoTests(unittest.TestCase):
    @mock.patch("main.time.sleep")
    @mock.patch("main.sys.stderr")
    def test_autocorrect_positive(self, mock_stderr, mock_sleep):
        """Test autocorrect with positive delay."""
        repo = main._Repo("repodir")

        mock_cmd = mock.MagicMock()
        repo.commands = {"start": mock_cmd}

        gopts = mock.MagicMock()
        gopts.submanifest_path = ""
        argv = []
        git_trace2_event_log = mock.MagicMock()

        mock_client = mock.MagicMock()
        mock_client.globalConfig.GetString.return_value = "10"

        with mock.patch("main.RepoClient", return_value=mock_client):
            with mock.patch("main.SetDefaultColoring"):
                repo._RunLong("tart", gopts, argv, git_trace2_event_log)

        mock_client.globalConfig.GetString.assert_called_with(
            "help.autocorrect"
        )
        mock_sleep.assert_called_with(1.0)
        mock_cmd.assert_called()

    @mock.patch("main.sys.stderr")
    def test_autocorrect_negative(self, mock_stderr):
        """Test autocorrect with negative delay."""
        repo = main._Repo("repodir")
        mock_cmd = mock.MagicMock()
        repo.commands = {"start": mock_cmd}
        gopts = mock.MagicMock()
        gopts.submanifest_path = ""
        argv = []
        git_trace2_event_log = mock.MagicMock()

        mock_client = mock.MagicMock()
        mock_client.globalConfig.GetString.return_value = "-1"

        with mock.patch("main.RepoClient", return_value=mock_client):
            with mock.patch("main.SetDefaultColoring"):
                repo._RunLong("tart", gopts, argv, git_trace2_event_log)

        mock_cmd.assert_called()

    @mock.patch("main.sys.stderr")
    def test_autocorrect_zero(self, mock_stderr):
        """Test autocorrect with zero delay (suggestions only)."""
        repo = main._Repo("repodir")
        mock_cmd = mock.MagicMock()
        repo.commands = {"start": mock_cmd}
        gopts = mock.MagicMock()
        gopts.submanifest_path = ""
        argv = []
        git_trace2_event_log = mock.MagicMock()

        mock_client = mock.MagicMock()
        mock_client.globalConfig.GetString.return_value = "0"

        with mock.patch("main.RepoClient", return_value=mock_client):
            with mock.patch("main.SetDefaultColoring"):
                res = repo._RunLong("tart", gopts, argv, git_trace2_event_log)

        self.assertEqual(res, 1)
        mock_cmd.assert_not_called()

    @mock.patch("main.sys.stderr")
    @mock.patch("builtins.input", return_value="y")
    def test_autocorrect_prompt_yes(self, mock_input, mock_stderr):
        """Test autocorrect with prompt and user answers yes."""
        repo = main._Repo("repodir")
        mock_cmd = mock.MagicMock()
        repo.commands = {"start": mock_cmd}
        gopts = mock.MagicMock()
        gopts.submanifest_path = ""
        argv = []
        git_trace2_event_log = mock.MagicMock()

        mock_client = mock.MagicMock()
        mock_client.globalConfig.GetString.return_value = "prompt"

        with mock.patch("main.RepoClient", return_value=mock_client):
            with mock.patch("main.SetDefaultColoring"):
                repo._RunLong("tart", gopts, argv, git_trace2_event_log)

        mock_cmd.assert_called()

    @mock.patch("main.sys.stderr")
    @mock.patch("builtins.input", return_value="n")
    def test_autocorrect_prompt_no(self, mock_input, mock_stderr):
        """Test autocorrect with prompt and user answers no."""
        repo = main._Repo("repodir")
        mock_cmd = mock.MagicMock()
        repo.commands = {"start": mock_cmd}
        gopts = mock.MagicMock()
        gopts.submanifest_path = ""
        argv = []
        git_trace2_event_log = mock.MagicMock()

        mock_client = mock.MagicMock()
        mock_client.globalConfig.GetString.return_value = "prompt"

        with mock.patch("main.RepoClient", return_value=mock_client):
            with mock.patch("main.SetDefaultColoring"):
                res = repo._RunLong("tart", gopts, argv, git_trace2_event_log)

        self.assertEqual(res, 1)
        mock_cmd.assert_not_called()
