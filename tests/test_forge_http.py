"""Unit tests for the shared forge transport (relay/forge_http.py).

All three forge clients (GitHub/GitLab/Bitbucket) run the same HTTP shape:
capped reads, transient (429/5xx) retry with backoff+jitter, and normalized
errors. These tests pin that shared contract once, so the per-forge suites
only need to cover their own payload shapes.
"""
import io
import urllib.error
import urllib.request
from unittest import mock

import pytest

from relay.errors import RelayError


class StubForgeError(RelayError):
    def __init__(self, message="", status=0, body="", payload=None, detail=""):
        super().__init__(message)
        self.status = status
        self.body = body
        self.payload = payload
        self.detail = detail


def stub_reason(payload):
    if isinstance(payload, dict):
        return payload.get("message") or ""
    return ""


def call_helper(request, **kwargs):
    from relay.forge_http import request_json

    params = dict(
        forge="Example",
        tag="example",
        error_cls=StubForgeError,
        extract_reason=stub_reason,
        unreachable="cannot reach Example",
    )
    params.update(kwargs)
    return request_json(request, **params)


def fake_http(body: bytes):
    resp = mock.MagicMock()
    resp.read.return_value = body
    return mock.MagicMock(__enter__=mock.MagicMock(return_value=resp))


def test_success_returns_parsed_json():
    req = urllib.request.Request("https://api.example.com/x", method="GET")
    with mock.patch("urllib.request.urlopen", return_value=fake_http(b'{"a": 1}')):
        assert call_helper(req) == {"a": 1}


def test_oversized_success_body_is_rejected():
    from relay.forge_http import MAX_RESPONSE_BYTES

    req = urllib.request.Request("https://api.example.com/x", method="GET")
    big = fake_http(b"x" * (MAX_RESPONSE_BYTES + 1))
    with mock.patch("urllib.request.urlopen", return_value=big):
        with pytest.raises(StubForgeError, match="byte limit") as exc_info:
            call_helper(req)
    assert "Example" in str(exc_info.value)


def test_transient_status_retries_then_recovers():
    err_429 = urllib.error.HTTPError(
        "https://api.example.com/x", 429, "Too Many Requests", {}, io.BytesIO(b"{}")
    )
    req = urllib.request.Request("https://api.example.com/x", method="GET")
    with mock.patch("relay.forge_http.time.sleep") as mock_sleep:
        with mock.patch(
            "urllib.request.urlopen", side_effect=[err_429, fake_http(b'{"ok": true}')]
        ) as mock_urlopen:
            assert call_helper(req) == {"ok": True}
    assert mock_urlopen.call_count == 2
    mock_sleep.assert_called_once()


def test_non_transient_error_carries_status_body_and_detail():
    body = b'{"message": "nope"}'
    err = urllib.error.HTTPError(
        "https://api.example.com/x", 400, "Bad Request", {}, io.BytesIO(body)
    )
    req = urllib.request.Request("https://api.example.com/x", method="GET")
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(StubForgeError) as exc_info:
            call_helper(req)
    exc = exc_info.value
    assert exc.status == 400
    assert exc.detail == "nope"
    assert "Example API error 400" in str(exc)


def test_connection_failure_uses_unreachable_prefix():
    req = urllib.request.Request("https://api.example.com/x", method="GET")
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("timed out"),
    ):
        with pytest.raises(StubForgeError, match="cannot reach Example"):
            call_helper(req)


def test_verbose_prints_method_and_url(capsys):
    req = urllib.request.Request("https://api.example.com/things", method="GET")
    with mock.patch("urllib.request.urlopen", return_value=fake_http(b"[]")):
        call_helper(req, verbose=True)
    out = capsys.readouterr().out
    assert "[relay] example GET" in out
    assert "https://api.example.com/things" in out


def test_quiet_mode_prints_nothing(capsys):
    req = urllib.request.Request("https://api.example.com/things", method="GET")
    with mock.patch("urllib.request.urlopen", return_value=fake_http(b"[]")):
        call_helper(req, verbose=False)
    assert capsys.readouterr().out == ""
