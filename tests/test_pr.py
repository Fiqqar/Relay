"""Unit tests for `relay pr` (relay/pr.py)."""
from unittest import mock

import pytest

from relay.errors import RelayError
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
        fake_client.assert_called_once_with("owner", "repo")

    def test_owner_repo_parsed_from_https_remote(self, fake_client):
        run_pr(git=FakeGit(remote="https://github.com/acme/widget.git"))
        fake_client.assert_called_once_with("acme", "widget")

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
