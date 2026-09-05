"""Tests for custom hooks — [hooks.pre_commit] / [hooks.post_push]."""
import textwrap
from unittest import mock

import pytest

from relay import config
from relay.errors import GitError
from relay.hooks import run_hook


@pytest.fixture(autouse=True)
def clear(monkeypatch):
    config._RAW_CACHE.clear()
    for k in ("RELAY_CONFIG", "XDG_CONFIG_HOME", "APPDATA"):
        monkeypatch.delenv(k, raising=False)


def _write(monkeypatch, tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setenv("RELAY_CONFIG", str(p))


# ---- config parsing -------------------------------------------------------

def test_no_hooks_returns_none():
    assert config.hook_pre_commit() is None
    assert config.hook_post_push() is None


def test_pre_commit_command_list(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = ["./scripts/check.sh", "--strict"]
    """)
    assert config.hook_pre_commit() == ["./scripts/check.sh", "--strict"]
    assert config.hook_post_push() is None


def test_post_push_command_list(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.post_push]
        command = ["echo", "pushed"]
    """)
    assert config.hook_post_push() == ["echo", "pushed"]


def test_hooks_both_tables(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = ["echo", "pre"]

        [hooks.post_push]
        command = ["echo", "post"]
    """)
    assert config.hook_pre_commit() == ["echo", "pre"]
    assert config.hook_post_push() == ["echo", "post"]


def test_hooks_direct_list_compat(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks]
        pre_commit = ["echo", "hi"]
    """)
    assert config.hook_pre_commit() == ["echo", "hi"]


def test_hooks_single_string_command_splits_to_argv(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = "echo hi"
    """)
    assert config.hook_pre_commit() == ["echo", "hi"]


def test_hooks_single_string_without_args_is_single_element(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = "./scripts/check.sh"
    """)
    assert config.hook_pre_commit() == ["./scripts/check.sh"]


def test_hooks_single_string_keeps_quoted_path_together(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = '"/opt/my tools/check.sh" --strict'
    """)
    assert config.hook_pre_commit() == ["/opt/my tools/check.sh", "--strict"]


def test_hooks_single_string_unbalanced_quotes_returns_none(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = "echo 'hi"
    """)
    assert config.hook_pre_commit() is None


def test_hooks_single_string_blank_returns_none(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = "   "
    """)
    assert config.hook_pre_commit() is None


def test_hooks_empty_list_returns_none(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = []
    """)
    assert config.hook_pre_commit() is None


def test_hooks_invalid_shape_returns_none(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [hooks.pre_commit]
        command = 123
    """)
    assert config.hook_pre_commit() is None


# ---- run_hook -------------------------------------------------------------

def test_run_hook_success(monkeypatch):
    with mock.patch("subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        run_hook(["echo", "hi"], verbose=False)
        m.assert_called_once()
        args, kwargs = m.call_args
        assert kwargs["shell"] is False
        assert args[0] == ["echo", "hi"]


def test_run_hook_failure_raises_giterr(monkeypatch):
    with mock.patch("subprocess.run") as m:
        m.return_value = mock.Mock(returncode=1, stdout="", stderr="oops")
        with pytest.raises(GitError, match="hook failed"):
            run_hook(["false"], verbose=False)


def test_run_hook_not_found_raises(monkeypatch):
    with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(GitError, match="hook not found"):
            run_hook(["nope"], verbose=False)


def test_run_hook_timeout_raises(monkeypatch):
    import subprocess

    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60)):
        with pytest.raises(GitError, match="hook timed out"):
            run_hook(["sleep"], verbose=False)


def test_run_hook_verbose_prints(capsys):
    with mock.patch("subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        run_hook(["echo", "hi"], verbose=True)
        assert "echo hi" in capsys.readouterr().out


def test_run_hook_argv_as_list_no_shell_injection(monkeypatch):
    """A hook argv containing shell metacharacters must stay as literal args."""
    with mock.patch("subprocess.run") as m:
        m.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        run_hook(["echo", "hi; rm -rf /"], verbose=False)
        assert m.call_args[0][0] == ["echo", "hi; rm -rf /"]
        assert m.call_args[1]["shell"] is False


# ---- orchestrator integration ---------------------------------------------

class StubAI:
    def __init__(self):
        self.calls = []

    def generate(self, diff, stat, branch):
        self.calls.append((diff, stat, branch))
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


def test_orchestrator_runs_pre_commit_before_commit(monkeypatch):
    from relay.orchestrator import Orchestrator

    _write(monkeypatch, mock.MagicMock(), "")  # ensure no previous file influences? we set env later
    # Use monkeypatch to mock hook to avoid real subprocess
    with mock.patch("relay.orchestrator.get_pre_commit_hook", return_value=["echo", "pre"]):
        with mock.patch("relay.orchestrator.run_hook") as mh:
            ai = StubAI()
            git = _make_git()
            orch = Orchestrator(git=git, provider=ai, yes=True, no_push=True)
            orch.run()
            mh.assert_called_once_with(["echo", "pre"], verbose=False)
            git.commit.assert_called_once()


def test_orchestrator_pre_commit_failure_aborts(monkeypatch):
    from relay.orchestrator import Orchestrator

    with mock.patch("relay.orchestrator.get_pre_commit_hook", return_value=["false"]):
        with mock.patch("relay.orchestrator.run_hook", side_effect=GitError("hook failed")):
            ai = StubAI()
            git = _make_git()
            orch = Orchestrator(git=git, provider=ai, yes=True, no_push=True)
            with pytest.raises(GitError, match="hook failed"):
                orch.run()
            git.commit.assert_not_called()


def test_orchestrator_post_push_runs_after_push(monkeypatch):
    from relay.orchestrator import Orchestrator

    with mock.patch("relay.orchestrator.get_pre_commit_hook", return_value=None):
        with mock.patch("relay.orchestrator.get_post_push_hook", return_value=["echo", "post"]):
            with mock.patch("relay.orchestrator.run_hook") as mh:
                ai = StubAI()
                git = _make_git()
                orch = Orchestrator(git=git, provider=ai, yes=True, no_push=False)
                orch.run()
                # post hook called after push
                mh.assert_called_once_with(["echo", "post"], verbose=False)
                git.push.assert_called_once()


def test_orchestrator_post_push_failure_is_warning(monkeypatch, capsys):
    from relay.orchestrator import Orchestrator

    with mock.patch("relay.orchestrator.get_pre_commit_hook", return_value=None):
        with mock.patch("relay.orchestrator.get_post_push_hook", return_value=["false"]):
            with mock.patch("relay.orchestrator.run_hook", side_effect=GitError("hook failed", stderr="err")):
                ai = StubAI()
                git = _make_git()
                orch = Orchestrator(git=git, provider=ai, yes=True, no_push=False)
                code = orch.run()
                assert code == 0  # push succeeded, hook failure is warning
                assert "post_push hook failed" in capsys.readouterr().out


def test_dry_run_does_not_run_hooks(monkeypatch):
    from relay.orchestrator import Orchestrator

    with mock.patch("relay.orchestrator.get_pre_commit_hook", return_value=["echo", "pre"]):
        with mock.patch("relay.orchestrator.run_hook") as mh:
            ai = StubAI()
            git = _make_git()
            orch = Orchestrator(git=git, provider=ai, yes=True, dry_run=True)
            orch.run()
            mh.assert_not_called()
            git.commit.assert_not_called()
