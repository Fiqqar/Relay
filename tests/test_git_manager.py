"""Unit tests for relay/git_manager.py.

subprocess.run is mocked on EVERY test so no real git commands are ever
executed — the suite is fully hermetic and safe to run on a machine that may
not even have git installed.
"""
import subprocess
from unittest import mock

import pytest

from relay.errors import GitError
from relay.git_manager import GitManager, parse_remote, parse_remote_url


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
            encoding="utf-8",
            errors="replace",
            input=None,
        )

    @mock.patch("relay.git_manager.subprocess.run")
    def test_invalid_bytes_never_yield_none_stdout(self, mock_run, git):
        """C-17: git output the locale codec (cp1252 on Windows) cannot decode
        must not crash. `subprocess.run` with text=True and no encoding lets a
        UnicodeDecodeError kill the reader thread, after which stdout/stderr
        come back as None and `proc.stdout.strip()` raises AttributeError. The
        explicit utf-8 + errors=replace kwargs guarantee stdout is always str.
        """
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=None, stderr=None
        )
        git._run("diff", "--cached", "--unified=0")
        assert mock_run.call_args.kwargs["encoding"] == "utf-8"
        assert mock_run.call_args.kwargs["errors"] == "replace"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_non_utf8_bytes_decode_to_replacement_char(self, mock_run, git):
        """A byte sequence invalid in both cp1252 and utf-8 becomes U+FFFD in
        the captured stdout instead of raising in the reader thread."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\ufffd", stderr=""
        )
        assert git.staged_diff() == "\ufffd"

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

    @mock.patch("relay.git_manager.subprocess.run")
    def test_network_command_gets_a_timeout(self, mock_run, git, make_proc):
        """push/fetch/ls-remote must carry a hard timeout so an unreachable
        remote cannot hang the workflow forever (C-06)."""
        mock_run.return_value = make_proc()
        git.push("main")
        assert mock_run.call_args.kwargs["timeout"] == pytest.approx(60.0)

        git.fetch("origin", "main")
        assert mock_run.call_args.kwargs["timeout"] == pytest.approx(60.0)

        git.remote_has_branch("feat/x")
        assert mock_run.call_args.kwargs["timeout"] == pytest.approx(60.0)

    @mock.patch("relay.git_manager.subprocess.run")
    def test_local_command_has_no_timeout_kwarg(self, mock_run, git, make_proc):
        """Local commands keep the exact previous call shape (no timeout)."""
        mock_run.return_value = make_proc(stdout="true")
        git.is_repo()
        assert "timeout" not in mock_run.call_args.kwargs

    @mock.patch("relay.git_manager.subprocess.run")
    def test_timeout_raises_git_error(self, mock_run, git, make_proc):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git", "push"], timeout=60)
        with pytest.raises(GitError) as exc_info:
            git.push("main")
        assert "timed out after 60" in str(exc_info.value)
        assert exc_info.value.command == "git push origin main"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_missing_git_binary_raises_clear_git_error(self, mock_run, git, make_proc):
        """H-16: when `git` is not on PATH, subprocess raises FileNotFoundError
        — that raw OS error must become a clear GitError, not a traceback."""
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(GitError) as exc_info:
            git.stage_all()
        assert "git not found on PATH" in str(exc_info.value)
        assert exc_info.value.command == "git add ."


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
        assert mock_run.call_args.args[0] == ["git", "diff", "--cached", "--unified=0"]

        mock_run.return_value = make_proc(stdout="stat output")
        assert git.staged_stat() == "stat output"
        assert mock_run.call_args.args[0] == ["git", "diff", "--cached", "--stat"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_staged_diff_binary_only_true_when_all_binary(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(
            stdout="-\t-\tassets/logo.png\n-\t-\tsounds/beep.wav\n"
        )
        assert git.staged_diff_binary_only() is True
        assert mock_run.call_args.args[0] == ["git", "diff", "--cached", "--numstat"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_staged_diff_binary_only_false_when_text_present(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="10\t2\tapp.py\n-\t-\tassets/logo.png\n")
        assert git.staged_diff_binary_only() is False

    @mock.patch("relay.git_manager.subprocess.run")
    def test_staged_diff_binary_only_false_when_empty(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="")
        assert git.staged_diff_binary_only() is False

    @mock.patch("relay.git_manager.subprocess.run")
    def test_diff_range_and_stat_range(self, mock_run, git, make_proc):
        """Range diff must compare base..tip (not the index) — the diff a
        squash of commits actually needs."""
        mock_run.return_value = make_proc(stdout="range diff")
        assert git.diff_range("base123", "tip456") == "range diff"
        assert mock_run.call_args.args[0] == [
            "git", "diff", "base123..tip456", "--unified=0",
        ]

        mock_run.return_value = make_proc(stdout="range stat")
        assert git.stat_range("base123", "tip456") == "range stat"
        assert mock_run.call_args.args[0] == [
            "git", "diff", "base123..tip456", "--stat",
        ]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_pipes_message_via_stdin(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.commit("feat: subject\n\nbody line")
        assert mock_run.call_args.args[0] == ["git", "commit", "-F", "-"]
        assert mock_run.call_args.kwargs["input"] == "feat: subject\n\nbody line"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_no_verify_appends_flag(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.commit("fix: urgent", no_verify=True)
        assert mock_run.call_args.args[0] == [
            "git", "commit", "--no-verify", "-F", "-",
        ]
        assert mock_run.call_args.kwargs["input"] == "fix: urgent"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_amend_appends_flag(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.commit("fix: last commit", amend=True)
        assert mock_run.call_args.args[0] == [
            "git", "commit", "--amend", "-F", "-",
        ]
        assert mock_run.call_args.kwargs["input"] == "fix: last commit"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_amend_and_no_verify_combined(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.commit("fix: x", amend=True, no_verify=True)
        assert mock_run.call_args.args[0] == [
            "git", "commit", "--no-verify", "--amend", "-F", "-",
        ]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_create_branch(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.create_branch("status/payments")
        assert mock_run.call_args.args[0] == ["git", "checkout", "-b", "status/payments"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_checkout(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.checkout("main")
        assert mock_run.call_args.args[0] == ["git", "checkout", "main"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_delete_branch_force_by_default(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.delete_branch("orphan/feat")
        assert mock_run.call_args.args[0] == ["git", "branch", "-D", "orphan/feat"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_delete_branch_safe_flag(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.delete_branch("feat/x", force=False)
        assert mock_run.call_args.args[0] == ["git", "branch", "-d", "feat/x"]

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

    @mock.patch("relay.git_manager.subprocess.run")
    def test_fetch_remote_and_ref(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.fetch("origin", "main")
        assert mock_run.call_args.args[0] == ["git", "fetch", "origin", "main"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_fetch_defaults_to_origin_no_ref(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.fetch()
        assert mock_run.call_args.args[0] == ["git", "fetch", "origin"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_fetch_with_check_false_ignores_errors(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="couldn't resolve host")
        git.fetch("origin", "main", check=False)  # must not raise

    @mock.patch("relay.git_manager.subprocess.run")
    def test_fetch_with_check_true_raises_on_error(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="couldn't resolve host")
        with pytest.raises(GitError):
            git.fetch("origin", "main")


class TestParseRemoteUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://github.com/owner/repo.git", ("owner", "repo")),
            ("https://github.com/owner/repo", ("owner", "repo")),
            ("git@github.com:owner/repo.git", ("owner", "repo")),
            ("git@github.com:owner/repo", ("owner", "repo")),
            ("ssh://git@github.com/owner/repo.git", ("owner", "repo")),
            ("  https://github.com/Acme/Widget.git  ", ("Acme", "Widget")),
        ],
    )
    def test_supported_github_urls(self, url, expected):
        assert parse_remote_url(url) == expected

    def test_github_url_with_slash_in_owner_is_rejected(self):
        # GitHub does not nest repositories: a three-segment path is not a
        # valid GitHub remote (only GitLab supports nested groups).
        with pytest.raises(ValueError, match="owner/repo"):
            parse_remote_url("https://github.com/Owner/Sub/Repo.git")

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            "git@gitlab.com:owner/repo.git",
            "https://gitlab.com/owner/repo.git",
            "https://github.com/",
            "git@github.com:",
            "git@github.com:/repo.git",
            "not-a-remote-url",
        ],
    )
    def test_invalid_urls_raise_value_error(self, url):
        with pytest.raises(ValueError):
            parse_remote_url(url)

    @pytest.mark.parametrize(
        "url,host,owner_repo",
        [
            ("git@gitlab.com:owner/repo.git", "gitlab.com", ("owner", "repo")),
            ("https://gitlab.com/group/sub/repo.git", "gitlab.com", ("group/sub", "repo")),
            (
                "git@gitlab.example.com:team/widget.git",
                "gitlab.example.com",
                ("team", "widget"),
            ),
            ("ssh://git@gitlab.com/owner/repo.git", "gitlab.com", ("owner", "repo")),
            ("https://github.com/owner/repo.git", "github.com", ("owner", "repo")),
        ],
    )
    def test_parse_remote_detects_host(self, url, host, owner_repo):
        parsed_host, owner, repo = parse_remote(url)
        assert parsed_host == host
        assert (owner, repo) == owner_repo

    def test_parse_remote_with_empty_host_raises(self):
        """A URL-style remote with an empty host (``https://`` followed
        straight by the path) must be rejected, not silently misparsed."""
        with pytest.raises(ValueError, match="cannot extract host"):
            parse_remote("https:///owner/repo.git")


class TestRemoteHelpers:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_remote_url_returns_stripped_value(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="git@github.com:acme/widget.git\n")
        assert git.remote_url() == "git@github.com:acme/widget.git"
        assert mock_run.call_args.args[0] == ["git", "config", "--get", "remote.origin.url"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_remote_url_empty_when_unset(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=1)
        assert git.remote_url() == ""

    @mock.patch("relay.git_manager.subprocess.run")
    def test_remote_url_supports_custom_remote_name(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="https://github.com/acme/widget.git")
        git.remote_url("upstream")
        assert mock_run.call_args.args[0] == ["git", "config", "--get", "remote.upstream.url"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_latest_commit_message_returns_full_message(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="feat: add login\n\nAdds OAuth.\n")
        assert git.latest_commit_message() == "feat: add login\n\nAdds OAuth."
        assert mock_run.call_args.args[0] == ["git", "log", "-1", "--format=%B"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_latest_commit_message_empty_when_no_commits(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal: bad default revision")
        assert git.latest_commit_message() == ""

    @mock.patch("relay.git_manager.subprocess.run")
    def test_log_between_returns_subjects(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="feat: one\nfix: two\n")
        assert git.log_between("main", "feat/login") == "feat: one\nfix: two"
        assert mock_run.call_args.args[0] == ["git", "log", "--format=%s", "main..feat/login"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_log_between_empty_when_base_missing(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal: ambiguous")
        assert git.log_between("nope", "feat/login") == ""


class TestVerbose:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_verbose_prints_the_command(self, mock_run, capsys, make_proc):
        mock_run.return_value = make_proc()
        GitManager(cwd=None, verbose=True).stage_all()
        captured = capsys.readouterr()
        assert "$ git add ." in captured.out


class TestStagingEdgePaths:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_stage_files_with_no_paths_is_a_noop(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.stage_files()
        mock_run.assert_not_called()

    @mock.patch("relay.git_manager.subprocess.run")
    def test_stage_files_uses_guard_before_paths(self, mock_run, git, make_proc):
        """Paths must be handed verbatim after ``--`` so shell-special filenames
        (leading dashes, spaces) can never be misread as flags."""
        mock_run.return_value = make_proc()
        git.stage_files("app.py", "-config.txt")
        assert mock_run.call_args.args[0] == ["git", "add", "--", "app.py", "-config.txt"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_unstage_with_no_paths_is_a_noop(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.unstage()
        mock_run.assert_not_called()

    @mock.patch("relay.git_manager.subprocess.run")
    def test_unstage_with_paths(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.unstage("app.py")
        assert mock_run.call_args.args[0] == ["git", "reset", "--", "app.py"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_unstaged_changes_includes_untracked(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="?? new.txt\n")
        assert git.unstaged_changes() == ["new.txt"]
        assert mock_run.call_args.args[0] == ["git", "status", "--porcelain"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_unstaged_changes_includes_worktree_modified(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout=" M app.py\n")
        assert git.unstaged_changes() == ["app.py"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_unstaged_changes_excludes_staged_only(self, mock_run, git, make_proc):
        """A file whose change lives only in the index (``M  ``) is already
        staged, so the interactive picker must not offer it again."""
        mock_run.return_value = make_proc(stdout="M  staged.py\nA  added.py\n")
        assert git.unstaged_changes() == []

    @mock.patch("relay.git_manager.subprocess.run")
    def test_unstaged_changes_mixed_porcelain(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="?? new.txt\n M app.py\nM  staged.py\n")
        assert git.unstaged_changes() == ["new.txt", "app.py"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_add_interactive_invokes_git_add_p(self, mock_run, git, make_proc):
        """Patch mode inherits the real terminal (no capture_output), so the
        only assertable contract is the argv list and the working directory."""
        mock_run.return_value = make_proc()
        git.add_interactive()
        mock_run.assert_called_once_with(["git", "add", "-p"], cwd="/fake/repo")


class TestUndoAndSquashGuards:
    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_commits_true_when_head_resolves(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=0, stdout="abc1234\n")
        assert git.has_commits() is True
        assert mock_run.call_args.args[0] == ["git", "rev-parse", "--verify", "HEAD"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_commits_false_when_repo_empty(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal: Needed a single revision")
        assert git.has_commits() is False

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_count_returns_number(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="42\n")
        assert git.commit_count() == 42
        assert mock_run.call_args.args[0] == ["git", "rev-list", "--count", "HEAD"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_commit_count_zero_when_repo_empty(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal: bad default revision")
        assert git.commit_count() == 0

    @mock.patch("relay.git_manager.subprocess.run")
    def test_root_commit_returns_sha(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b\n")
        assert git.root_commit() == "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_root_commit_empty_when_git_fails(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal")
        assert git.root_commit() == ""

    @mock.patch("relay.git_manager.subprocess.run")
    def test_root_commit_empty_when_no_output(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=0, stdout="")
        assert git.root_commit() == ""

    @mock.patch("relay.git_manager.subprocess.run")
    def test_rev_parse_returns_full_sha(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="abc1234\n")
        assert git.rev_parse("HEAD") == "abc1234"

    @mock.patch("relay.git_manager.subprocess.run")
    def test_rev_parse_empty_when_ref_missing(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=128, stderr="fatal: ambiguous argument")
        assert git.rev_parse("nope") == ""

    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_staged_changes_true(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="app.py\n")
        assert git.has_staged_changes() is True

    @mock.patch("relay.git_manager.subprocess.run")
    def test_has_staged_changes_false_when_index_matches_head(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(stdout="")
        assert git.has_staged_changes() is False

    @mock.patch("relay.git_manager.subprocess.run")
    def test_is_ancestor_true(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=0)
        assert git.is_ancestor("base", "tip") is True

    @mock.patch("relay.git_manager.subprocess.run")
    def test_is_ancestor_false(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc(returncode=1)
        assert git.is_ancestor("tip", "base") is False

    @mock.patch("relay.git_manager.subprocess.run")
    def test_reset_soft_defaults_to_head_parent(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.reset_soft()
        assert mock_run.call_args.args[0] == ["git", "reset", "--soft", "HEAD~1"]

    @mock.patch("relay.git_manager.subprocess.run")
    def test_reset_soft_custom_target(self, mock_run, git, make_proc):
        mock_run.return_value = make_proc()
        git.reset_soft("HEAD~3")
        assert mock_run.call_args.args[0] == ["git", "reset", "--soft", "HEAD~3"]
