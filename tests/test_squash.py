"""Unit tests for `relay squash` (relay/squash.py) and its CLI routing."""
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.errors import GitError, UserAbort
from relay.squash import run_squash


class FakeGit:
    """Stand-in for GitManager with controllable squash behavior."""

    def __init__(self, count=2, message="feat(billing): add invoicing", pushed=False,
                 depth=5):
        self._count = count
        self._message = message
        self._pushed = pushed
        self._depth = depth
        self.reset_target = None
        self.commit_messages = []
        self.diff_range_calls = []
        self.stat_range_calls = []
        self.staged_diff_called = False
        self.staged_stat_called = False

    def has_commits(self):
        return self._count > 0

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

    def is_ancestor(self, ancestor, descendant):
        return self._pushed

    def reset_soft(self, target):
        self.reset_target = target

    def commit(self, message, **kwargs):
        self.commit_messages.append(message)


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


def test_squash_dry_run_changes_nothing(git, capsys):
    assert run_squash(git=git, count=3, dry_run=True, yes=True) == 0
    assert git.reset_target is None
    assert git.commit_messages == []
    assert "dry-run" in capsys.readouterr().out


def test_squash_warns_when_pushed(git, capsys):
    git._pushed = True
    assert run_squash(git=git, count=3, yes=True) == 0
    assert "already pushed" in capsys.readouterr().out


# ---- confirmation gate ------------------------------------------------------

def test_squash_confirms_before_mutating(git):
    with mock.patch("relay.squash.input", return_value="A"):
        with pytest.raises(UserAbort):
            run_squash(git=git, count=3)
    assert git.reset_target is None
    assert git.commit_messages == []


# ---- CLI routing ------------------------------------------------------------

def test_parser_squash_defaults():
    args = build_parser().parse_args(["squash"])
    assert args.command == "squash"
    assert args.count == 2


def test_parser_squash_count_flag():
    args = build_parser().parse_args(["squash", "--count", "4"])
    assert args.count == 4


def test_main_squash_routes_and_forwards():
    with mock.patch("relay.cli.build_provider") as build_provider, mock.patch(
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