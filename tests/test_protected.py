"""Unit tests for the default-branch safety rule (relay/protected.py)."""
from unittest import mock

import pytest

from relay.errors import ProtectedBranchError
from relay.orchestrator import Orchestrator
from relay.protected import assert_branch_allowed, is_protected


class StubAI:
    def __init__(self, response="feat(api): add login"):
        self._response = response

    def generate(self, diff, stat, branch):
        return self._response


@pytest.fixture
def git():
    g = mock.Mock()
    g.is_repo.return_value = True
    g.has_changes.return_value = True
    g.has_remote.return_value = True
    g.staged_diff.return_value = "diff --git a/app.py b/app.py\n+print(1)\n"
    g.staged_stat.return_value = " app.py | 1 +\n"
    g.current_branch.return_value = "main"
    g.staged_diff_binary_only.return_value = False
    return g


def make_orchestrator(git, **kwargs):
    defaults = dict(mode="team", no_push=True, protected_branches=["main", "master"])
    defaults.update(kwargs)
    return Orchestrator(git=git, **defaults)


# ---- is_protected -------------------------------------------------------------


def test_is_protected_matches_configured_branch():
    assert is_protected("main", ["main", "master"]) is True
    assert is_protected("feat/payments", ["main", "master"]) is False


def test_is_protected_matches_case_insensitively():
    """M-14: a differently-cased branch name must not bypass the guard."""
    assert is_protected("MAIN", ["main", "master"]) is True
    assert is_protected("main", ["Main"]) is True


def test_is_protected_empty_list_allows_everything():
    assert is_protected("main", []) is False


# ---- assert_branch_allowed ----------------------------------------------------


def test_assert_allows_unprotected_branch():
    assert_branch_allowed("feat/payments", ["main"])  # no exception


def test_assert_refuses_protected_branch():
    with pytest.raises(ProtectedBranchError) as exc:
        assert_branch_allowed("main", ["main"])
    assert "protected branch" in str(exc.value)
    assert "--allow-protected" in str(exc.value)


def test_assert_force_skips_the_guard():
    assert_branch_allowed("main", ["main"], force=True)  # no exception


# ---- Orchestrator: team mode + protected branch --------------------------------


def test_team_mode_refuses_protected_target_branch(git):
    git.current_branch.return_value = "feature/main"
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        with pytest.raises(ProtectedBranchError):
            make_orchestrator(git, provider=ai, feature="main", branch_template="<feature>").run()
    git.commit.assert_not_called()
    git.create_branch.assert_not_called()


def test_team_mode_allow_protected_override(git, capsys):
    git.current_branch.return_value = "feature/main"
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        code = make_orchestrator(
            git, provider=ai, feature="main", branch_template="<feature>", allow_protected=True
        ).run()
    assert code == 0
    git.create_branch.assert_called_once_with("main")
    git.commit.assert_called_once()


def test_team_mode_yes_flag_does_not_bypass_protection(git):
    """--yes skips the confirmation prompt only; it must never bypass the
    default-branch safety guard. A scripted/CI run using --yes on a protected
    branch has to opt out with the explicit --allow-protected flag."""
    git.current_branch.return_value = "feature/main"
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        with pytest.raises(ProtectedBranchError):
            make_orchestrator(
                git, provider=ai, feature="main", branch_template="<feature>", yes=True
            ).run()
    git.commit.assert_not_called()
    git.create_branch.assert_not_called()


def test_team_mode_dry_run_warns_instead_of_blocking(git, capsys):
    git.current_branch.return_value = "feature/main"
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        code = make_orchestrator(
            git, provider=ai, feature="main", branch_template="<feature>", dry_run=True
        ).run()
    assert code == 0
    out = capsys.readouterr().out
    assert "protected branch" in out
    git.create_branch.assert_not_called()
    git.commit.assert_not_called()


def test_solo_mode_keeps_committing_to_any_branch(git):
    """Solo convention: committing to the current branch is never blocked."""
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        code = make_orchestrator(
            git, provider=ai, mode="solo", protected_branches=["main"]
        ).run()
    assert code == 0
    git.commit.assert_called_once()  # on "main" — solo convention preserved


def test_team_mode_on_protected_branch_prompts_for_feature(git):
    """L-10: running --team straight from main/master must not inherit
    'main'/'master' as the feature name (which would then be refused as a
    protected branch). Ask the developer for a real feature name instead."""
    git.current_branch.return_value = "main"
    ai = StubAI()
    with mock.patch("builtins.input", side_effect=["a", "payments"]):
        code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")
    git.commit.assert_called_once()


def test_team_mode_from_feature_branch_still_inherits_feature_name(git):
    """A non-protected current branch keeps inheriting its feature name."""
    git.current_branch.return_value = "feat/payments"
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")


def test_non_protected_team_branch_is_untouched(git):
    ai = StubAI()
    with mock.patch("builtins.input", return_value="a"):
        code = make_orchestrator(git, provider=ai, feature="payments").run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")
