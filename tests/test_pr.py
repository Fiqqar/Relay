"""Unit tests for `relay pr` (relay/pr.py)."""
from unittest import mock

import pytest

from relay.errors import RelayError
from relay.github import DuplicatePullRequestError, GitHubError
from relay.pr import run_pr


class FakeGit:
    """Stand-in for GitManager with controllable results."""

    def __init__(
        self,
        is_repo=True,
        remote="git@github.com:acme/widget.git",
        branch="feat/login",
        commit="feat: add login\n\nAdds OAuth.",
        log="feat: add login",
    ):
        self._is_repo = is_repo
        self._remote = remote
        self._branch = branch
        self._commit = commit
        self._log = log
        self.fetch_calls = []
        self.log_calls = []

    def is_repo(self):
        return self._is_repo

    def remote_url(self):
        return self._remote

    def current_branch(self):
        return self._branch

    def latest_commit_message(self):
        return self._commit

    def log_between(self, base, head):
        self.log_calls.append((base, head))
        return self._log

    def staged_diff(self):
        return "diff output"

    def staged_stat(self):
        return " 1 file changed\n"

    def fetch(self, remote, ref="", check=True):
        self.fetch_calls.append((remote, ref, check))
        return None


@pytest.fixture
def fake_client():
    with mock.patch("relay.pr.GitHubClient") as client_cls:
        client_cls.return_value.find_open_pr.return_value = None
        client_cls.return_value.open_pull.return_value = {
            "number": 12,
            "html_url": "https://github.com/acme/widget/pull/12",
        }
        yield client_cls


class TestRunPr:
    def test_opens_pr_with_commit_title(self, fake_client, capsys):
        assert run_pr(git=FakeGit()) == 0
        fake_client.return_value.open_pull.assert_called_once_with(
            title="feat: add login", head="feat/login", base="main", body=mock.ANY
        )
        out = capsys.readouterr().out
        assert "PR #12" in out
        assert "pull/12" in out

    def test_explicit_title_wins(self, fake_client):
        run_pr(git=FakeGit(), title="My PR")
        args = fake_client.return_value.open_pull.call_args.kwargs
        assert args["title"] == "My PR"

    def test_custom_base_forwarded(self, fake_client):
        run_pr(git=FakeGit(), base="develop")
        args = fake_client.return_value.open_pull.call_args.kwargs
        assert args["base"] == "develop"

    def test_owner_repo_parsed_from_ssh_remote(self, fake_client):
        run_pr(git=FakeGit(remote="git@github.com:owner/repo.git"))
        fake_client.assert_called_once_with("owner", "repo", verbose=False)

    def test_owner_repo_parsed_from_https_remote(self, fake_client):
        run_pr(git=FakeGit(remote="https://github.com/acme/widget.git"))
        fake_client.assert_called_once_with("acme", "widget", verbose=False)

    def test_body_lists_commits(self, fake_client):
        run_pr(git=FakeGit(log="feat: one\nfix: two"))
        body = fake_client.return_value.open_pull.call_args.kwargs["body"]
        assert "- feat: one" in body
        assert "- fix: two" in body

    def test_body_compares_against_remote_base(self, fake_client):
        git = FakeGit()
        run_pr(git=git)
        assert git.log_calls == [("origin/main", "feat/login")]
        body = fake_client.return_value.open_pull.call_args.kwargs["body"]
        assert "origin/main" in body

    def test_body_uses_custom_remote_base(self, fake_client):
        git = FakeGit()
        run_pr(git=git, base="develop")
        assert git.log_calls == [("origin/develop", "feat/login")]

    def test_fetches_base_before_building_body(self, fake_client):
        git = FakeGit()
        run_pr(git=git)
        assert ("origin", "main", False) in git.fetch_calls

    def test_fetch_uses_custom_base(self, fake_client):
        git = FakeGit()
        run_pr(git=git, base="develop")
        assert ("origin", "develop", False) in git.fetch_calls

    def test_ai_title_when_no_commit(self, fake_client):
        class FakeProvider:
            def generate(self, diff, stat, branch):
                return "Generated title from diff"
        run_pr(git=FakeGit(commit=""), provider=FakeProvider())
        args = fake_client.return_value.open_pull.call_args.kwargs
        assert args["title"] == "Generated title from diff"

    def test_no_title_sources_raises(self, fake_client):
        with pytest.raises(RelayError) as exc_info:
            run_pr(git=FakeGit(commit=""))
        assert "--title" in str(exc_info.value)
        fake_client.return_value.open_pull.assert_not_called()

    def test_not_a_repo_raises(self, fake_client):
        with pytest.raises(RelayError) as exc_info:
            run_pr(git=FakeGit(is_repo=False))
        assert "not a git repository" in str(exc_info.value)

    def test_no_remote_raises(self, fake_client):
        with pytest.raises(RelayError) as exc_info:
            run_pr(git=FakeGit(remote=""))
        assert "origin" in str(exc_info.value)

    def test_detached_head_raises(self, fake_client):
        with pytest.raises(RelayError) as exc_info:
            run_pr(git=FakeGit(branch=""))
        assert "detached" in str(exc_info.value)

    def test_non_github_remote_raises(self, fake_client):
        with pytest.raises(RelayError):
            run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git"))


class TestAntiDuplicate:
    def test_queries_open_prs_for_head_branch(self, fake_client):
        run_pr(git=FakeGit())
        fake_client.return_value.find_open_pr.assert_called_once_with(head="feat/login")

    def test_existing_pr_skips_creation_and_exits_zero(self, fake_client, capsys):
        fake_client.return_value.find_open_pr.return_value = {
            "number": 9,
            "html_url": "https://github.com/acme/widget/pull/9",
        }
        assert run_pr(git=FakeGit()) == 0
        fake_client.return_value.open_pull.assert_not_called()
        out = capsys.readouterr().out
        assert "PR already exists" in out
        assert "acme/widget/pull/9" in out

    def test_existing_pr_opens_browser_when_requested(self, fake_client):
        fake_client.return_value.find_open_pr.return_value = {
            "number": 9,
            "html_url": "https://github.com/acme/widget/pull/9",
        }
        with mock.patch("relay.pr.webbrowser.open") as browser:
            run_pr(git=FakeGit(), open_browser=True)
        browser.assert_called_once_with("https://github.com/acme/widget/pull/9")


class TestDuplicate422SafetyNet:
    def test_post_422_recovers_and_reports_existing_pr(self, fake_client, capsys):
        # The GET missed it (returns None), but the POST is rejected as a duplicate.
        find = fake_client.return_value.find_open_pr
        find.side_effect = [None, {"number": 9, "html_url": "https://github.com/acme/widget/pull/9"}]
        fake_client.return_value.open_pull.side_effect = DuplicatePullRequestError(
            "a pull request already exists", status=422, body="already exists"
        )

        assert run_pr(git=FakeGit()) == 0
        assert find.call_count == 2
        assert "PR already exists: https://github.com/acme/widget/pull/9" in capsys.readouterr().out

    def test_post_422_opens_browser_for_existing_pr(self, fake_client):
        find = fake_client.return_value.find_open_pr
        find.side_effect = [None, {"html_url": "https://github.com/acme/widget/pull/9"}]
        fake_client.return_value.open_pull.side_effect = DuplicatePullRequestError(
            "already exists", status=422
        )
        with mock.patch("relay.pr.webbrowser.open") as browser:
            run_pr(git=FakeGit(), open_browser=True)
        browser.assert_called_once_with("https://github.com/acme/widget/pull/9")

    def test_post_422_without_lookup_result_falls_back_to_pulls_page(self, fake_client, capsys):
        find = fake_client.return_value.find_open_pr
        find.side_effect = [None, None]  # GET missed it AND the re-query finds nothing
        fake_client.return_value.open_pull.side_effect = DuplicatePullRequestError(
            "already exists", status=422
        )
        assert run_pr(git=FakeGit()) == 0
        assert "PR already exists: https://github.com/acme/widget/pulls" in capsys.readouterr().out

    def test_post_422_uses_git_verbose_for_client(self, fake_client):
        fake_client.return_value.find_open_pr.return_value = None
        fake_client.return_value.open_pull.return_value = {
            "number": 12,
            "html_url": "https://github.com/acme/widget/pull/12",
        }
        run_pr(git=FakeGit(), verbose=True)
        fake_client.assert_called_once_with("acme", "widget", verbose=True)


class TestCannotOpenPr:
    def test_no_commits_422_prints_reason_and_exits_nonzero(self, fake_client, capsys):
        fake_client.return_value.open_pull.side_effect = GitHubError(
            "GitHub API error 422: No commits between main and dev",
            status=422,
            payload={"message": "No commits between main and dev"},
            detail="No commits between main and dev",
        )
        assert run_pr(git=FakeGit()) == 1
        assert "[relay] Cannot open PR: No commits between main and dev" in capsys.readouterr().out

    def test_merged_or_closed_422_prints_reason(self, fake_client, capsys):
        fake_client.return_value.open_pull.side_effect = GitHubError(
            "GitHub API error 422: Validation Failed",
            status=422,
            payload={"message": "Validation Failed"},
            detail="Validation Failed",
        )
        assert run_pr(git=FakeGit()) == 1
        assert "[relay] Cannot open PR: Validation Failed" in capsys.readouterr().out

    def test_non_422_errors_propagate(self, fake_client):
        fake_client.return_value.open_pull.side_effect = GitHubError(
            "GitHub API error 500: boom", status=500, payload=None, detail="boom"
        )
        with pytest.raises(GitHubError):
            run_pr(git=FakeGit())


class TestOpenBrowser:
    def test_created_pr_opens_browser_when_requested(self, fake_client):
        with mock.patch("relay.pr.webbrowser.open") as browser:
            run_pr(git=FakeGit(), open_browser=True)
        browser.assert_called_once_with("https://github.com/acme/widget/pull/12")

    def test_created_pr_does_not_open_browser_by_default(self, fake_client):
        with mock.patch("relay.pr.webbrowser.open") as browser:
            run_pr(git=FakeGit())
        browser.assert_not_called()
