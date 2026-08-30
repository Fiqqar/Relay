"""Tests for multi-repo runs — --repo flag + [repos] config."""
import textwrap
from unittest import mock

import pytest

from relay import config
from relay.cli import build_parser


@pytest.fixture(autouse=True)
def clear(monkeypatch):
    config._RAW_CACHE.clear()
    for k in ("RELAY_REPOS", "RELAY_CONFIG", "XDG_CONFIG_HOME", "APPDATA"):
        monkeypatch.delenv(k, raising=False)


def _write(monkeypatch, tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setenv("RELAY_CONFIG", str(p))


# ---- config ---------------------------------------------------------------

def test_repos_defaults_empty():
    assert config.repos() == []


def test_repos_env_comma_split(monkeypatch):
    monkeypatch.setenv("RELAY_REPOS", "a/b, c/d , e")
    assert config.repos() == ["a/b", "c/d", "e"]


def test_repos_env_beats_file(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [repos]
        paths = ["from-file"]
    """)
    monkeypatch.setenv("RELAY_REPOS", "from-env")
    assert config.repos() == ["from-env"]


def test_repos_file_paths(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [repos]
        paths = ["worktree/a", "worktree/b"]
    """)
    assert config.repos() == ["worktree/a", "worktree/b"]


def test_repos_file_repos_key_compat(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [repos]
        repos = ["a", "b"]
    """)
    assert config.repos() == ["a", "b"]


def test_repos_empty_file_falls_back(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [repos]
        paths = []
    """)
    assert config.repos() == []


# ---- cli parsing ----------------------------------------------------------

def test_cli_repo_single():
    args = build_parser().parse_args(["--repo", "a/b"])
    assert args.repo == ["a/b"]


def test_cli_repo_repeatable():
    args = build_parser().parse_args(["--repo", "a", "--repo", "b"])
    assert args.repo == ["a", "b"]


def test_cli_repo_defaults_none():
    args = build_parser().parse_args([])
    assert args.repo is None


def test_cli_repo_with_solo():
    args = build_parser().parse_args(["--repo", "a", "--solo"])
    assert args.repo == ["a"]
    assert args.solo is True


# ---- orchestrator loop ----------------------------------------------------

class StubAI:
    def generate(self, diff, stat, branch):
        return "feat: stub"


def _make_git():
    g = mock.Mock()
    g.is_repo.return_value = True
    g.has_changes.return_value = True
    g.has_remote.return_value = True
    g.staged_diff.return_value = "diff --git a/a.py b/a.py\n+hi\n"
    g.staged_stat.return_value = " a.py | 1 +\n"
    g.head_diff.return_value = "diff --git a/a.py b/a.py\n+hi\n"
    g.head_stat.return_value = " a.py | 1 +\n"
    g.current_branch.return_value = "main"
    g.staged_diff_binary_only.return_value = False
    g.head_diff_binary_only.return_value = False
    g.write_tree.return_value = "abc"
    return g


def test_main_multirepo_loops(monkeypatch, tmp_path):
    from relay.cli import main

    # Create two fake repo dirs (just need paths, GitManager mocked)
    monkeypatch.setenv("RELAY_REPOS", "")
    config._RAW_CACHE.clear()
    with mock.patch("relay.cli.GitManager") as MockGM:
        with mock.patch("relay.cli.build_provider", return_value=StubAI()):
            mock_git = _make_git()
            MockGM.return_value = mock_git
            # Also need Orchestrator mock to avoid real git
            with mock.patch("relay.cli.Orchestrator") as MockOrch:
                inst = mock.Mock()
                inst.run.return_value = 0
                MockOrch.return_value = inst
                code = main(["--repo", "a", "--repo", "b", "--yes", "--no-push"])
                assert code == 0
                # Orchestrator created twice (once per repo)
                assert MockOrch.call_count == 2
                # GitManager created with cwd per repo
                assert MockGM.call_count == 2
                # Check that first call had cwd "a"
                assert MockGM.call_args_list[0][1].get("cwd") == "a" or "a" in str(MockGM.call_args_list[0])
                assert MockGM.call_args_list[1][1].get("cwd") == "b" or "b" in str(MockGM.call_args_list[1])


def test_main_multirepo_from_config(monkeypatch, tmp_path):
    from relay.cli import main

    _write(monkeypatch, tmp_path, """
        [repos]
        paths = ["r1", "r2"]
    """)
    with mock.patch("relay.cli.GitManager") as MockGM:
        with mock.patch("relay.cli.build_provider", return_value=StubAI()):
            mock_git = _make_git()
            MockGM.return_value = mock_git
            with mock.patch("relay.cli.Orchestrator") as MockOrch:
                inst = mock.Mock()
                inst.run.return_value = 0
                MockOrch.return_value = inst
                code = main(["--yes", "--no-push"])
                assert code == 0
                assert MockOrch.call_count == 2


def test_main_multirepo_one_failure_returns_1(monkeypatch):
    from relay.cli import main

    with mock.patch("relay.cli.GitManager") as MockGM:
        with mock.patch("relay.cli.build_provider", return_value=StubAI()):
            MockGM.return_value = _make_git()
            with mock.patch("relay.cli.Orchestrator") as MockOrch:
                inst = mock.Mock()
                inst.run.side_effect = [0, 1]
                MockOrch.return_value = inst
                code = main(["--repo", "a", "--repo", "b", "--yes", "--no-push"])
                assert code == 1
