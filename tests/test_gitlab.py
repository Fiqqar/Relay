"""Unit tests for relay/gitlab.py — the zero-dependency GitLab MR client."""
import json
import urllib.error
from unittest import mock

import pytest

from relay.gitlab import (
    DuplicateMergeRequestError,
    GitLabClient,
    GitLabError,
    gitlab_token,
)


def fake_http(payload):
    response = mock.Mock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


def make_client():
    return GitLabClient("gitlab.com", "acme/widget", token="glpat-test")


class TestGitLabToken:
    def test_reads_gitlab_token(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "glpat-xxx")
        assert gitlab_token() == "glpat-xxx"

    def test_falls_back_to_ci_job_token(self, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("CI_JOB_TOKEN", "ci-xxx")
        assert gitlab_token() == "ci-xxx"


class TestGitLabClient:
    def test_requires_token(self):
        with mock.patch("relay.gitlab.gitlab_token", return_value=None):
            client = GitLabClient("gitlab.com", "acme/widget")
            with pytest.raises(GitLabError, match="GITLAB_TOKEN"):
                client.find_open_mr(source_branch="feat/login")

    def test_success_returns_iid_and_url(self):
        payload = {"iid": 42, "web_url": "https://gitlab.com/acme/widget/-/merge_requests/42"}
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = fake_http(payload)
            result = make_client().open_merge_request(
                title="feat: add login", source_branch="feat/login",
                target_branch="main", description="body", draft=False,
            )
        assert result == payload
        request = urlopen.call_args.args[0]
        assert "projects/acme%2Fwidget/merge_requests" in request.full_url
        headers = {k.lower(): v for k, v in request.headers.items()}
        assert headers["private-token"] == "glpat-test"

    def test_draft_sets_draft_flag(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = fake_http({})
            make_client().open_merge_request(
                title="t", source_branch="b", draft=True
            )
        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        assert body["draft"] is True

    def test_find_open_mr_returns_first_opened(self):
        mrs = [{"iid": 1}, {"iid": 2}]
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = fake_http(mrs)
            urlopen.return_value.__enter__.return_value = fake_http(mrs)
            result = make_client().find_open_mr(source_branch="feat/login")
        assert result == {"iid": 1}

    def test_find_open_mr_returns_none_when_empty(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = fake_http([])
            assert make_client().find_open_mr(source_branch="feat/login") is None

    def test_http_409_duplicate_raises_duplicate_error(self):
        err = urllib.error.HTTPError(
            "https://gitlab.com", 409, "Conflict", {}, None
        )
        err.read = lambda *args: b'{"message":"Another open merge request already exists for this source branch"}'
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(DuplicateMergeRequestError):
                make_client().open_merge_request(
                    title="t", source_branch="b", target_branch="main"
                )

    def test_http_400_raises_gitlab_error_with_detail(self):
        err = urllib.error.HTTPError(
            "https://gitlab.com", 400, "Bad Request", {}, None
        )
        err.read = lambda *args: b'{"message":"Bad source branch name"}'
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(GitLabError) as exc_info:
                make_client().open_merge_request(
                    title="t", source_branch="b", target_branch="main"
                )
        assert exc_info.value.status == 400
        assert "Bad source branch name" in exc_info.value.reason

    def test_error_body_read_is_capped_at_10kib(self):
        from relay.gitlab import _MAX_ERROR_BODY_BYTES

        err = urllib.error.HTTPError(
            "https://gitlab.com", 500, "Internal Server Error", {}, None
        )
        err.read = lambda n=0: (b"x" * (_MAX_ERROR_BODY_BYTES + 100))[:n]
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(GitLabError) as exc_info:
                make_client().find_open_mr(source_branch="b")
        assert len(exc_info.value.body) <= _MAX_ERROR_BODY_BYTES

    def test_reason_handles_field_keyed_message(self):
        err = urllib.error.HTTPError(
            "https://gitlab.com", 400, "Bad Request", {}, None
        )
        err.read = lambda *args: b'{"message":{"source_branch":["is invalid"]}}'
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(GitLabError) as exc_info:
                make_client().open_merge_request(
                    title="t", source_branch="b", target_branch="main"
                )
        assert "source_branch" in exc_info.value.reason

    def test_connection_error_surfaces_clearly(self):
        from urllib.error import URLError

        with mock.patch("urllib.request.urlopen", side_effect=URLError("timed out")):
            with pytest.raises(GitLabError, match="cannot reach"):
                make_client().open_merge_request(
                    title="t", source_branch="b", target_branch="main"
                )

    def test_oversized_success_response_is_rejected(self):
        """A healthy-looking but huge 2xx body must not be slurped whole."""
        from relay.gitlab import MAX_RESPONSE_BYTES

        response = mock.Mock()
        response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            with pytest.raises(GitLabError, match="byte limit"):
                make_client().find_open_mr(source_branch="feat/login")
