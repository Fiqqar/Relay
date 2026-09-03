"""Unit tests for relay/github.py — the zero-dependency GitHub client.

urllib.request.urlopen is mocked so no real network request is ever made; the
suite stays hermetic and offline-safe.
"""
import io
import json
import os
import urllib.error
import urllib.parse
from unittest import mock

import pytest

from relay.github import (
    DuplicatePullRequestError,
    GitHubClient,
    GitHubError,
    github_token,
)


class TestGithubToken:
    def test_prefers_github_token_over_gh_token(self):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "a", "GH_TOKEN": "b"}):
            assert github_token() == "a"

    def test_falls_back_to_gh_token(self):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": "b"}):
            assert github_token() == "b"

    def test_empty_when_neither_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert github_token() is None


class TestPullsUrl:
    def test_pulls_url_uses_owner_and_repo(self):
        assert GitHubClient("acme", "widget").pulls_url == (
            "https://api.github.com/repos/acme/widget/pulls"
        )

    def test_pulls_url_quotes_special_characters(self):
        assert GitHubClient("owner with space", "repo/slash").pulls_url == (
            "https://api.github.com/repos/owner%20with%20space/repo%2Fslash/pulls"
        )


class TestFindOpenPr:
    @mock.patch("relay.github.urllib.request.urlopen")
    def test_queries_pulls_with_owner_head_and_state(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            [{"number": 9, "html_url": "https://github.com/acme/widget/pull/9"}]
        ).encode()

        client = GitHubClient("acme", "widget", token="secret")
        result = client.find_open_pr(head="feat/login")

        request = mock_urlopen.call_args.args[0]
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == "Bearer secret"
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        assert query["head"] == ["acme:feat/login"]
        assert query["state"] == ["open"]
        assert result["number"] == 9

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_returns_none_when_no_open_pr(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        client = GitHubClient("acme", "widget", token="t")
        assert client.find_open_pr(head="feat/login") is None

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_returns_none_when_response_is_dict(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b'{"message": "error"}'
        client = GitHubClient("acme", "widget", token="t")
        assert client.find_open_pr(head="feat/login") is None

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_owner_head_uses_client_owner_by_default(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        client = GitHubClient("acme", "widget", token="t")
        client.find_open_pr(head="feat/login")
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(mock_urlopen.call_args.args[0].full_url).query
        )
        assert query["head"] == ["acme:feat/login"]

    def test_raises_when_token_missing(self):
        with mock.patch("relay.github.github_token", return_value=None):
            client = GitHubClient("acme", "widget")
            with pytest.raises(GitHubError) as exc_info:
                client.find_open_pr(head="feat/login")
        assert "GITHUB_TOKEN" in str(exc_info.value)

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_raises_with_status_on_http_error(self, mock_urlopen):
        error = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad creds"}')
        )
        mock_urlopen.side_effect = error
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.find_open_pr(head="feat/login")
        assert exc_info.value.status == 401

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_error_body_read_is_capped_at_10kib(self, mock_urlopen):
        """M-04: a pathological error body must not be slurped in full."""
        from relay.github import _MAX_ERROR_BODY_BYTES

        body = b"x" * (_MAX_ERROR_BODY_BYTES + 500)
        error = urllib.error.HTTPError(
            "url", 500, "Internal Server Error", {}, io.BytesIO(body)
        )
        mock_urlopen.side_effect = error
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.find_open_pr(head="feat/login")
        assert len(exc_info.value.body) <= _MAX_ERROR_BODY_BYTES

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_oversized_success_response_is_rejected(self, mock_urlopen):
        """A healthy-looking but huge 2xx body must not be slurped whole."""
        from relay.github import MAX_RESPONSE_BYTES

        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b"x" * (MAX_RESPONSE_BYTES + 1)
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError, match="byte limit"):
            client.find_open_pr(head="feat/login")

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_strips_whitespace_from_head_and_owner(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        client = GitHubClient("acme", "widget", token="t")
        client.find_open_pr(head="  feat/login  ", owner=" acme ")
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(mock_urlopen.call_args.args[0].full_url).query
        )
        assert query["head"] == ["acme:feat/login"]


class TestDuplicateFallback:
    @mock.patch("relay.github.urllib.request.urlopen")
    def test_open_pull_raises_duplicate_error_on_422_already_exists(self, mock_urlopen):
        body = json.dumps(
            {
                "message": "Validation Failed",
                "errors": [
                    {
                        "resource": "PullRequest",
                        "field": "head",
                        "message": "A pull request already exists for acme:feat/login.",
                    }
                ],
            }
        )
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 422, "Unprocessable Entity", {}, io.BytesIO(body.encode())
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(DuplicatePullRequestError) as exc_info:
            client.open_pull(title="x", head="feat/login")
        assert exc_info.value.status == 422
        assert "already exists" in exc_info.value.body

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_open_pull_keeps_plain_error_for_other_422s(self, mock_urlopen):
        body = json.dumps({"message": "Validation Failed", "errors": []})
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 422, "Unprocessable Entity", {}, io.BytesIO(body.encode())
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.open_pull(title="x", head="feat/login")
        assert type(exc_info.value) is GitHubError  # not the duplicate subclass
        assert str(exc_info.value) == "GitHub API error 422: Validation Failed"
        assert exc_info.value.reason == "Validation Failed"


class TestErrorDetail:
    @mock.patch("relay.github.urllib.request.urlopen")
    def test_top_level_message_is_surfaced(self, mock_urlopen):
        body = json.dumps({"message": "No commits between main and fix/pr-bug-fix"})
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 422, "Unprocessable Entity", {}, io.BytesIO(body.encode())
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.open_pull(title="x", head="fix/pr-bug-fix")

        error = exc_info.value
        assert str(error) == "GitHub API error 422: No commits between main and fix/pr-bug-fix"
        assert error.reason == "No commits between main and fix/pr-bug-fix"
        assert error.status == 422
        assert error.payload == {"message": "No commits between main and fix/pr-bug-fix"}

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_errors_list_is_formatted_in_message(self, mock_urlopen):
        body = json.dumps(
            {
                "message": "Validation Failed",
                "errors": [{"message": "A pull request already exists for acme:feat/login."}],
            }
        )
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 422, "Unprocessable Entity", {}, io.BytesIO(body.encode())
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.open_pull(title="x", head="feat/login")

        error = exc_info.value
        assert error.reason == (
            "Validation Failed (A pull request already exists for acme:feat/login.)"
        )
        assert "Validation Failed (A pull request already exists for acme:feat/login.)" in str(error)

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_non_json_body_falls_back_to_raw_text(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 500, "Internal Server Error", {}, io.BytesIO(b"oops")
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.open_pull(title="x", head="feat/login")

        error = exc_info.value
        assert str(error) == "GitHub API error 500: oops"
        assert error.reason == "oops"
        assert error.payload is None

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_duplicate_error_reason_exposed(self, mock_urlopen):
        body = json.dumps(
            {
                "message": "Validation Failed",
                "errors": [{"message": "A pull request already exists for acme:feat/login."}],
            }
        )
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 422, "Unprocessable Entity", {}, io.BytesIO(body.encode())
        )
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(DuplicatePullRequestError) as exc_info:
            client.open_pull(title="x", head="feat/login")
        assert exc_info.value.reason == (
            "Validation Failed (A pull request already exists for acme:feat/login.)"
        )
        assert exc_info.value.payload == json.loads(body)


class TestVerboseLogging:
    @mock.patch("relay.github.urllib.request.urlopen")
    def test_prints_get_and_post_endpoints(self, mock_urlopen, capsys):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        client = GitHubClient("acme", "widget", token="t", verbose=True)
        client.find_open_pr(head="feat/login")
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        client.open_pull(title="x", head="feat/login")

        out = capsys.readouterr().out
        assert "[relay] github GET" in out
        assert "pulls?head=acme%3Afeat%2Flogin&state=open" in out
        assert "[relay] github POST" in out
        assert "repos/acme/widget/pulls" in out

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_does_not_log_when_quiet(self, mock_urlopen, capsys):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        client = GitHubClient("acme", "widget", token="t", verbose=False)
        client.open_pull(title="x", head="feat/login")
        assert capsys.readouterr().out == ""


class TestOpenPull:
    @mock.patch("relay.github.urllib.request.urlopen")
    def test_posts_payload_to_pulls_endpoint(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"number": 7, "html_url": "https://github.com/acme/widget/pull/7"}
        ).encode()

        client = GitHubClient("acme", "widget", token="secret")
        result = client.open_pull(title="Add login", head="feat/login", base="main", body="Details")

        request = mock_urlopen.call_args.args[0]
        assert request.full_url == "https://api.github.com/repos/acme/widget/pulls"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer secret"
        assert request.headers.get("User-agent") == "relay-cli"
        assert json.loads(request.data) == {
            "title": "Add login",
            "head": "feat/login",
            "base": "main",
            "body": "Details",
            "draft": False,
        }
        assert result["number"] == 7

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_open_pull_defaults_draft_to_false(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        GitHubClient("acme", "widget", token="t").open_pull(title="x", head="h")
        request = mock_urlopen.call_args.args[0]
        assert json.loads(request.data)["draft"] is False

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_open_pull_forwards_draft_true(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        GitHubClient("acme", "widget", token="t").open_pull(
            title="x", head="h", draft=True
        )
        request = mock_urlopen.call_args.args[0]
        assert json.loads(request.data)["draft"] is True

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_base_defaults_to_main(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        GitHubClient("acme", "widget", token="t").open_pull(title="x", head="h")
        request = mock_urlopen.call_args.args[0]
        assert json.loads(request.data)["base"] == "main"

    def test_raises_when_token_missing(self):
        with mock.patch("relay.github.github_token", return_value=None):
            client = GitHubClient("acme", "widget")
            with pytest.raises(GitHubError) as exc_info:
                client.open_pull(title="x", head="h")
        assert "GITHUB_TOKEN" in str(exc_info.value)

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_raises_with_status_on_http_error(self, mock_urlopen):
        error = urllib.error.HTTPError(
            "url", 422, "Unprocessable Entity", {}, io.BytesIO(b'{"message":"exists"}')
        )
        mock_urlopen.side_effect = error
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.open_pull(title="x", head="h")
        assert exc_info.value.status == 422
        assert '"message":"exists"' in exc_info.value.body

    @mock.patch("relay.github.urllib.request.urlopen")
    def test_raises_on_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError(ConnectionError("down"))
        client = GitHubClient("acme", "widget", token="t")
        with pytest.raises(GitHubError) as exc_info:
            client.open_pull(title="x", head="h")
        assert "cannot reach GitHub" in str(exc_info.value)

    def test_explicit_token_beats_env(self):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env"}):
            assert GitHubClient("a", "b", token="explicit").token == "explicit"

    @mock.patch("relay.github.time.sleep")
    @mock.patch("relay.github.urllib.request.urlopen")
    def test_transient_http_errors_retry_and_recover(self, mock_urlopen, mock_sleep):
        err_429 = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO(b"{}"))
        success_resp = mock.MagicMock()
        success_resp.__enter__.return_value.read.return_value = b'{"number": 1, "html_url": "https://github.com/acme/widget/pull/1"}'
        mock_urlopen.side_effect = [err_429, success_resp]

        client = GitHubClient("acme", "widget", token="t")
        res = client.open_pull(title="x", head="h")
        assert res["number"] == 1
        assert mock_urlopen.call_count == 2
        assert mock_sleep.call_count == 1
        assert 1.0 <= mock_sleep.call_args.args[0] <= 1.6

