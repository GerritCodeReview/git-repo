# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the ssh.py module."""

import multiprocessing
import subprocess
from typing import Tuple
from unittest import mock

import pytest

import ssh


@pytest.fixture(autouse=True)
def clear_ssh_version_cache() -> None:
    """Clear the ssh version cache before each test."""
    ssh.version.cache_clear()


@pytest.mark.parametrize(
    "input_str, expected",
    (
        ("Unknown\n", ()),
        ("OpenSSH_1.0\n", (1, 0)),
        (
            "OpenSSH_6.6.1p1 Ubuntu-2ubuntu2.13, OpenSSL 1.0.1f 6 Jan 2014\n",
            (6, 6, 1),
        ),
        (
            "OpenSSH_7.6p1 Ubuntu-4ubuntu0.3, OpenSSL 1.0.2n  7 Dec 2017\n",
            (7, 6),
        ),
        ("OpenSSH_9.0p1, LibreSSL 3.3.6\n", (9, 0)),
    ),
)
def test_parse_ssh_version(input_str: str, expected: Tuple[int, ...]) -> None:
    """Check _parse_ssh_version() handling."""
    assert ssh._parse_ssh_version(input_str) == expected


def test_version() -> None:
    """Check version() handling."""
    with mock.patch("ssh._run_ssh_version", return_value="OpenSSH_1.2\n"):
        assert ssh.version() == (1, 2)


def test_context_manager_empty() -> None:
    """Verify context manager with no clients works correctly."""
    with multiprocessing.Manager() as manager:
        with ssh.ProxyManager(manager):
            pass


def test_context_manager_child_cleanup() -> None:
    """Verify orphaned clients & masters get cleaned up."""
    with multiprocessing.Manager() as manager:
        with mock.patch("ssh.version", return_value=(1, 2)):
            with ssh.ProxyManager(manager) as ssh_proxy:
                client = subprocess.Popen(["sleep", "964853320"])
                ssh_proxy.add_client(client)
                master = subprocess.Popen(["sleep", "964853321"])
                ssh_proxy.add_master(master)
    # If the process still exists, these will throw timeout errors.
    client.wait(0)
    master.wait(0)


def test_ssh_sock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check sock() function."""
    with multiprocessing.Manager() as manager:
        proxy = ssh.ProxyManager(manager)
        monkeypatch.setattr(
            "tempfile.mkdtemp", lambda *args, **kwargs: "/tmp/foo"
        )

        # Old ssh version uses port.
        with mock.patch("ssh.version", return_value=(6, 6)):
            with proxy as ssh_proxy:
                assert ssh_proxy.sock().endswith("%p")

        proxy._sock_path = None
        # New ssh version uses hash.
        with mock.patch("ssh.version", return_value=(6, 7)):
            with proxy as ssh_proxy:
                assert ssh_proxy.sock().endswith("%C")
        proxy._sock_path = None
