"""Unit tests for relay/config_local.py — repo-local `.relay.toml` loading.

Covers the branches the suite previously missed: parent-directory traversal in
``find_repo_root``, the no-repo ``None`` paths, unreadable/malformed local
files, and every arm of the security allowlist (non-dict sections, non-list
``ignore.paths``, disallowed ``[ai]`` keys, invalid ``[team.protected]``).
"""
import pytest

from relay import config_local
from relay.config_local import (
    _load_local_ignore,
    _load_local_raw,
    _load_local_team_protected,
    find_repo_root,
    local_config_file_path,
)


@pytest.fixture(autouse=True)
def clear_local_state(monkeypatch):
    """Start each test with an empty local-file cache and no env override."""
    config_local._LOCAL_CACHE.clear()
    monkeypatch.delenv("RELAY_LOCAL_CONFIG", raising=False)


def _write_local_config(tmp_path, body: str):
    p = tmp_path / ".relay.toml"
    p.write_text(body, encoding="utf-8")
    return p


class TestFindRepoRoot:
    def test_finds_git_in_parent_directories(self, tmp_path):
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        assert find_repo_root(start=nested) == tmp_path

    def test_returns_none_when_no_git_anywhere(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        assert find_repo_root(start=nested) is None


class TestLocalConfigFilePath:
    def test_returns_none_outside_any_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert local_config_file_path() is None

    def test_explicit_path_to_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(tmp_path / "nope.toml"))
        assert local_config_file_path() is None

    def test_explicit_path_to_existing_file(self, tmp_path, monkeypatch):
        cfg = _write_local_config(tmp_path, '[relay]\nprovider = "openai"\n')
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert local_config_file_path() == cfg


class TestLoadLocalRawErrors:
    def test_unreadable_file_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(tmp_path))
        assert _load_local_raw() == {}

    def test_file_vanishing_before_read_returns_empty_dict(
        self, tmp_path, monkeypatch
    ):
        ghost = tmp_path / "ghost.toml"
        monkeypatch.setattr(
            config_local, "local_config_file_path", lambda: ghost
        )
        assert _load_local_raw() == {}

    def test_malformed_toml_warns_and_returns_empty_dict(
        self, tmp_path, monkeypatch, capsys
    ):
        cfg = _write_local_config(tmp_path, "[[[broken\n")
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_raw() == {}
        assert "malformed repo config" in capsys.readouterr().err

    def test_malformed_result_is_cached_as_empty(self, tmp_path, monkeypatch):
        cfg = _write_local_config(tmp_path, "[[[broken\n")
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_raw() == {}
        assert _load_local_raw() == {}


class TestAllowlistBranches:
    def test_top_level_scalar_is_ignored(self, tmp_path, monkeypatch):
        cfg = _write_local_config(
            tmp_path, 'title = "hello"\n[relay]\nprovider = "openai"\n'
        )
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_raw() == {"relay": {"provider": "openai"}}

    def test_relay_ignore_with_non_list_paths_adds_nothing(
        self, tmp_path, monkeypatch
    ):
        cfg = _write_local_config(
            tmp_path, '[relay]\nignore = {paths = "nope"}\n'
        )
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_raw() == {"relay": {}}

    def test_disallowed_ai_key_is_dropped_with_warning(
        self, tmp_path, monkeypatch, capsys
    ):
        cfg = _write_local_config(
            tmp_path,
            '[ai]\nopenai_base_url = "https://evil.example/v1"\n'
            'openai_model = "gpt-4o"\n',
        )
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        raw = _load_local_raw()
        assert raw["ai"] == {"openai_model": "gpt-4o"}
        assert "security-restricted key" in capsys.readouterr().err

    def test_team_protected_as_scalar_yields_no_team(self, tmp_path, monkeypatch):
        cfg = _write_local_config(tmp_path, '[team]\nprotected = "nope"\n')
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_team_protected() == {}

    def test_team_protected_with_non_list_branches_yields_empty(
        self, tmp_path, monkeypatch
    ):
        cfg = _write_local_config(
            tmp_path, '[team.protected]\nbranches = "production"\n'
        )
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_team_protected() == {}

    def test_team_protected_with_branch_list(self, tmp_path, monkeypatch):
        cfg = _write_local_config(
            tmp_path, '[team.protected]\nbranches = ["production"]\n'
        )
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_team_protected() == {"branches": ["production"]}

    def test_top_level_ignore_section_with_paths(self, tmp_path, monkeypatch):
        cfg = _write_local_config(tmp_path, '[ignore]\npaths = ["*.log"]\n')
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_ignore() == {"paths": ["*.log"]}

    def test_top_level_ignore_section_without_list_is_dropped(
        self, tmp_path, monkeypatch
    ):
        cfg = _write_local_config(tmp_path, '[ignore]\npaths = "*.log"\n')
        monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(cfg))
        assert _load_local_raw() == {}
