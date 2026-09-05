"""Unit tests for `relay squash` (relay/squash.py) and its CLI routing."""
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.errors import ConfigError, GitError, UserAbort
from relay.squash import run_squash


class FakeGit:
    """Stand-in for GitManager with controllable squash behavior."""

    def __init__(self, count=2, message="feat(billing): add invoicing", pushed=False,
                 depth=5, staged=False):
        self._count = count
        self._message = message
        self._pushed = pushed
        self._depth = depth
        self._staged = staged
        self.commit_error = None
        self.reset_target = None
        self.reset_targets = []
        self.commit_messages = []
        self.amend_flags = []
        self.diff_range_calls = []
        self.stat_range_calls = []
        self.staged_diff_called = False
        self.staged_stat_called = False

    def has_commits(self):
        return self._count > 0

    def commit_count(self):
        return self._count

    def root_commit(self):
        return "root123" if self._count else ""

    def has_staged_changes(self):
        return self._staged

    def rev_parse(self, ref):
        if ref == "HEAD":
            return "tip123"
        if ref.startswith("HEAD~"):
            n = int(ref[5:])
            return f"base{n}" if n <= self._depth else ""
        return ""

    def log_between(self, base, head):
        return "fix: a\nfeat: b"

    def diff_range(self, base, head):
        self.diff_range_calls.append((base, head))
        return "diff --git a/app.py b/app.py\n+def f(): pass"

    def stat_range(self, base, head):
        self.stat_range_calls.append((base, head))
        return " app.py | 1 +\n"

    def staged_diff(self):
        self.staged_diff_called = True
        return "diff --git a/staged.py b/staged.py\n+import os"

    def staged_stat(self):
        self.staged_stat_called = True
        return " staged.py | 1 +\n"

    def latest_commit_message(self):
        return self._message

    def current_branch(self):
        return "main"

    def check_branch_and_head(self, branch, head):
        # Mirrors GitManager.check_branch_and_head so tests exercise the
        # wiring (call timing + refusal propagation), not just its presence.
        if self.current_branch() != branch or self.rev_parse("HEAD") != head:
            raise GitError(
                "branch/HEAD changed while Relay was running; "
                "review `git status` and retry"
            )

    def is_ancestor(self, ancestor, descendant):
        return self._pushed

    def reset_soft(self, target):
        self.reset_target = target
        self.reset_targets.append(target)

    def commit(self, message, **kwargs):
        if self.commit_error:
            raise self.commit_error
        self.commit_messages.append(message)
        self.amend_flags.append(kwargs.get("amend", False))


class FakeProvider:
    def generate(self, diff, stat, branch):
        return "feat(billing): combine invoicing changes"


@pytest.fixture
def git():
    return FakeGit()


def test_squash_resets_to_count_and_commits_once(git):
    assert run_squash(git=git, count=3, yes=True) == 0
    assert git.reset_target == "HEAD~3"
    assert len(git.commit_messages) == 1


def test_squash_branch_switch_aborts_before_reset(git):
    """L1: a concurrent `git switch` during AI/confirm must not reset the wrong branch."""
    with mock.patch.object(git, "current_branch", side_effect=["main", "other"]):
        with pytest.raises(GitError, match="changed while Relay"):
            run_squash(git=git, count=2, yes=True)
    assert git.reset_target is None
    assert git.commit_messages == []


def test_squash_concurrent_stage_aborts_before_reset(git):
    """L2: changes staged after the up-front check must still abort the fold."""
    calls = {"n": 0}

    def _flaky_has_staged():
        calls["n"] += 1
        return calls["n"] > 1  # clean at entry, dirty by reset time

    git.has_staged_changes = _flaky_has_staged
    with pytest.raises(GitError, match="gained staged changes"):
        run_squash(git=git, count=2, yes=True)
    assert git.reset_target is None
    assert git.commit_messages == []


@pytest.mark.parametrize("passed", [1, 0, -3])
def test_squash_rejects_count_below_two(git, passed):
    with pytest.raises(GitError, match="at least 2 commits"):
        run_squash(git=git, count=passed, yes=True)
    assert git.reset_target is None


def test_squash_requires_history(git):
    git._count = 0
    with pytest.raises(GitError, match="no commits to squash"):
        run_squash(git=git, count=3, yes=True)


def test_squash_custom_message_wins(git):
    assert run_squash(git=git, count=3, message="fix: tighten validation", yes=True) == 0
    assert git.commit_messages == ["fix: tighten validation"]


def test_squash_uses_ai_when_provided(git):
    assert run_squash(git=git, count=3, provider=FakeProvider(), yes=True) == 0
    assert git.commit_messages == ["feat(billing): combine invoicing changes"]


def test_squash_feeds_ai_the_commit_range_diff_not_the_index(git):
    """Regression: squash used staged_diff()/staged_stat() to generate the AI
    message, but the index holds unrelated working-tree changes (reset --soft
    runs after the message is resolved). The AI must see the combined diff of
    the squashed commits — base..tip — so the message matches the actual fold."""
    assert run_squash(git=git, count=3, provider=FakeProvider(), yes=True) == 0
    assert git.diff_range_calls == [("base3", "tip123")]
    assert git.stat_range_calls == [("base3", "tip123")]
    assert git.staged_diff_called is False
    assert git.staged_stat_called is False


def test_squash_falls_back_to_commit_message(git):
    assert run_squash(git=git, count=3, yes=True) == 0
    assert git.commit_messages == ["feat(billing): add invoicing"]


def test_squash_ai_failure_falls_back_to_top_commit_message(git):
    """Regression: _message_from_ai used to raise UserAbort after printing
    "keeping the original commit message", aborting the squash instead of
    actually falling back. An unavailable AI must not block the fold."""
    class BrokenProvider:
        def generate(self, diff, stat, branch):
            raise RuntimeError("offline")

    assert run_squash(git=git, count=3, provider=BrokenProvider(), yes=True) == 0
    assert git.commit_messages == ["feat(billing): add invoicing"]


def test_squash_ai_garbage_falls_back_to_top_commit_message(git, capsys):
    class GarbageProvider:
        def generate(self, diff, stat, branch):
            return "not a conventional commit"

    assert run_squash(git=git, count=3, provider=GarbageProvider(), yes=True) == 0
    assert git.commit_messages == ["feat(billing): add invoicing"]
    assert "keeping the top commit's message" in capsys.readouterr().out


def test_squash_not_enough_history_raises(git):
    git._depth = 2
    with pytest.raises(GitError, match="not enough history"):
        run_squash(git=git, count=5, yes=True)
    assert git.reset_target is None
    assert git.commit_messages == []


def test_squash_insufficient_history_single_commit_no_misleading_hint(git):
    git._count = 1
    git._depth = 0
    with pytest.raises(GitError) as exc_info:
        run_squash(git=git, count=2, yes=True)
    assert "try --count 1" not in str(exc_info.value)
    assert "only 1 on HEAD" in str(exc_info.value)


def test_squash_entire_history_amends_the_root(git):
    """Regression: squashing ALL commits (`--count N` == total history) used to
    fail because `HEAD~N` points past the root commit. It must fold the whole
    tree into a single root-amended commit instead of raising."""
    git._count = 2
    git._depth = 1  # only HEAD~1 exists
    assert run_squash(git=git, count=2, yes=True) == 0
    assert git.reset_target == "root123"
    assert git.amend_flags == [True]
    assert len(git.commit_messages) == 1


def test_squash_entire_history_uses_range_diff_for_ai(git):
    """Regression (H-11): a whole-history fold used `root..tip`, silently
    omitting the root commit's own changes from the AI prompt. The diff base
    must be the empty tree so the root's content is included."""
    from relay.squash import EMPTY_TREE

    git._count = 2
    git._depth = 1
    assert run_squash(git=git, count=2, provider=FakeProvider(), yes=True) == 0
    assert git.diff_range_calls == [(EMPTY_TREE, "tip123")]
    assert git.stat_range_calls == [(EMPTY_TREE, "tip123")]


def test_squash_refuses_dirty_index(git):
    """Regression: squash silently swept pre-staged unrelated files into the
    new commit (reset --soft keeps the index). A non-empty index must be
    refused before any AI call or confirmation."""
    git._staged = True
    with pytest.raises(GitError, match="unrelated staged changes"):
        run_squash(git=git, count=3, yes=True)
    assert git.reset_target is None
    assert git.commit_messages == []
    assert git.diff_range_calls == []


def test_squash_dry_run_changes_nothing(git, capsys):
    assert run_squash(git=git, count=3, dry_run=True, yes=True) == 0
    assert git.reset_target is None
    assert git.commit_messages == []
    assert "dry-run" in capsys.readouterr().out


def test_squash_warns_when_pushed(git, capsys):
    git._pushed = True
    assert run_squash(git=git, count=3, yes=True) == 0
    assert "already pushed" in capsys.readouterr().out


def test_squash_restores_head_when_commit_fails(git, capsys):
    """Regression (C-04): a failed commit after the soft reset used to leave
    HEAD mid-reset, with the folds staged and no way to recover visually. It
    must reset --soft back to the original tip (non-destructive) and re-raise
    instead of pretending success."""
    git.commit_error = GitError("commit failed", command="git commit", stderr="hook rejected")
    with pytest.raises(GitError, match="commit failed"):
        run_squash(git=git, count=3, yes=True)
    assert git.reset_targets == ["HEAD~3", "tip123"]
    assert "HEAD restored" in capsys.readouterr().out
    assert git.commit_messages == []


def test_squash_entire_history_restores_head_on_commit_failure(git, capsys):
    """The HEAD-restore must work for squash-all too (reset target was the
    root; the restore needs the original tip, not the root)."""
    git._count = 2
    git._depth = 1
    git.commit_error = GitError("commit failed")
    with pytest.raises(GitError):
        run_squash(git=git, count=2, yes=True)
    assert git.reset_targets == ["root123", "tip123"]
    assert git.commit_messages == []


# ---- confirmation gate ------------------------------------------------------

def test_squash_confirms_before_mutating(git):
    with mock.patch("relay.squash.input", return_value="A"):
        with pytest.raises(UserAbort):
            run_squash(git=git, count=3)
    assert git.reset_target is None
    assert git.commit_messages == []


def test_squash_confirm_accept(git):
    with mock.patch("relay.squash.input", return_value="a"):
        assert run_squash(git=git, count=2) == 0
    assert len(git.commit_messages) == 1


def test_squash_confirm_edit_success(git):
    with mock.patch("relay.squash.input", side_effect=["e", "feat: custom edited"]):
        assert run_squash(git=git, count=2) == 0
    assert git.commit_messages == ["feat: custom edited"]


def test_squash_confirm_edit_blank_aborts(git):
    with mock.patch("relay.squash.input", side_effect=["e", ""]):
        with pytest.raises(UserAbort):
            run_squash(git=git, count=2)


def test_squash_restore_head_failure_does_not_crash(git, capsys):
    git.commit_error = GitError("commit hook fail")
    # Make the second reset_soft (the restore) fail as well
    call_count = 0
    original_reset = git.reset_soft
    def flaking_reset(target):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise GitError("cannot restore")
        return original_reset(target)
    git.reset_soft = flaking_reset
    with pytest.raises(GitError, match="commit hook fail"):
        run_squash(git=git, count=2, yes=True)
    assert "automatic recovery failed" in capsys.readouterr().out



# ---- CLI routing ------------------------------------------------------------

def test_parser_squash_defaults():
    args = build_parser().parse_args(["squash"])
    assert args.command == "squash"
    assert args.count == 2


def test_parser_squash_count_flag():
    args = build_parser().parse_args(["squash", "--count", "4"])
    assert args.count == 4


def test_main_squash_routes_and_forwards():
    with mock.patch("relay.cli.build_provider"), mock.patch(
        "relay.cli.run_squash", return_value=0
    ) as run:
        assert main(["squash", "--count", "4"]) == 0
    run.assert_called_once()
    assert run.call_args.kwargs["count"] == 4


def test_main_squash_error_maps_to_exit_1():
    with mock.patch("relay.cli.build_provider"), mock.patch(
        "relay.cli.run_squash", side_effect=GitError("boom")
    ):
        assert main(["squash"]) == 1


def test_main_squash_with_message_skips_the_provider():
    """Regression: squash built the provider unconditionally, so
    `relay squash --message ...` failed with a ConfigError when no API key
    was set, even though the AI is never used in that path."""
    with mock.patch("relay.cli.build_provider") as build_provider, mock.patch(
        "relay.cli.run_squash", return_value=0
    ) as run:
        assert main(["squash", "--message", "chore: bump lockfile"]) == 0
    build_provider.assert_not_called()
    assert run.call_args.kwargs["provider"] is None


def test_main_squash_missing_key_falls_back_to_provider_none():
    """A missing GEMINI_API_KEY must not abort a plain squash; squash.py
    falls back to the top commit's message when provider is None."""
    with mock.patch(
        "relay.cli.build_provider", side_effect=ConfigError("no key")
    ), mock.patch("relay.cli.run_squash", return_value=0) as run:
        assert main(["squash"]) == 0
    assert run.call_args.kwargs["provider"] is None
