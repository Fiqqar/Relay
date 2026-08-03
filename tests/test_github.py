"""Unit tests for relay/github.py — the zero-dependency GitHub client.

urllib.request.urlopen is mocked so no real network request is ever made; the
suite stays hermetic and offline-safe.
"""
import io
import json
import os
import urllib.error
from unittest import mock

import pytest

from relay.github import GitHubClient, GitHubError, github_token


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
        }
        assert result["number"] == 7

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
