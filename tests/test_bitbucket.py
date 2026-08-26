"""Unit tests for relay/bitbucket.py — the zero-dependency Bitbucket Cloud client.

urllib.request.urlopen is mocked so no real network request is ever made; the
suite stays hermetic and offline-safe.
"""
import base64
import json
import urllib.error
import urllib.parse
from unittest import mock

import pytest

from relay.bitbucket import (
    BitbucketClient,
    BitbucketError,
    DuplicatePullRequestError,
    bitbucket_token,
)


def fake_http(payload):
    response = mock.Mock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


def make_client(token="user:app_password", verbose=False):
    return BitbucketClient("acme", "widget", token=token, verbose=verbose)


BASIC = "Basic " + base64.b64encode(b"user:app_password").decode("ascii")


class TestBitbucketToken:
    def test_reads_bitbucket_token(self, monkeypatch):
        monkeypatch.setenv("BITBUCKET_TOKEN", "user:pass")
        assert bitbucket_token() == "user:pass"

    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("BITBUCKET_TOKEN", raising=False)
        assert bitbucket_token() is None


class TestPullsUrl:
    def test_url_uses_owner_and_repo(self):
        assert make_client().pulls_url == (
            "https://api.bitbucket.org/2.0/repositories/acme/widget/pullrequests"
        )

    def test_url_quotes_special_characters(self):
        client = BitbucketClient("owner with space", "repo/slash", token="user:pass")
        assert client.pulls_url == (
            "https://api.bitbucket.org/2.0/repositories/owner%20with%20space/repo%2Fslash/pullrequests"
        )


class TestAuth:
    def test_requires_token(self):
        with mock.patch("relay.bitbucket.bitbucket_token", return_value=None):
            client = BitbucketClient("acme", "widget")
            with pytest.raises(BitbucketError, match="BITBUCKET_TOKEN"):
                client.find_open_pull(source_branch="feat/login")

    def test_malformed_token_raises_with_format_hint(self):
        with pytest.raises(BitbucketError, match="username:app_password"):
            make_client("just-a-password").find_open_pull(source_branch="b")

    def test_token_without_username_raises(self):
        with pytest.raises(BitbucketError, match="username:app_password"):
            make_client(":password").find_open_pull(source_branch="b")


class TestFindOpenPull:
    @mock.patch("relay.bitbucket.urllib.request.urlopen")
    def test_queries_open_prs_for_source_branch(self, mock_urlopen):
        payload = {"values": [{"id": 9, "links": {"html": {"href": "https://bitbucket.org/acme/widget/pull-requests/9"}}}]}
        mock_urlopen.return_value.__enter__.return_value = fake_http(payload)

        result = make_client().find_open_pull(source_branch="feat/login")

        request = mock_urlopen.call_args.args[0]
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == BASIC
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        assert query["q"] == ['source.branch.name="feat/login" AND state="OPEN"']
        assert result["id"] == 9

    @mock.patch("relay.bitbucket.urllib.request.urlopen")
    def test_returns_none_when_empty(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = fake_http({"values": []})
        assert make_client().find_open_pull(source_branch="feat/login") is None

    @mock.patch("relay.bitbucket.urllib.request.urlopen")
    def test_raises_with_status_on_http_error(self, mock_urlopen):
        error = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, None
        )
        error.read = lambda *args: b'{"error":{"message":"Bad credentials"}}'
        mock_urlopen.side_effect = error
        with pytest.raises(BitbucketError) as exc_info:
            make_client().find_open_pull(source_branch="b")
        assert exc_info.value.status == 401
        assert "Bad credentials" in exc_info.value.reason


class TestOpenPull:
    @mock.patch("relay.bitbucket.urllib.request.urlopen")
    def test_posts_payload_with_source_and_destination(self, mock_urlopen):
        payload = {"id": 7, "links": {"html": {"href": "https://bitbucket.org/acme/widget/pull-requests/7"}}}
        mock_urlopen.return_value.__enter__.return_value = fake_http(payload)

        result = make_client().open_pull(
            title="Add login", source_branch="feat/login",
            destination_branch="main", description="Details",
        )

        request = mock_urlopen.call_args.args[0]
        assert request.full_url == (
            "https://api.bitbucket.org/2.0/repositories/acme/widget/pullrequests"
        )
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == BASIC
        assert json.loads(request.data) == {
            "title": "Add login",
            "description": "Details",
            "source": {"branch": {"name": "feat/login"}},
            "destination": {"branch": {"name": "main"}},
        }
        assert result["id"] == 7

    @mock.patch("relay.bitbucket.urllib.request.urlopen")
    def test_destination_defaults_to_main(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = fake_http({})
        make_client().open_pull(title="x", source_branch="b")
        body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        assert body["destination"]["branch"]["name"] == "main"

    def test_400_duplicate_raises_duplicate_error(self):
        err = urllib.error.HTTPError("https://api.bitbucket.org", 400, "Bad Request", {}, None)
        err.read = lambda *args: b'{"error":{"message":"A pull request for source branch \'feat/login\' already exists"}}'
        with mock.patch("relay.bitbucket.urllib.request.urlopen", side_effect=err):
            with pytest.raises(DuplicatePullRequestError) as exc_info:
                make_client().open_pull(title="t", source_branch="feat/login")
        assert exc_info.value.status == 400

    def test_400_without_duplicate_stays_plain_error(self):
        err = urllib.error.HTTPError("https://api.bitbucket.org", 400, "Bad Request", {}, None)
        err.read = lambda *args: b'{"error":{"message":"Invalid source branch"}}'
        with mock.patch("relay.bitbucket.urllib.request.urlopen", side_effect=err):
            with pytest.raises(BitbucketError) as exc_info:
                make_client().open_pull(title="t", source_branch="b")
        assert type(exc_info.value) is BitbucketError
        assert "Invalid source branch" in exc_info.value.reason

    def test_errors_list_shape_is_extracted(self):
        err = urllib.error.HTTPError("https://api.bitbucket.org", 422, "Unprocessable Entity", {}, None)
        err.read = lambda *args: b'{"errors":[{"message":"Destination branch does not exist"}]}'
        with mock.patch("relay.bitbucket.urllib.request.urlopen", side_effect=err):
            with pytest.raises(BitbucketError) as exc_info:
                make_client().open_pull(title="t", source_branch="b")
        assert "Destination branch does not exist" in exc_info.value.reason

    def test_error_body_read_is_capped_at_10kib(self):
        from relay.bitbucket import _MAX_ERROR_BODY_BYTES

        err = urllib.error.HTTPError("https://api.bitbucket.org", 500, "Internal Server Error", {}, None)
        err.read = lambda n=0: (b"x" * (_MAX_ERROR_BODY_BYTES + 100))[:n]
        with mock.patch("relay.bitbucket.urllib.request.urlopen", side_effect=err):
            with pytest.raises(BitbucketError) as exc_info:
                make_client().find_open_pull(source_branch="b")
        assert len(exc_info.value.body) <= _MAX_ERROR_BODY_BYTES

    def test_connection_error_surfaces_clearly(self):
        with mock.patch("relay.bitbucket.urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            with pytest.raises(BitbucketError, match="cannot reach Bitbucket"):
                make_client().open_pull(title="t", source_branch="b")

    def test_oversized_success_response_is_rejected(self):
        from relay.bitbucket import MAX_RESPONSE_BYTES

        response = mock.Mock()
        response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        with mock.patch("relay.bitbucket.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            with pytest.raises(BitbucketError, match="byte limit"):
                make_client().find_open_pull(source_branch="b")


class TestVerboseLogging:
    @mock.patch("relay.bitbucket.urllib.request.urlopen")
    def test_prints_endpoint_when_verbose(self, mock_urlopen, capsys):
        mock_urlopen.return_value.__enter__.return_value = fake_http({"values": []})
        make_client(verbose=True).find_open_pull(source_branch="b")
        out = capsys.readouterr().out
        assert "[relay] bitbucket GET" in out
        assert "pullrequests" in out
