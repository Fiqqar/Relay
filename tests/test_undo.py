"""Unit tests for `relay undo` (relay/undo.py) and its CLI routing."""
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.errors import GitError
from relay.undo import run_undo


class FakeGit:
    """Stand-in for GitManager with controllable undo behavior."""

    def __init__(self, is_repo=True, has_commits=True, branch="main", pushed=False):
        self._is_repo = is_repo
        self._commits = has_commits
        self._branch = branch
        self._pushed = pushed
        self.reset_calls = 0

    def is_repo(self):
        return self._is_repo

    def has_commits(self):
        return self._commits

    def current_branch(self):
        return self._branch

    def rev_parse(self, ref):
        return "abc123" if ref == "HEAD" else ""

    def is_ancestor(self, ancestor, descendant):
        return self._pushed

    def reset_soft(self):
        self.reset_calls += 1


@pytest.fixture
def git():
    return FakeGit()


def test_undo_resets_soft_and_reports(git, capsys):
    assert run_undo(git) == 0
    assert git.reset_calls == 1
    out = capsys.readouterr().out
    assert "undone last commit" in out
    assert "nothing lost" in out


def test_undo_warns_when_commit_was_pushed(git, capsys):
    git._pushed = True
    assert run_undo(git) == 0
    out = capsys.readouterr().out
    assert "already pushed" in out


def test_undo_not_a_repo_raises(git):
    git._is_repo = False
    with pytest.raises(GitError, match="not a git repository"):
        run_undo(git)
    assert git.reset_calls == 0


def test_undo_no_commits_raises(git):
    git._commits = False
    with pytest.raises(GitError, match="no commits to undo"):
        run_undo(git)
    assert git.reset_calls == 0


def test_undo_detached_head_still_works(git):
    git._branch = ""
    assert run_undo(git) == 0
    assert git.reset_calls == 1


# ---- CLI routing -----------------------------------------------------------

def test_parser_routes_undo_subcommand():
    assert build_parser().parse_args(["undo"]).command == "undo"
    assert build_parser().parse_args([]).command is None


def test_main_undo_routes_and_propagates_exit_code():
    with mock.patch("relay.cli.run_undo", return_value=0) as run:
        assert main(["undo"]) == 0
    run.assert_called_once_with(verbose=False)


def test_main_undo_error_maps_to_exit_1():
    with mock.patch("relay.cli.run_undo", side_effect=GitError("boom")):
        assert main(["undo"]) == 1
