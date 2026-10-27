# Copyright (C) 2009 The Android Open Source Project
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

"""Unittests for the git_config.py module."""

import json
import os
from pathlib import Path
from typing import Any, Optional

import pytest
import utils_for_test

import error
import git_config


@pytest.fixture
def readonly_config() -> git_config.GitConfig:
    """Create a GitConfig object using the test.gitconfig fixture."""
    config_fixture = utils_for_test.FIXTURES_DIR / "test.gitconfig"
    return git_config.GitConfig(config_fixture)


def test_get_string_with_empty_config_values(
    readonly_config: git_config.GitConfig,
) -> None:
    """Test config entries with no value.

    [section]
        empty

    """
    val = readonly_config.GetString("section.empty")
    assert val is None


def test_get_string_with_true_value(
    readonly_config: git_config.GitConfig,
) -> None:
    """Test config entries with a string value.

    [section]
        nonempty = true

    """
    val = readonly_config.GetString("section.nonempty")
    assert val == "true"


def test_get_string_from_missing_file() -> None:
    """Test missing config file."""
    config_fixture = utils_for_test.FIXTURES_DIR / "not.present.gitconfig"
    config = git_config.GitConfig(config_fixture)
    val = config.GetString("empty")
    assert val is None


def test_get_boolean_undefined(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on key that doesn't exist."""
    assert readonly_config.GetBoolean("section.missing") is None


def test_get_boolean_invalid(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on invalid boolean value."""
    assert readonly_config.GetBoolean("section.boolinvalid") is None


def test_get_boolean_true(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on valid true boolean."""
    assert readonly_config.GetBoolean("section.booltrue") is True


def test_get_boolean_false(readonly_config: git_config.GitConfig) -> None:
    """Test GetBoolean on valid false boolean."""
    assert readonly_config.GetBoolean("section.boolfalse") is False


def test_get_int_undefined(readonly_config: git_config.GitConfig) -> None:
    """Test GetInt on key that doesn't exist."""
    assert readonly_config.GetInt("section.missing") is None


def test_get_int_invalid(readonly_config: git_config.GitConfig) -> None:
    """Test GetInt on invalid integer value."""
    assert readonly_config.GetInt("section.intinvalid") is None


@pytest.mark.parametrize(
    "key, expected",
    (
        ("inthex", 16),
        ("inthexk", 16384),
        ("int", 10),
        ("intk", 10240),
        ("intm", 10485760),
        ("intg", 10737418240),
    ),
)
def test_get_int_valid(
    readonly_config: git_config.GitConfig, key: str, expected: int
) -> None:
    """Test GetInt on valid integers."""
    assert readonly_config.GetInt(f"section.{key}") == expected


@pytest.fixture
def rw_config_file(tmp_path: Path) -> Path:
    """Return a path to a temporary config file."""
    return tmp_path / "config"


def test_set_string(rw_config_file: Path) -> None:
    """Test SetString behavior."""
    config = git_config.GitConfig(str(rw_config_file))

    # Set a value.
    assert config.GetString("foo.bar") is None
    config.SetString("foo.bar", "val")
    assert config.GetString("foo.bar") == "val"

    # Make sure the value was actually written out.
    config2 = git_config.GitConfig(str(rw_config_file))
    assert config2.GetString("foo.bar") == "val"

    # Update the value.
    config.SetString("foo.bar", "valll")
    assert config.GetString("foo.bar") == "valll"
    config3 = git_config.GitConfig(str(rw_config_file))
    assert config3.GetString("foo.bar") == "valll"

    # Delete the value.
    config.SetString("foo.bar", None)
    assert config.GetString("foo.bar") is None
    config4 = git_config.GitConfig(str(rw_config_file))
    assert config4.GetString("foo.bar") is None


def test_set_boolean(rw_config_file: Path) -> None:
    """Test SetBoolean behavior."""
    config = git_config.GitConfig(str(rw_config_file))

    # Set a true value.
    assert config.GetBoolean("foo.bar") is None
    for val in (True, 1):
        config.SetBoolean("foo.bar", val)
        assert config.GetBoolean("foo.bar") is True

    # Make sure the value was actually written out.
    config2 = git_config.GitConfig(str(rw_config_file))
    assert config2.GetBoolean("foo.bar") is True
    assert config2.GetString("foo.bar") == "true"

    # Set a false value.
    for val in (False, 0):
        config.SetBoolean("foo.bar", val)
        assert config.GetBoolean("foo.bar") is False

    # Make sure the value was actually written out.
    config3 = git_config.GitConfig(str(rw_config_file))
    assert config3.GetBoolean("foo.bar") is False
    assert config3.GetString("foo.bar") == "false"

    # Delete the value.
    config.SetBoolean("foo.bar", None)
    assert config.GetBoolean("foo.bar") is None
    config4 = git_config.GitConfig(str(rw_config_file))
    assert config4.GetBoolean("foo.bar") is None


def test_set_int(rw_config_file: Path) -> None:
    """Test SetInt behavior."""
    config = git_config.GitConfig(str(rw_config_file))

    # Set a value.
    assert config.GetInt("foo.bar") is None
    config.SetInt("foo.bar", 10)
    assert config.GetInt("foo.bar") == 10

    # Make sure the value was actually written out.
    config2 = git_config.GitConfig(str(rw_config_file))
    assert config2.GetInt("foo.bar") == 10
    assert config2.GetString("foo.bar") == "10"

    # Update the value.
    config.SetInt("foo.bar", 20)
    assert config.GetInt("foo.bar") == 20
    config3 = git_config.GitConfig(str(rw_config_file))
    assert config3.GetInt("foo.bar") == 20

    # Delete the value.
    config.SetInt("foo.bar", None)
    assert config.GetInt("foo.bar") is None
    config4 = git_config.GitConfig(str(rw_config_file))
    assert config4.GetInt("foo.bar") is None


def test_get_sync_analysis_state_data(rw_config_file: Path) -> None:
    """Test config entries with a sync state analysis data."""
    config = git_config.GitConfig(str(rw_config_file))
    superproject_logging_data: dict[str, Any] = {"test": False}

    class Options:
        """Container for testing."""

    options = Options()
    options.verbose = "true"
    options.mp_update = "false"

    TESTS = (
        ("superproject.test", "false"),
        ("options.verbose", "true"),
        ("options.mpupdate", "false"),
        ("main.version", "1"),
    )
    config.UpdateSyncAnalysisState(options, superproject_logging_data)
    sync_data = config.GetSyncAnalysisStateData()
    for key, value in TESTS:
        assert sync_data[f"{git_config.SYNC_STATE_PREFIX}{key}"] == value
    assert sync_data[f"{git_config.SYNC_STATE_PREFIX}main.synctime"]


def test_remote_save_with_push_url_without_projectname(
    rw_config_file: Path,
) -> None:
    """Test saving a remote pushUrl when projectname is unset."""
    config = git_config.GitConfig(str(rw_config_file))
    remote = config.GetRemote("origin")
    remote.url = "https://example.com/repo"
    remote.pushUrl = "ssh://example.com"
    remote.projectname = None

    remote.Save()

    written_config = git_config.GitConfig(str(rw_config_file))
    assert (
        written_config.GetString("remote.origin.pushurl") == "ssh://example.com"
    )


@pytest.mark.parametrize(
    "rev, expected",
    (
        ("a" * 40, True),
        ("0" * 40, True),
        ("f" * 40, True),
        ("a" * 64, True),
        ("0" * 64, True),
        ("f" * 64, True),
        ("a" * 39, False),
        ("a" * 41, False),
        ("a" * 63, False),
        ("a" * 65, False),
        ("g" * 40, False),
        ("g" * 64, False),
        ("refs/heads/master", False),
        ("refs/tags/v1.0", False),
    ),
)
def test_is_id(rev: str, expected: bool) -> None:
    """Test IsId identifies both SHA-1 and SHA-256 hashes."""
    assert git_config.IsId(rev) == expected


def test_repo_config_for_user_is_not_shared_with_git_config(
    monkeypatch: pytest.MonkeyPatch, tmp_home_dir: Path
) -> None:
    """RepoConfig.ForUser() must not reuse GitConfig.ForUser()'s cache."""
    monkeypatch.setattr(git_config.GitConfig, "_ForUser", None)
    monkeypatch.setattr(git_config.RepoConfig, "_ForUser", None)
    monkeypatch.delenv("REPO_CONFIG_DIR", raising=False)

    # Populate the GitConfig cache first, as manifest loading does.
    git_cfg = git_config.GitConfig.ForUser()
    repo_cfg = git_config.RepoConfig.ForUser()

    assert repo_cfg is not git_cfg
    assert git_cfg.file == str(tmp_home_dir / ".gitconfig")
    assert repo_cfg.file == str(tmp_home_dir / ".repoconfig" / "config")
    # And the RepoConfig instance is cached on its own class.
    assert git_config.RepoConfig.ForUser() is repo_cfg
    assert git_config.GitConfig.ForUser() is git_cfg


@pytest.mark.parametrize(
    "value, expected",
    (
        ("true", True),
        ("True", True),
        ("yes", True),
        ("on", True),
        ("1", True),
        (" true ", True),
        ("false", False),
        ("No", False),
        ("off", False),
        ("0", False),
        ("oops", None),
        ("2", None),
        ("", None),
    ),
)
def test_parse_boolean(value: str, expected: Optional[bool]) -> None:
    """Test ParseBoolean accepts the spellings `git config --type=bool` does."""
    assert git_config.ParseBoolean(value) is expected


@pytest.mark.parametrize(
    "value, expected",
    (
        ("10", 10),
        ("-7", -7),
        ("10k", 10 * 1024),
        ("10M", 10 * 1024 * 1024),
        ("10g", 10 * 1024 * 1024 * 1024),
        ("0x10", 16),
        ("0x10k", 16 * 1024),
        (" 10 ", 10),
        ("oops", None),
        ("1x", None),
        ("", None),
    ),
)
def test_parse_int(value: str, expected: Optional[int]) -> None:
    """Test ParseInt accepts the syntax `git config --type=int` does."""
    assert git_config.ParseInt(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    (("on", True), ("off", False), ("1", True), ("0", False)),
)
def test_get_boolean_git_spellings(
    tmp_path: Path, value: str, expected: bool
) -> None:
    """Test GetBoolean accepts on/off/1/0 like git does."""
    config_file = tmp_path / "config"
    config_file.write_text(f"[section]\n\tkey = {value}\n")
    config = git_config.GitConfig(config_file)
    assert config.GetBoolean("section.key") is expected


def test_set_string_updates_json_and_section_caches(
    rw_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test SetString keeps .repo_config.json and _sections coherent."""
    config = git_config.GitConfig(str(rw_config_file))
    assert not config.HasSection("remote", "origin")

    config.SetString("remote.origin.url", "https://example.com/repo")
    assert config.HasSection("remote", "origin")

    json_file = rw_config_file.parent / ".repo_config.json"
    raw = json.loads(json_file.read_text(encoding="utf-8"))
    assert git_config._JSON_META_KEY in raw
    raw.pop(git_config._JSON_META_KEY)
    assert raw == {"remote.origin.url": ["https://example.com/repo"]}

    reader = git_config.GitConfig(str(rw_config_file))

    def fail_read_git() -> None:
        raise AssertionError("Expected _ReadJson cache hit without git config")

    monkeypatch.setattr(reader, "_ReadGit", fail_read_git)
    assert reader.GetString("remote.origin.url") == "https://example.com/repo"
    assert git_config._JSON_META_KEY not in reader.DumpConfigDict()


def test_reload_refreshes_external_edits(rw_config_file: Path) -> None:
    """Test Reload() discards stale JSON cache and reloads external edits."""
    config = git_config.GitConfig(str(rw_config_file))
    config.SetString("abfs.initialized", "false")
    assert config.GetBoolean("abfs.initialized") is False

    rw_config_file.write_text(
        "[abfs]\n\tinitialized = true\n", encoding="utf-8"
    )
    config.Reload()

    assert config.GetBoolean("abfs.initialized") is True
    json_file = rw_config_file.parent / ".repo_config.json"
    raw = json.loads(json_file.read_text(encoding="utf-8"))
    raw.pop(git_config._JSON_META_KEY, None)
    assert raw == {"abfs.initialized": ["true"]}


def test_same_tick_external_edit_invalidates_json_cache(
    rw_config_file: Path,
) -> None:
    """External edit with identical mtime_ns and size invalidates JSON."""
    config = git_config.GitConfig(str(rw_config_file))
    config.SetString("foo.bar", "val1")

    json_file = rw_config_file.parent / ".repo_config.json"
    json_stat = os.stat(json_file)

    # Rewrite with identical byte length and force identical mtime_ns.
    updated = rw_config_file.read_text(encoding="utf-8").replace("val1", "val2")
    rw_config_file.write_text(updated, encoding="utf-8")
    os.utime(rw_config_file, ns=(json_stat.st_atime_ns, json_stat.st_mtime_ns))

    reader = git_config.GitConfig(str(rw_config_file))
    assert reader.GetString("foo.bar") == "val2"


def test_clear_cache_and_set_string_refresh_remotes_and_branches(
    rw_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ClearCache, Reload, SetString, and Branch.Save keep caches coherent."""
    config = git_config.GitConfig(str(rw_config_file))
    remote = config.GetRemote("origin")
    remote.url = "https://old.example.com/repo"
    remote.ResetFetch()
    remote.Save()

    branch = config.GetBranch("main")
    branch.remote = remote
    branch.merge = "refs/heads/main"
    branch.Save()

    assert config.HasSection("branch", "main")
    assert config.GetString("branch.main.remote") == "origin"
    assert config.GetString("branch.main.merge") == "refs/heads/main"

    # Subsequent SetString must not clobber branch.* keys in .repo_config.json.
    config.SetString("custom.flag", "1")
    reader = git_config.GitConfig(str(rw_config_file))
    monkeypatch.setattr(
        reader,
        "_ReadGit",
        lambda: (_ for _ in ()).throw(AssertionError("expected JSON hit")),
    )
    assert reader.GetString("branch.main.remote") == "origin"
    assert reader.GetString("branch.main.merge") == "refs/heads/main"

    # Direct SetString on remote.* invalidates cached Remote objects.
    config.SetString(
        "remote.origin.fetch", "+refs/heads/dev:refs/remotes/origin/dev"
    )
    assert (
        config.GetRemote("origin").ToLocal("dev") == "refs/remotes/origin/dev"
    )

    # External edit + Reload() refreshes both GetRemote() and GetBranch().
    rw_config_file.write_text(
        '[remote "origin"]\n'
        "\turl = https://new.example.com/repo\n"
        "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
        '[branch "main"]\n'
        "\tremote = origin\n"
        "\tmerge = refs/heads/next\n",
        encoding="utf-8",
    )
    config.Reload()
    assert config.GetRemote("origin").url == "https://new.example.com/repo"
    assert config.GetBranch("main").merge == "refs/heads/next"


def test_set_string_with_include_invalidates_instead_of_corrupting(
    tmp_path: Path,
) -> None:
    """SetString with [include] avoids freezing or dropping included values."""
    inc_file = tmp_path / "extra.gitconfig"
    inc_file.write_text("[inc]\n\tkey = v1\n", encoding="utf-8")

    cfg_file = tmp_path / "config"
    config = git_config.GitConfig(str(cfg_file))
    config.SetString("include.path", str(inc_file))
    assert config.GetString("inc.key") == "v1"

    config.SetString("local.only", "yes")
    json_file = tmp_path / ".repo_config.json"
    assert not json_file.exists()

    inc_file.write_text("[inc]\n\tkey = v2\n", encoding="utf-8")
    assert config.GetString("inc.key") == "v2"
    assert config.GetString("local.only") == "yes"

    # Unsetting an included-only key does not fail with exit code 5 or hide it.
    config.SetString("inc.key", None)
    assert config.GetString("inc.key") == "v2"


def test_set_string_failure_preserves_cache(
    rw_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed _do() must not leave mutated values in _cache."""
    config = git_config.GitConfig(str(rw_config_file))
    config.SetString("foo.bar", "good")

    def fail_do(*_args: Any, **_kwargs: Any) -> str:
        raise error.GitError("lock contention")

    monkeypatch.setattr(config, "_do", fail_do)
    with pytest.raises(error.GitError):
        config.SetString("foo.bar", "bad")
    assert config.GetString("foo.bar") == "good"

    with pytest.raises(error.GitError):
        config.SetString("foo.bar", None)
    assert config.GetString("foo.bar") == "good"


def test_set_string_after_external_edit_preserves_external_keys(
    rw_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Warm SetString reloads external edits instead of overwriting JSON."""
    config = git_config.GitConfig(str(rw_config_file))
    config.SetString("init.key", "v0")
    assert config._cache_dict is not None

    # External edit adds other.key while config._cache_dict is warm in memory.
    rw_config_file.write_text(
        "[init]\n\tkey = v0\n[other]\n\tkey = ext1\n", encoding="utf-8"
    )
    config.SetString("user.name", "Alice")

    assert config.GetString("other.key") == "ext1"
    assert config.GetString("user.name") == "Alice"

    reader = git_config.GitConfig(str(rw_config_file))
    monkeypatch.setattr(
        reader,
        "_ReadGit",
        lambda: (_ for _ in ()).throw(AssertionError("expected JSON hit")),
    )
    assert reader.GetString("other.key") == "ext1"
    assert reader.GetString("user.name") == "Alice"

    # Same-mtime_ns and same-size external edit while warm is also detected.
    prev_stat = os.stat(rw_config_file)
    same_len = rw_config_file.read_text(encoding="utf-8").replace(
        "ext1", "ext2"
    )
    rw_config_file.write_text(same_len, encoding="utf-8")
    os.utime(rw_config_file, ns=(prev_stat.st_atime_ns, prev_stat.st_mtime_ns))

    config.SetString("user.email", "alice@example.com")
    assert config.GetString("other.key") == "ext2"
    assert config.GetString("user.email") == "alice@example.com"

    reader2 = git_config.GitConfig(str(rw_config_file))
    monkeypatch.setattr(
        reader2,
        "_ReadGit",
        lambda: (_ for _ in ()).throw(AssertionError("expected JSON hit")),
    )
    assert reader2.GetString("other.key") == "ext2"
    assert reader2.GetString("user.name") == "Alice"
    assert reader2.GetString("user.email") == "alice@example.com"
