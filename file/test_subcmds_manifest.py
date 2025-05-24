# Copyright (C) 2025 The Android Open Source Project
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

"""Unittests for the subcmds/manifest.py module."""

import json
from pathlib import Path
from unittest import mock

import manifest_xml
from subcmds import manifest


_EXAMPLE_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="test-remote" fetch="http://localhost" />
  <default remote="test-remote" revision="refs/heads/main" />
  <project name="repohooks" path="src/repohooks"/>
  <repo-hooks in-project="repohooks" enabled-list="a, b"/>
</manifest>
"""


def _get_cmd(repodir: Path) -> manifest.Manifest:
    """Instantiate a manifest command object to test."""
    manifests_git = repodir / "manifests.git"
    manifests_git.mkdir()
    (manifests_git / "config").write_text(
        """
[remote "origin"]
\turl = http://localhost/manifest
"""
    )
    client = manifest_xml.RepoClient(repodir=str(repodir))
    git_event_log = mock.MagicMock(ErrorEvent=mock.Mock(return_value=None))
    return manifest.Manifest(
        repodir=client.repodir,
        client=client,
        manifest=client.manifest,
        outer_client=client,
        outer_manifest=client.manifest,
        git_event_log=git_event_log,
    )


def test_output_format_xml_file(tmp_path):
    """Test writing XML to a file."""
    path = tmp_path / "manifest.xml"
    path.write_text(_EXAMPLE_MANIFEST)
    outpath = tmp_path / "output.xml"
    cmd = _get_cmd(tmp_path)
    opt, args = cmd.OptionParser.parse_args(["--output-file", str(outpath)])
    cmd.Execute(opt, args)
    # Normalize the output a bit as we don't exactly care.
    normalize = lambda data: "\n".join(
        x.strip() for x in data.splitlines() if x.strip()
    )
    assert (
        normalize(outpath.read_text())
        == """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
<remote name="test-remote" fetch="http://localhost"/>
<default remote="test-remote" revision="refs/heads/main"/>
<project name="repohooks" path="src/repohooks"/>
<repo-hooks in-project="repohooks" enabled-list="a b"/>
</manifest>"""
    )


def test_output_format_xml_stdout(tmp_path, capsys):
    """Test writing XML to stdout."""
    path = tmp_path / "manifest.xml"
    path.write_text(_EXAMPLE_MANIFEST)
    cmd = _get_cmd(tmp_path)
    opt, args = cmd.OptionParser.parse_args(["--format", "xml"])
    cmd.Execute(opt, args)
    # Normalize the output a bit as we don't exactly care.
    normalize = lambda data: "\n".join(
        x.strip() for x in data.splitlines() if x.strip()
    )
    stdout = capsys.readouterr().out
    assert (
        normalize(stdout)
        == """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
<remote name="test-remote" fetch="http://localhost"/>
<default remote="test-remote" revision="refs/heads/main"/>
<project name="repohooks" path="src/repohooks"/>
<repo-hooks in-project="repohooks" enabled-list="a b"/>
</manifest>"""
    )


def test_output_format_json(tmp_path, capsys):
    """Test writing JSON."""
    path = tmp_path / "manifest.xml"
    path.write_text(_EXAMPLE_MANIFEST)
    cmd = _get_cmd(tmp_path)
    opt, args = cmd.OptionParser.parse_args(["--format", "json"])
    cmd.Execute(opt, args)
    obj = json.loads(capsys.readouterr().out)
    assert obj == {
        "default": {"remote": "test-remote", "revision": "refs/heads/main"},
        "project": [{"name": "repohooks", "path": "src/repohooks"}],
        "remote": [{"fetch": "http://localhost", "name": "test-remote"}],
        "repo-hooks": {"enabled-list": "a b", "in-project": "repohooks"},
    }


def test_output_format_json_pretty(tmp_path, capsys):
    """Test writing pretty JSON."""
    path = tmp_path / "manifest.xml"
    path.write_text(_EXAMPLE_MANIFEST)
    cmd = _get_cmd(tmp_path)
    opt, args = cmd.OptionParser.parse_args(["--format", "json", "--pretty"])
    cmd.Execute(opt, args)
    stdout = capsys.readouterr().out
    assert (
        stdout
        == """\
{
  "default": {
    "remote": "test-remote",
    "revision": "refs/heads/main"
  },
  "project": [
    {
      "name": "repohooks",
      "path": "src/repohooks"
    }
  ],
  "remote": [
    {
      "fetch": "http://localhost",
      "name": "test-remote"
    }
  ],
  "repo-hooks": {
    "enabled-list": "a b",
    "in-project": "repohooks"
  }
}
"""
    )
