"""Unit tests for the Orchestrator, with emphasis on the AI fallback.

The GitManager is replaced with a Mock (no git commands ever run) and
builtins.input is patched so prompts are answered programmatically. The heart
of the suite verifies the exact requirement: when the AI throws an exception,
the workflow falls back to manual input WITHOUT exiting.
"""
from unittest import mock

import pytest

from relay.errors import AIError, GitError, UserAbort
from relay.git_manager import GitManager
from relay.orchestrator import Orchestrator


class StubAI:
    """A stand-in provider: raises an error or returns canned responses."""

    def __init__(self, responses=(), error=None):
        self.responses = list(responses)
        self.error = error
        self.generate_calls = []

    def generate(self, diff, stat, branch):
        self.generate_calls.append((diff, stat, branch))
        if self.error:
            raise self.error
        return self.responses.pop(0)


@pytest.fixture
def git():
    """A GitManager double whose git commands are all no-ops with sane defaults."""
    g = mock.Mock(spec=GitManager)
    g.is_repo.return_value = True
    g.has_changes.return_value = True
    g.has_remote.return_value = True
    g.staged_diff.return_value = "diff --git a/app.py b/app.py\n+print(1)\n"
    g.staged_stat.return_value = " app.py | 1 +\n"
    g.head_diff.return_value = "diff --git a/app.py b/app.py\n+print(1)\n"
    g.head_stat.return_value = " app.py | 1 +\n"
    g.current_branch.return_value = "main"
    g.staged_diff_binary_only.return_value = False
    g.head_diff_binary_only.return_value = False
    g.write_tree.return_value = "abc123"
    return g


def make_orchestrator(git, **kwargs):
    defaults = dict(mode="solo", no_push=True)
    defaults.update(kwargs)
    return Orchestrator(git=git, **defaults)


# ---- The fallback mechanism -------------------------------------------------


@mock.patch("builtins.input", side_effect=["fix: manual fallback message", ""])
def test_ai_failure_falls_back_to_manual_input_and_commits(mock_input, git):
    ai = StubAI(error=AIError("fake", "rate_limited", "out of quota"))
    code = make_orchestrator(git, provider=ai).run()

    assert code == 0
    git.commit.assert_called_once_with("fix: manual fallback message", no_verify=False)
    git.push.assert_not_called()  # --no-push
    assert ai.generate_calls, "the AI must have been tried before falling back"


# ---- H-14: provider=None degrades straight to manual input --------------------


@mock.patch("builtins.input", side_effect=["fix: no ai needed", ""])
def test_no_provider_goes_straight_to_manual_input(mock_input, git):
    """With provider=None (missing API key), the run must not crash and must
    not require a mock generate — it goes straight to the manual-input path."""
    code = make_orchestrator(git, provider=None).run()
    assert code == 0
    git.commit.assert_called_once_with("fix: no ai needed", no_verify=False)


@mock.patch("builtins.input", side_effect=["fix: team no ai", ""])
def test_no_provider_team_mode_uses_manual_message_for_branch(mock_input, git):
    """Team mode with no provider: the branch type still comes from the manual
    message, so the branch name is resolved and created normally."""
    code = make_orchestrator(
        git, provider=None, mode="team", feature="payments", no_push=True
    ).run()
    assert code == 0
    git.create_branch.assert_called_once_with("fix/payments")
    git.commit.assert_called_once_with("fix: team no ai", no_verify=False)


@mock.patch("builtins.input", side_effect=["fix: manual fallback message", ""])
def test_connection_refused_also_falls_back(mock_input, git):
    ai = StubAI(error=AIError("ollama", "unavailable", "connection refused"))
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("fix: manual fallback message", no_verify=False)


@mock.patch("builtins.input", return_value="")
def test_empty_manual_input_aborts_without_committing(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    with pytest.raises(UserAbort):
        make_orchestrator(git, provider=ai).run()
    git.commit.assert_not_called()

# ---- F4: transient (429/5xx) retry + backoff ----------------------------------


class FlakyAI:
    """A provider that replays a script of AIError raises and canned responses."""

    def __init__(self, script):
        self.script = list(script)
        self.generate_calls = []

    def generate(self, diff, stat, branch):
        self.generate_calls.append((diff, stat, branch))
        item = self.script.pop(0)
        if isinstance(item, AIError):
            raise item
        return item


@mock.patch("relay.orchestrator.time.sleep")
@mock.patch("builtins.input", side_effect=["fix: after retries", ""])
def test_rate_limited_is_retried_twice_before_fallback(mock_input, mock_sleep, git):
    # Two transient failures in a row, then a manual fallback.
    ai = FlakyAI([
        AIError("gemini", "rate_limited", "HTTP 429"),
        AIError("gemini", "rate_limited", "HTTP 429"),
        AIError("gemini", "rate_limited", "HTTP 429"),
    ])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    assert len(ai.generate_calls) == 3  # 2 retries, then manual fallback
    assert mock_sleep.call_args_list == [mock.call(1), mock.call(2)]
    git.commit.assert_called_once_with("fix: after retries", no_verify=False)


@mock.patch("relay.orchestrator.time.sleep")
@mock.patch("builtins.input", return_value="")
def test_rate_limited_recovers_on_second_attempt(mock_input, mock_sleep, git):
    ai = FlakyAI([AIError("gemini", "rate_limited", "HTTP 429"), "feat(api): ok"])
    code = make_orchestrator(git, provider=ai, yes=True).run()
    assert code == 0
    assert mock_sleep.call_count == 1  # one backoff before success
    git.commit.assert_called_once_with("feat(api): ok", no_verify=False)


@mock.patch("relay.orchestrator.time.sleep")
@mock.patch("builtins.input", return_value="")
def test_api_error_is_retried_twice_before_fallback(mock_input, mock_sleep, git):
    """api_error (e.g. a 4xx HTTP status) is in the transient retry set, so it
    gets the same 2x backoff as rate_limited before the manual fallback."""
    ai = FlakyAI([
        AIError("gemini", "api_error", "HTTP 401"),
        AIError("gemini", "api_error", "HTTP 401"),
        AIError("gemini", "api_error", "HTTP 401"),
    ])
    with pytest.raises(UserAbort):  # empty manual input aborts
        make_orchestrator(git, provider=ai).run()
    assert len(ai.generate_calls) == 3  # 2 retries, then manual fallback
    assert mock_sleep.call_args_list == [mock.call(1), mock.call(2)]


@mock.patch("relay.orchestrator.time.sleep")
def test_non_transient_error_is_not_retried(mock_sleep, git):
    ai = FlakyAI([AIError("ollama", "unavailable", "down")])
    with mock.patch("builtins.input",
                    side_effect=["fix: straight to manual", ""]):
        make_orchestrator(git, provider=ai).run()
    assert mock_sleep.call_count == 0  # unavailable is never retried
    git.commit.assert_called_once_with("fix: straight to manual", no_verify=False)


@mock.patch("builtins.input", side_effect=["WIP stuff", ""])
def test_manual_message_is_committed_verbatim_even_if_not_conventional(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    # Manual fallback is intentionally NOT validated — the user's words win.
    git.commit.assert_called_once_with("WIP stuff", no_verify=False)


@mock.patch("builtins.input", side_effect=["fix: garbage response fallback", ""])
def test_garbage_ai_response_triggers_fallback(mock_input, git):
    # Model returns a non-Conventional line -> treated exactly like an outage.
    ai = StubAI(responses=["wip stuff"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("fix: garbage response fallback", no_verify=False)


# ---- Confirmation gate -------------------------------------------------------


@mock.patch("builtins.input", return_value="a")
def test_ai_message_requires_confirmation_then_commits(mock_input, git):
    ai = StubAI(responses=["feat(api): add login"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("feat(api): add login", no_verify=False)
    assert mock_input.call_count == 1  # only the [Accept] prompt


def test_yes_skips_confirmation_prompt(git):
    ai = StubAI(responses=["feat(api): add login"])
    code = make_orchestrator(git, provider=ai, yes=True).run()
    assert code == 0
    git.commit.assert_called_once_with("feat(api): add login", no_verify=False)


@mock.patch("builtins.input", side_effect=["e", "fix: edited by hand", ""])
def test_edit_confirmation_uses_manual_input(mock_input, git):
    ai = StubAI(responses=["feat(api): add login"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("fix: edited by hand", no_verify=False)


@mock.patch("builtins.input", side_effect=["r", "a"])
def test_retry_ai_regenerates_before_accept(mock_input, git):
    ai = StubAI(responses=["feat(api): add login", "fix(api): add login"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    assert len(ai.generate_calls) == 2  # first message rejected, second accepted
    git.commit.assert_called_once_with("fix(api): add login", no_verify=False)


@mock.patch("relay.orchestrator.time.sleep")
@mock.patch("builtins.input", side_effect=["r", "a"])
def test_user_retry_after_transient_retries_does_not_abort_early(mock_input, mock_sleep, git):
    from relay.errors import AIError

    ai = FlakyAI([
        AIError("gemini", "rate_limited", "slow down"),
        AIError("gemini", "rate_limited", "slow down"),
        "feat(api): first try",
        "feat(api): second try",
    ])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("feat(api): second try", no_verify=False)


@mock.patch("builtins.input", return_value="x")
def test_unknown_confirm_choice_aborts(mock_input, git):
    ai = StubAI(responses=["feat: ok"])
    with pytest.raises(UserAbort):
        make_orchestrator(git, provider=ai).run()
    git.commit.assert_not_called()


@mock.patch("builtins.input", return_value="a")
def test_lowercase_a_accepts(mock_input, git):
    ai = StubAI(responses=["feat(api): add login"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("feat(api): add login", no_verify=False)


@mock.patch("builtins.input", return_value="A")
def test_uppercase_a_aborts_without_committing(mock_input, git):
    # Regression: Shift+A used to be lowercased to "a" and accidentally commit.
    ai = StubAI(responses=["feat(api): add login"])
    with pytest.raises(UserAbort):
        make_orchestrator(git, provider=ai).run()
    git.commit.assert_not_called()


@mock.patch("builtins.input", return_value="")
def test_enter_at_confirmation_aborts(mock_input, git):
    # Empty input aborts (Abort is the capitalized default); it must NOT accept.
    ai = StubAI(responses=["feat(api): add login"])
    with pytest.raises(UserAbort):
        make_orchestrator(git, provider=ai).run()
    git.commit.assert_not_called()


@mock.patch("builtins.input", return_value="y")
def test_yes_accepts(mock_input, git):
    ai = StubAI(responses=["feat(api): add login"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with("feat(api): add login", no_verify=False)


@mock.patch("builtins.input", return_value="q")
def test_q_aborts_without_committing(mock_input, git):
    ai = StubAI(responses=["feat(api): add login"])
    with pytest.raises(UserAbort):
        make_orchestrator(git, provider=ai).run()
    git.commit.assert_not_called()


# ---- Modes and push ----------------------------------------------------------


@mock.patch("builtins.input", side_effect=["fix: push it", ""])
def test_solo_mode_pushes_current_branch(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, no_push=False).run()
    assert code == 0
    git.push.assert_called_once_with("main", set_upstream=False)


@mock.patch("builtins.input", side_effect=["fix: skip hooks", ""])
def test_no_verify_forwards_to_commit(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, no_verify=True).run()
    assert code == 0
    git.commit.assert_called_once_with("fix: skip hooks", no_verify=True)


@mock.patch("builtins.input", side_effect=["feat: team work", ""])
def test_team_mode_creates_branch_and_pushes_upstream(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(
        git, provider=ai, mode="team", feature="payments", no_push=False
    ).run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")
    git.push.assert_called_once_with("feat/payments", set_upstream=True)


@mock.patch("builtins.input", side_effect=["feat: derived", ""])
def test_team_feature_derived_from_current_branch(mock_input, git):
    git.current_branch.return_value = "feature/payments"
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, mode="team", no_push=False).run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")
    git.push.assert_called_once_with("feat/payments", set_upstream=True)


@mock.patch("builtins.input", side_effect=["feat: prompted", "", "payments"])
def test_team_feature_prompted_when_nothing_to_derive_from(mock_input, git):
    """Without --team and without a current branch, the feature name comes from
    the isolated _prompt_feature_name seam (a single input() call)."""
    git.current_branch.return_value = ""
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, mode="team", no_push=True).run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")


@mock.patch("builtins.input", side_effect=["a"])
def test_team_branch_uses_commit_type_from_ai_message(mock_input, git):
    ai = StubAI(responses=["fix(api): correct validation"])
    code = make_orchestrator(
        git, provider=ai, mode="team", feature="payments", no_push=True
    ).run()
    assert code == 0
    git.create_branch.assert_called_once_with("fix/payments")
    git.commit.assert_called_once_with("fix(api): correct validation", no_verify=False)


@mock.patch("builtins.input", side_effect=["WIP stuff", ""])
def test_team_branch_falls_back_to_feat_for_non_conventional_message(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(
        git, provider=ai, mode="team", feature="payments", no_push=True
    ).run()
    assert code == 0
    git.create_branch.assert_called_once_with("feat/payments")


@mock.patch("builtins.input", side_effect=["a"])
def test_team_branch_uses_docs_type_from_ai_message(mock_input, git):
    ai = StubAI(responses=["docs(readme): clarify install"])
    code = make_orchestrator(
        git, provider=ai, mode="team", feature="setup", no_push=True
    ).run()
    assert code == 0
    git.create_branch.assert_called_once_with("docs/setup")


@mock.patch("builtins.input", side_effect=["fix: push fails but commit stays", ""])
def test_push_failure_returns_1_and_keeps_commit(mock_input, git):
    git.push.side_effect = GitError("push rejected", stderr="! [rejected]")
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, no_push=False).run()
    assert code == 1
    git.commit.assert_called_once()  # commit happened; only the push failed


# ---- H-13: a detached HEAD (empty branch) must not be pushed ------------------


@mock.patch("builtins.input", side_effect=["fix: detached head", ""])
def test_solo_push_on_detached_head_is_refused_with_message(mock_input, git, capsys):
    git.current_branch.return_value = ""
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, no_push=False).run()
    assert code == 1
    git.commit.assert_called_once()  # the commit itself still happened
    git.push.assert_not_called()  # but never push an empty branch ref
    out = capsys.readouterr().out
    assert "detached" in out
    assert "git switch -c" in out


@mock.patch("builtins.input", side_effect=["fix: detached no push", ""])
def test_solo_detached_head_with_no_push_still_commits(mock_input, git):
    git.current_branch.return_value = ""
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, no_push=True).run()
    assert code == 0
    git.commit.assert_called_once()
    git.push.assert_not_called()


# ---- C-05: team commit failure rolls back the orphan branch --------------------


@mock.patch("builtins.input", side_effect=["feat: team work", ""])
def test_team_commit_failure_rolls_back_orphan_branch(mock_input, git):
    """Regression: a failed commit on the freshly created feature branch used
    to strand the developer on an orphan branch with the original branch
    abandoned. It must check out the original branch and delete the orphan."""
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    git.commit.side_effect = GitError("hook rejected")
    with pytest.raises(GitError):
        make_orchestrator(git, provider=ai, mode="team", feature="payments").run()
    git.create_branch.assert_called_once_with("feat/payments")
    git.checkout.assert_called_once_with("main")
    git.delete_branch.assert_called_once_with("feat/payments")


@mock.patch("builtins.input", side_effect=["feat: team work", ""])
def test_team_commit_failure_reports_when_rollback_also_fails(mock_input, git, capsys):
    """If the rollback itself fails (e.g. a detached HEAD with no branch to go
    back to), the original GitError must still surface with a cleanup hint."""
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    git.commit.side_effect = GitError("hook rejected")
    git.checkout.side_effect = GitError("checkout failed")
    with pytest.raises(GitError, match="hook rejected"):
        make_orchestrator(git, provider=ai, mode="team", feature="payments").run()
    assert "could not auto-clean" in capsys.readouterr().out


@mock.patch("builtins.input", side_effect=["feat: team work", ""])
def test_team_commit_success_does_not_touch_original_branch(mock_input, git):
    """The rollback must only run on the failure path."""
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, mode="team", feature="payments").run()
    assert code == 0
    git.checkout.assert_not_called()
    git.delete_branch.assert_not_called()


# ---- Preflight / guards ------------------------------------------------------


def test_not_a_repo_raises_before_any_mutation(git):
    git.is_repo.return_value = False
    with pytest.raises(GitError):
        make_orchestrator(git, provider=StubAI()).run()
    git.stage_all.assert_not_called()


def test_clean_tree_returns_0_without_staging(git):
    git.has_changes.return_value = False
    code = make_orchestrator(git, provider=StubAI()).run()
    assert code == 0
    git.stage_all.assert_not_called()


def test_empty_staged_diff_returns_0_without_calling_ai(git):
    git.staged_diff.return_value = ""
    ai = StubAI(responses=["feat: never used"])
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    assert ai.generate_calls == []
    git.commit.assert_not_called()


@mock.patch("builtins.input", side_effect=["fix: dry run", ""])
def test_dry_run_reports_plan_without_mutating(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, dry_run=True).run()
    assert code == 0
    git.commit.assert_not_called()
    git.push.assert_not_called()
    git.create_branch.assert_not_called()
    git.stage_all.assert_not_called()


@mock.patch("builtins.input", side_effect=["fix: dry run staged", ""])
def test_dry_run_does_not_stage_and_uses_head_diff(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    git.head_diff.return_value = "diff --git a/app.py b/app.py\n+new\n"
    git.head_stat.return_value = " app.py | 1 +"
    git.head_diff_binary_only.return_value = False
    code = make_orchestrator(git, provider=ai, dry_run=True, staged_only=False).run()
    assert code == 0
    git.stage_all.assert_not_called()
    git.head_diff.assert_called_once()
    git.head_stat.assert_called_once()
    git.staged_diff.assert_not_called()


@mock.patch("builtins.input", side_effect=["fix: dry run staged only", ""])
def test_dry_run_staged_only_uses_staged_diff(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, dry_run=True, staged_only=True).run()
    assert code == 0
    git.stage_all.assert_not_called()
    git.staged_diff.assert_called_once()
    git.head_diff.assert_not_called()


# ---- TOCTOU: index must not change between AI and commit --------------------


@mock.patch("builtins.input", side_effect=["fix: toctou", ""])
def test_toctou_raises_when_index_changed(mock_input, git):
    ai = StubAI(responses=["feat: toctou"])
    git.write_tree.side_effect = ["tree-before", "tree-after"]  # differs
    with mock.patch("relay.orchestrator.validate_conventional", return_value=(True, "")):
        with mock.patch("relay.orchestrator.sanitize_ai_message", return_value="feat: toctou"):
            with pytest.raises(GitError, match="staged changes changed"):
                make_orchestrator(git, provider=ai, yes=True).run()
    git.commit.assert_not_called()


def test_toctou_passes_when_index_unchanged(git):
    ai = StubAI(responses=["feat: stable"])
    git.write_tree.return_value = "same-tree"
    with mock.patch("relay.orchestrator.validate_conventional", return_value=(True, "")):
        with mock.patch("relay.orchestrator.sanitize_ai_message", return_value="feat: stable"):
            code = make_orchestrator(git, provider=ai, yes=True).run()
    assert code == 0
    git.commit.assert_called_once()


# ---- --staged: respect the developer's own staging ----------------------------


@mock.patch("builtins.input", side_effect=["fix: already staged", ""])
def test_staged_only_skips_git_add(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, staged_only=True).run()
    assert code == 0
    git.stage_all.assert_not_called()  # the user's staging is left untouched
    git.commit.assert_called_once_with("fix: already staged", no_verify=False)


def test_staged_only_still_commits_the_staged_diff(git):
    git.staged_diff.return_value = "diff --git a/app.py b/app.py\n+print(2)\n"
    ai = StubAI(responses=["feat: staged only"])
    code = make_orchestrator(git, provider=ai, staged_only=True, yes=True).run()
    assert code == 0
    assert ai.generate_calls, "the staged diff must still be read and sent"
    git.commit.assert_called_once_with("feat: staged only", no_verify=False)


# ---- Multi-line manual message (subject + body) -------------------------------


@mock.patch(
    "builtins.input",
    side_effect=[
        "feat(auth): add login",
        "Adds the login form and session handling.",
        "",
    ],
)
def test_multi_line_manual_message_separates_subject_and_body(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    git.commit.assert_called_once_with(
        "feat(auth): add login\n\nAdds the login form and session handling.",
        no_verify=False,
    )


# ---- amend mode: rewrite the last commit, never push -------------------------

@mock.patch("builtins.input", side_effect=["fix: amend last commit", ""])
def test_amend_mode_commits_with_amend_and_never_pushes(mock_input, git):
    git.rev_parse.return_value = "abc123"
    git.is_ancestor.return_value = False
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, mode="amend").run()
    assert code == 0
    git.commit.assert_called_once_with("fix: amend last commit", amend=True)
    git.create_branch.assert_not_called()
    git.push.assert_not_called()


@mock.patch("builtins.input", side_effect=["fix: amend it", ""])
def test_amend_mode_warns_when_commit_already_pushed(mock_input, git, capsys):
    git.rev_parse.return_value = "abc123"
    git.is_ancestor.return_value = True
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, mode="amend").run()
    assert code == 0
    out = capsys.readouterr().out
    assert "--force-with-lease" in out
    git.push.assert_not_called()


@mock.patch("builtins.input", side_effect=["fix: amend dry", ""])
def test_amend_mode_dry_run_does_not_commit(mock_input, git):
    ai = StubAI(error=AIError("fake", "unavailable", "down"))
    code = make_orchestrator(git, provider=ai, mode="amend", dry_run=True).run()
    assert code == 0
    git.commit.assert_not_called()


def test_amend_mode_empty_staged_diff_returns_0(git):
    git.staged_diff.return_value = ""
    ai = StubAI(responses=["feat: never used"])
    code = make_orchestrator(git, provider=ai, mode="amend").run()
    assert code == 0
    assert ai.generate_calls == []
    git.commit.assert_not_called()


# ---- H-12: binary-only staged diff falls back to manual input -----------------


@mock.patch("builtins.input", side_effect=["fix: binary asset update", ""])
def test_binary_only_staged_diff_skips_ai_and_uses_manual_message(mock_input, git):
    """An AI cannot summarize a diff it cannot read (binary files); the run
    must go straight to manual input and never call the provider."""
    ai = StubAI(responses=["feat: must never be used"])
    git.staged_diff_binary_only.return_value = True
    code = make_orchestrator(git, provider=ai).run()
    assert code == 0
    assert ai.generate_calls == []
    git.commit.assert_called_once_with("fix: binary asset update", no_verify=False)
