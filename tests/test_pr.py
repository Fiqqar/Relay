"""Unit tests for `relay pr` (relay/pr.py)."""
from unittest import mock

import pytest

from relay.bitbucket import BitbucketError
from relay.bitbucket import DuplicatePullRequestError as BitbucketDuplicateError
from relay.errors import RelayError
from relay.github import DuplicatePullRequestError, GitHubError
from relay.gitlab import DuplicateMergeRequestError, GitLabError
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
        has_branch=True,
    ):
        self._is_repo = is_repo
        self._remote = remote
        self._branch = branch
        self._commit = commit
        self._log = log
        self._has_branch = has_branch
        self.fetch_calls = []
        self.log_calls = []

    def is_repo(self):
        return self._is_repo

    def remote_url(self):
        return self._remote

    def current_branch(self):
        return self._branch

    def remote_has_branch(self, branch):
        return self._has_branch

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
            title="feat: add login", head="feat/login", base="main",
            body=mock.ANY, draft=False
        )
        out = capsys.readouterr().out
        assert "PR #12" in out
        assert "pull/12" in out

    def test_opens_draft_pr_when_requested(self, fake_client):
        run_pr(git=FakeGit(), draft=True)
        args = fake_client.return_value.open_pull.call_args.kwargs
        assert args["draft"] is True

    def test_pr_is_not_draft_by_default(self, fake_client):
        run_pr(git=FakeGit())
        args = fake_client.return_value.open_pull.call_args.kwargs
        assert args["draft"] is False

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

    def test_unpushed_branch_raises_with_push_hint(self, fake_client):
        with pytest.raises(RelayError) as exc_info:
            run_pr(git=FakeGit(has_branch=False))
        assert "git push -u origin feat/login" in str(exc_info.value)
        fake_client.return_value.open_pull.assert_not_called()

    def test_pushed_branch_proceeds_to_pr(self, fake_client):
        assert run_pr(git=FakeGit(has_branch=True)) == 0
        fake_client.return_value.open_pull.assert_called_once()

    def test_unrecognized_host_raises(self, fake_client):
        with pytest.raises(RelayError):
            run_pr(git=FakeGit(remote="git@myforge.example.com:acme/widget.git"))

    def test_invalid_base_branch_rejected(self, fake_client):
        with pytest.raises(RelayError, match="invalid base branch"):
            run_pr(git=FakeGit(), base="--upload-pack=evil")
        with pytest.raises(RelayError, match="invalid base branch"):
            run_pr(git=FakeGit(), base="..evil")
        fake_client.return_value.open_pull.assert_not_called()


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

    def test_refuses_file_scheme_url(self, fake_client, capsys):
        fake_client.return_value.open_pull.return_value = {
            "number": 12,
            "html_url": "file:///etc/passwd",
        }
        with mock.patch("relay.pr.webbrowser.open") as browser:
            assert run_pr(git=FakeGit(), open_browser=True) == 0
        browser.assert_not_called()
        assert "refusing to open non-http(s) URL" in capsys.readouterr().out

    def test_refuses_javascript_scheme_url(self, fake_client, capsys):
        fake_client.return_value.open_pull.return_value = {
            "number": 12,
            "html_url": "javascript:alert(1)",
        }
        with mock.patch("relay.pr.webbrowser.open") as browser:
            assert run_pr(git=FakeGit(), open_browser=True) == 0
        browser.assert_not_called()
        assert "refusing to open non-http(s) URL" in capsys.readouterr().out

    def test_safe_open_browser_helper_unit(self):
        from relay.pr import _safe_open_browser

        with mock.patch("relay.pr.webbrowser.open") as browser:
            assert _safe_open_browser("https://example.com") is True
            browser.assert_called_once_with("https://example.com")

        with mock.patch("relay.pr.webbrowser.open") as browser:
            assert _safe_open_browser("http://example.com") is True
            browser.assert_called_once_with("http://example.com")

        with mock.patch("relay.pr.webbrowser.open") as browser:
            assert _safe_open_browser("file:///tmp/malicious") is False
            assert _safe_open_browser("") is False
            assert _safe_open_browser("ssh://git@github.com") is False
            browser.assert_not_called()


class TestGitLab:
    @pytest.fixture(autouse=True)
    def clean_relay_env(self, monkeypatch):
        """The trust boundary reads the environment, so each test starts clean
        (a stray RELAY_CONFIG / RELAY_TRUSTED_GITLAB_HOSTS on the host machine
        must not leak into the assertions)."""
        from relay import config

        monkeypatch.delenv("RELAY_CONFIG", raising=False)
        monkeypatch.delenv("RELAY_TRUSTED_GITLAB_HOSTS", raising=False)
        config._RAW_CACHE.clear()

    @pytest.fixture
    def fake_gitlab(self):
        with mock.patch("relay.pr.GitLabClient") as client_cls:
            client_cls.return_value.find_open_mr.return_value = None
            client_cls.return_value.open_merge_request.return_value = {
                "iid": 42,
                "web_url": "https://gitlab.com/acme/widget/-/merge_requests/42",
            }
            yield client_cls

    def test_routes_https_gitlab_remote_to_gitlab(self, fake_gitlab, capsys):
        git = FakeGit(remote="https://gitlab.com/acme/widget.git")
        assert run_pr(git=git) == 0
        fake_gitlab.assert_called_once_with("gitlab.com", "acme/widget", verbose=False)
        out = capsys.readouterr().out
        assert "MR #42" in out
        assert "merge_requests/42" in out

    def test_routes_ssh_gitlab_remote(self, fake_gitlab):
        git = FakeGit(remote="git@gitlab.com:acme/widget.git")
        run_pr(git=git)
        fake_gitlab.assert_called_once_with("gitlab.com", "acme/widget", verbose=False)

    def test_sends_mr_payload(self, fake_gitlab):
        run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git"))
        fake_gitlab.return_value.open_merge_request.assert_called_once_with(
            title="feat: add login", source_branch="feat/login",
            target_branch="main", description=mock.ANY, draft=False
        )

    def test_mr_draft_forwarded(self, fake_gitlab):
        run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git"), draft=True)
        args = fake_gitlab.return_value.open_merge_request.call_args.kwargs
        assert args["draft"] is True

    def test_custom_mr_base_forwarded(self, fake_gitlab):
        run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git"), base="develop")
        args = fake_gitlab.return_value.open_merge_request.call_args.kwargs
        assert args["target_branch"] == "develop"

    def test_existing_mr_skips_creation(self, fake_gitlab, capsys):
        fake_gitlab.return_value.find_open_mr.return_value = {
            "iid": 7,
            "web_url": "https://gitlab.com/acme/widget/-/merge_requests/7",
        }
        assert run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git")) == 0
        fake_gitlab.return_value.open_merge_request.assert_not_called()
        assert "PR already exists: https://gitlab.com/acme/widget/-/merge_requests/7" in capsys.readouterr().out

    def test_mr_duplicate_post_safety_net(self, fake_gitlab, capsys):
        find = fake_gitlab.return_value.find_open_mr
        find.side_effect = [None, {"web_url": "https://gitlab.com/acme/widget/-/merge_requests/7"}]
        fake_gitlab.return_value.open_merge_request.side_effect = DuplicateMergeRequestError(
            "another merge request already exists", status=409, body="already exists"
        )
        assert run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git")) == 0
        assert find.call_count == 2

    def test_mr_400_returns_nonzero(self, fake_gitlab, capsys):
        fake_gitlab.return_value.open_merge_request.side_effect = GitLabError(
            "GitLab API error 400: bad request", status=400, payload={}, detail="bad request"
        )
        assert run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git")) == 1
        assert "Cannot open MR: bad request" in capsys.readouterr().out

    def test_mr_500_propagates(self, fake_gitlab):
        fake_gitlab.return_value.open_merge_request.side_effect = GitLabError(
            "GitLab API error 500: boom", status=500, payload={}, detail="boom"
        )
        with pytest.raises(GitLabError):
            run_pr(git=FakeGit(remote="git@gitlab.com:acme/widget.git"))

    def test_self_hosted_gitlab_refused_without_trust(self, fake_gitlab):
        """The host comes from `origin` (attacker-controllable), so an untrusted
        host must be refused before any token is read or request is made."""
        git = FakeGit(remote="git@gitlab.example.com:group/sub/widget.git")
        with pytest.raises(RelayError, match="RELAY_TRUSTED_GITLAB_HOSTS"):
            run_pr(git=git)
        fake_gitlab.assert_not_called()

    def test_self_hosted_gitlab_allowed_when_env_trusted(
        self, fake_gitlab, monkeypatch
    ):
        monkeypatch.setenv("RELAY_TRUSTED_GITLAB_HOSTS", "gitlab.example.com")
        git = FakeGit(remote="git@gitlab.example.com:group/sub/widget.git")
        assert run_pr(git=git) == 0
        fake_gitlab.assert_called_once_with(
            "gitlab.example.com", "group/sub/widget", verbose=False
        )

    def test_self_hosted_trust_match_is_case_insensitive(
        self, fake_gitlab, monkeypatch
    ):
        monkeypatch.setenv("RELAY_TRUSTED_GITLAB_HOSTS", "GitLab.Example.COM")
        git = FakeGit(remote="git@gitlab.example.com:group/sub/widget.git")
        assert run_pr(git=git) == 0
        fake_gitlab.assert_called_once_with(
            "gitlab.example.com", "group/sub/widget", verbose=False
        )

    def test_self_hosted_gitlab_config_file_is_ignored(
        self, fake_gitlab, monkeypatch, tmp_path
    ):
        """Config-file trusted hosts must be ignored (env-only)."""
        from relay import config

        p = tmp_path / "config.toml"
        p.write_text(
            '[relay]\ntrusted_gitlab_hosts = ["gitlab.example.com"]\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("RELAY_CONFIG", str(p))
        config._RAW_CACHE.clear()
        git = FakeGit(remote="git@gitlab.example.com:group/sub/widget.git")
        with pytest.raises(RelayError, match="RELAY_TRUSTED_GITLAB_HOSTS"):
            run_pr(git=git)
        fake_gitlab.assert_not_called()


class TestBitbucket:
    @pytest.fixture(autouse=True)
    def clean_relay_env(self, monkeypatch):
        """A stray RELAY_CONFIG / RELAY_TRUSTED_GITLAB_HOSTS on the host machine
        must not leak into the assertions."""
        from relay import config

        monkeypatch.delenv("RELAY_CONFIG", raising=False)
        monkeypatch.delenv("RELAY_TRUSTED_GITLAB_HOSTS", raising=False)
        config._RAW_CACHE.clear()

    @pytest.fixture
    def fake_bitbucket(self):
        with mock.patch("relay.pr.BitbucketClient") as client_cls:
            client_cls.return_value.find_open_pull.return_value = None
            client_cls.return_value.open_pull.return_value = {
                "id": 77,
                "links": {
                    "html": {"href": "https://bitbucket.org/acme/widget/pull-requests/77"}
                },
            }
            yield client_cls

    def test_routes_https_bitbucket_remote_to_bitbucket(self, fake_bitbucket, capsys):
        git = FakeGit(remote="https://bitbucket.org/acme/widget.git")
        assert run_pr(git=git) == 0
        fake_bitbucket.assert_called_once_with("acme", "widget", verbose=False)
        out = capsys.readouterr().out
        assert "PR #77" in out
        assert "bitbucket.org/acme/widget/pull-requests/77" in out

    def test_routes_ssh_bitbucket_remote(self, fake_bitbucket):
        git = FakeGit(remote="git@bitbucket.org:acme/widget.git")
        run_pr(git=git)
        fake_bitbucket.assert_called_once_with("acme", "widget", verbose=False)

    def test_sends_bitbucket_payload(self, fake_bitbucket):
        run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git"))
        fake_bitbucket.return_value.open_pull.assert_called_once_with(
            title="feat: add login", source_branch="feat/login",
            destination_branch="main", description=mock.ANY, draft=False
        )

    def test_bitbucket_draft_forwarded(self, fake_bitbucket):
        run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git"), draft=True)
        args = fake_bitbucket.return_value.open_pull.call_args.kwargs
        assert args["draft"] is True

    def test_custom_bitbucket_base_forwarded(self, fake_bitbucket):
        run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git"), base="develop")
        args = fake_bitbucket.return_value.open_pull.call_args.kwargs
        assert args["destination_branch"] == "develop"

    def test_existing_bitbucket_pr_skips_creation(self, fake_bitbucket, capsys):
        fake_bitbucket.return_value.find_open_pull.return_value = {
            "links": {"html": {"href": "https://bitbucket.org/acme/widget/pull-requests/9"}}
        }
        assert run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git")) == 0
        fake_bitbucket.return_value.open_pull.assert_not_called()
        assert "PR already exists: https://bitbucket.org/acme/widget/pull-requests/9" in capsys.readouterr().out

    def test_existing_bitbucket_pr_opens_browser(self, fake_bitbucket):
        fake_bitbucket.return_value.find_open_pull.return_value = {
            "links": {"html": {"href": "https://bitbucket.org/acme/widget/pull-requests/9"}}
        }
        with mock.patch("relay.pr.webbrowser.open") as browser:
            run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git"), open_browser=True)
        browser.assert_called_once_with("https://bitbucket.org/acme/widget/pull-requests/9")

    def test_bitbucket_duplicate_post_safety_net(self, fake_bitbucket, capsys):
        find = fake_bitbucket.return_value.find_open_pull
        find.side_effect = [None, {"links": {"html": {"href": "https://bitbucket.org/acme/widget/pull-requests/7"}}}]
        fake_bitbucket.return_value.open_pull.side_effect = BitbucketDuplicateError(
            "already exists", status=400, body="already exists"
        )
        assert run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git")) == 0
        assert find.call_count == 2

    def test_bitbucket_400_returns_nonzero(self, fake_bitbucket, capsys):
        fake_bitbucket.return_value.open_pull.side_effect = BitbucketError(
            "Bitbucket API error 400: Invalid source branch", status=400,
            payload={}, detail="Invalid source branch"
        )
        assert run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git")) == 1
        assert "Cannot open PR: Invalid source branch" in capsys.readouterr().out

    def test_bitbucket_500_propagates(self, fake_bitbucket):
        fake_bitbucket.return_value.open_pull.side_effect = BitbucketError(
            "Bitbucket API error 500: boom", status=500, payload=None, detail="boom"
        )
        with pytest.raises(BitbucketError):
            run_pr(git=FakeGit(remote="git@bitbucket.org:acme/widget.git"))


# ---- coverage: pr helpers (moved from test_coverage_95) ---------------------

def test_safe_open_browser_rejects():
    from relay.pr import _safe_open_browser
    assert _safe_open_browser("") is False
    assert _safe_open_browser("file:///etc/passwd") is False
    assert _safe_open_browser("ftp://example.com") is False


def test_host_web_base():
    from relay.pr import _host_web_base
    assert _host_web_base("github.com", "o", "r") == "https://github.com/o/r/pulls"
    assert _host_web_base("bitbucket.org", "o", "r") == "https://bitbucket.org/o/r/pull-requests"
    assert _host_web_base("gitlab.example.com", "o", "r") == "https://gitlab.example.com/o/r/-/merge_requests"


def test_pr_web_url():
    from relay.pr import _pr_web_url
    assert _pr_web_url("github.com", "o", "r", 42) == "https://github.com/o/r/pull/42"
    assert _pr_web_url("bitbucket.org", "o", "r", 5) == "https://bitbucket.org/o/r/pull-requests/5"
    assert _pr_web_url("gitlab.com", "o", "r", 7) == "https://gitlab.com/o/r/-/merge_requests/7"


def test_existing_url_none():
    from relay.pr import _existing_url
    assert _existing_url("github.com", "o", "r", None) == "https://github.com/o/r/pulls"


def test_existing_url_with_links():
    from relay.pr import _existing_url
    existing = {"links": {"html": {"href": "https://bitbucket.org/o/r/pull-requests/9"}}}
    assert _existing_url("bitbucket.org", "o", "r", existing) == "https://bitbucket.org/o/r/pull-requests/9"
    existing2 = {"html_url": "https://github.com/o/r/pull/1"}
    assert _existing_url("github.com", "o", "r", existing2) == "https://github.com/o/r/pull/1"
    existing3 = {"number": 10}
    assert _existing_url("github.com", "o", "r", existing3) == "https://github.com/o/r/pull/10"
    existing4 = {"iid": 3}
    assert _existing_url("gitlab.com", "o", "r", existing4) == "https://gitlab.com/o/r/-/merge_requests/3"


def test_safe_open_browser_allows_https():
    from relay.pr import _safe_open_browser
    with mock.patch("relay.pr.webbrowser.open", return_value=True) as wb:
        assert _safe_open_browser("https://github.com/o/r/pull/1") is True
        wb.assert_called_once()


def test_derive_title_with_ai_provider():
    from relay.pr import _resolve_title

    git = FakeGit()
    git.latest_commit_message = lambda: ""
    git.staged_diff = lambda: "diff"
    git.staged_stat = lambda: "stat"
    git.current_branch = lambda: "main"
    ai = mock.MagicMock()
    ai.generate.return_value = "feat: generated title"
    title = _resolve_title(git, title=None, provider=ai)
    assert title == "feat: generated title"


def test_build_body_empty():
    from relay.pr import _build_body

    git = FakeGit()
    git.log_between = lambda base, head: ""
    body = _build_body(git, base="main", head="feat")
    assert body == ""

