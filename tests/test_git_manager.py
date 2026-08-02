"""Unit tests for relay/git_manager.py.

subprocess.run is mocked on EVERY test so no real git commands are ever
executed — the suite is fully hermetic and safe to run on a machine that may
not even have git installed.
"""
from unittest import mock

import pytest

from relay.errors import GitError
from relay.git_manager import GitManager


@pytest.fixture
def git() -> GitManager:
    return GitManager(cwd="/fake/repo", verbose=False)


class TestRun:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_builds_argv_with_git_prefix_and_kwargs(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="true")
        git._run("rev-parse", "--is-inside-work-tree")
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd="/fake/repo",
            capture_output=True,
            text=True,
            input=None,
        )

    @mock.patch("relay.git_manager.subprocess.run")
    def test_raises_git_error_on_nonzero_exit(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(
            returncode=128, stderr="fatal: not a git repository"
        )
        with pytest.raises(GitError) as exc_info:
            git._run("rev-parse")
        assert "exit 128" in str(exc_info.value)
        assert exc_info.value.stderr == "fatal: not a git repository"
        assert exc_info.value.command == "git rev-parse"


class TestPreflightHelpers:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_is_repo_true(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="true")
        assert git.is_repo() is True

    @mock.patch("relay.git_manager.subprocess.run")
    def test_is_repo_false_when_git_fails(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal")
        assert git.is_repo() is False  # GitError must be swallowed here

    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_changes_true_when_porcelain_nonempty(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout=" M app.py\n")
        assert git.has_changes() is True

    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_changes_false_when_clean(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="")
        assert git.has_changes() is False

    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_remote(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="origin\n")
        assert git.has_remote() is True

    @mock.patch("relay.git_manager.subprocess.run")
    def test_current_branch_strips_whitespace(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="  main\n")
        assert git.current_branch() == "main"


class TestMutations:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_stage_all(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.stage_all()
        assert mock_run.call_args.args[0] == ["git", "add", "."]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_staged_diff_and_stat(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="diff output")
        assert git.staged_diff() == "diff output"
        assert mock_run.call_args.args[0] == ["git", "diff", "--cached"]

        mock_run.return_value = make_proc(stdout="stat output")
        assert git.staged_stat() == "stat output"
        assert mock_run.call_args.args[0] == ["git", "diff", "--cached", "--stat"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_pipes_message_via_stdin(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.commit("feat: subject\n\nbody line")
        assert mock_run.call_args.args[0] == ["git", "commit", "-F", "-"]
        assert mock_run.call_args.kwargs["input"] == "feat: subject\n\nbody line"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_create_branch(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.create_branch("status/payments")
        assert mock_run.call_args.args[0] == ["git", "checkout", "-b", "status/payments"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_push_without_upstream(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.push("main")
        assert mock_run.call_args.args[0] == ["git", "push", "origin", "main"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_push_with_upstream(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.push("status/payments", set_upstream=True)
        assert mock_run.call_args.args[0] == ["git", "push", "-u", "origin", "status/payments"]


class TestVerbose:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_verbose_prints_the_command(self, mock_run, capsys, make_proc):
        mock_run.return_value = make_proc()
        GitManager(cwd=None, verbose=True).stage_all()
        captured = capsys.readouterr()
        assert "$ git add ." in captured.out
