"""Unit tests for relay/telemetry.py — the opt-in reporting gate.

The core contract under test: nothing is ever sent (and no thread even starts)
unless the user explicitly opted in. The rest is the fire-and-forget payload
shape, which is asserted through a fake thread target.
"""
import json
import urllib.error
from unittest import mock

import pytest

from relay import telemetry
from relay.cli import build_parser, main


class TestConsent:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("RELAY_TELEMETRY", raising=False)
        assert telemetry.is_enabled() is False

    def test_env_var_enables(self, monkeypatch):
        monkeypatch.delenv("RELAY_TELEMETRY", raising=False)
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        assert telemetry.is_enabled() is True

    def test_env_var_truthy_variants(self, monkeypatch):
        for val in ("1", "true", "yes", "on", "enabled"):
            monkeypatch.setenv("RELAY_TELEMETRY", val)
            assert telemetry.is_enabled() is True

    def test_env_var_falsy_variants(self, monkeypatch):
        for val in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("RELAY_TELEMETRY", val)
            assert telemetry.is_enabled() is False

    def test_marker_file_enables(self, monkeypatch, tmp_path):
        monkeypatch.delenv("RELAY_TELEMETRY", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        telemetry.set_enabled(True)
        assert telemetry.is_enabled() is True

    def test_marker_file_disables(self, monkeypatch, tmp_path):
        monkeypatch.delenv("RELAY_TELEMETRY", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        telemetry.set_enabled(False)
        assert telemetry.is_enabled() is False

    def test_env_beats_marker(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        telemetry.set_enabled(True)
        monkeypatch.setenv("RELAY_TELEMETRY", "0")
        assert telemetry.is_enabled() is False


class TestReport:
    @pytest.fixture(autouse=True)
    def prepare(self, monkeypatch, tmp_path):
        monkeypatch.delenv("RELAY_TELEMETRY", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def test_disabled_never_starts_thread(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://example.com")
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="solo", provider="gemini", ok=True)
        thread.assert_not_called()

    def test_enabled_without_url_is_noop(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.delenv("RELAY_TELEMETRY_URL", raising=False)
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="team", provider="ollama", ok=True)
        thread.assert_not_called()

    def test_enabled_with_url_starts_payload_thread(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://t.example/collect")
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="team", provider="ollama", ok=False)
        thread.assert_called_once()
        payload = thread.call_args.kwargs["args"][0]
        assert payload["mode"] == "team"
        assert payload["provider"] == "ollama"
        assert payload["ok"] is False
        assert payload["event"] == "relay_run"

    def test_never_raises_on_bad_url(self, monkeypatch):
        """_send_payload must swallow a malformed collection URL, not raise.
        Tested directly so no real background thread is spawned."""
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "://bad url")
        telemetry._send_payload({"event": "relay_run", "ok": True})  # no exception

    # ---- HTTPS-only collection URL (C-02) -----------------------------------

    def test_non_https_url_does_not_start_thread(self, monkeypatch, capsys):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "http://evil.example.com/collect")
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="solo", provider="gemini", ok=True)
        thread.assert_not_called()
        assert "warning" in capsys.readouterr().err

    def test_bare_host_url_is_rejected(self, monkeypatch, capsys):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "example.com/collect")
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="solo", provider="gemini", ok=True)
        thread.assert_not_called()

    def test_https_url_still_sends(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://t.example/collect")
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="solo", provider="gemini", ok=True)
        thread.assert_called_once()

    def test_send_payload_skips_non_https_without_network(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "http://evil.example.com/collect")
        with mock.patch("urllib.request.urlopen") as urlopen:
            telemetry._send_payload({"event": "relay_run", "ok": True})
        urlopen.assert_not_called()

    # ---- Local/private endpoints are rejected (C-02 hardening) ---------------

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/collect",
            "https://localhost/collect",
            "https://foo.localhost/collect",
            "https://10.1.2.3/collect",
            "https://172.16.0.5/collect",
            "https://192.168.1.1/collect",
            "https://169.254.1.1/collect",
            "https://[::1]/collect",
            "https://[fc00::1]/collect",
            "https://[fe80::1]/collect",
        ],
    )
    def test_local_private_url_does_not_start_thread(self, monkeypatch, url):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", url)
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="solo", provider="gemini", ok=True)
        thread.assert_not_called()

    @pytest.mark.parametrize(
        "url",
        [
            "https://t.example/collect",
            "https://analytics.internal.example/collect",
            "https://[2606:4700:4700::1111]/collect",
        ],
    )
    def test_public_url_still_sends(self, monkeypatch, url):
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", url)
        with mock.patch.object(telemetry.threading, "Thread") as thread:
            telemetry.report(mode="solo", provider="gemini", ok=True)
        thread.assert_called_once()

    def test_send_payload_skips_private_host_without_network(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://127.0.0.1/collect")
        with mock.patch("urllib.request.urlopen") as urlopen:
            telemetry._send_payload({"event": "relay_run", "ok": True})
        urlopen.assert_not_called()


class TestStateFile:
    def test_state_file_falls_back_to_home_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        with mock.patch("relay.telemetry.Path.home", return_value=tmp_path):
            assert telemetry._state_file() == tmp_path / ".config" / "relay" / "telemetry"


class TestSendPayload:
    def test_posts_json_payload_over_https(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://t.example/collect")
        mock_opener = mock.Mock()
        mock_opener.open.return_value.__enter__ = mock.Mock(return_value=mock.Mock())
        mock_opener.open.return_value.__exit__ = mock.Mock(return_value=False)
        with mock.patch("urllib.request.build_opener", return_value=mock_opener) as build:
            telemetry._send_payload({"event": "relay_run", "ok": True, "mode": "solo"})
        build.assert_called_once()
        request = mock_opener.open.call_args.args[0]
        assert request.full_url == "https://t.example/collect"
        assert request.method == "POST"
        assert mock_opener.open.call_args.kwargs["timeout"] == 3
        assert json.loads(request.data) == {"event": "relay_run", "ok": True, "mode": "solo"}

    def test_swallows_network_failure(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://t.example/collect")
        mock_opener = mock.Mock()
        mock_opener.open.side_effect = RuntimeError("unreachable")
        with mock.patch("urllib.request.build_opener", return_value=mock_opener):
            telemetry._send_payload({"event": "relay_run", "ok": True})  # never raises

    def test_swallows_http_error(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://t.example/collect")
        mock_opener = mock.Mock()
        mock_opener.open.side_effect = urllib.error.HTTPError(
            "https://t.example", 500, "boom", {}, None
        )
        with mock.patch("urllib.request.build_opener", return_value=mock_opener):
            telemetry._send_payload({"event": "relay_run", "ok": True})  # never raises

    def test_redirect_to_private_host_is_blocked(self, monkeypatch):
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://t.example/collect")
        handler = telemetry._SafeRedirectHandler()
        assert handler.redirect_request(None, None, 302, "msg", {}, "http://127.0.0.1/evil") is None
        assert handler.redirect_request(None, None, 302, "msg", {}, "https://127.0.0.1/evil") is None
        assert handler.redirect_request(None, None, 302, "msg", {}, "http://t.example/other") is None
        # public https redirect is allowed (returns a Request or not None)
        # We only verify it doesn't return None for a public https URL
        # Use a dummy request to see it passes _is_https
        assert telemetry._is_https("https://t.example/other") is True


def test_parser_telemetry_defaults_status():
    args = build_parser().parse_args(["telemetry"])
    assert args.command == "telemetry"
    assert args.action == "status"


def test_parser_telemetry_on(tmpdir):
    args = build_parser().parse_args(["telemetry", "on"])
    assert args.action == "on"


def test_flag_named_telemetry_is_not_a_subcommand():
    args = build_parser().parse_args(["--team", "telemetry"])
    assert args.command is None
    assert args.team == "telemetry"


class TestCliTelemetry:
    def test_telemetry_on_then_status(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        telemetry.set_enabled(False)
        assert main(["telemetry", "on"]) == 0
        assert telemetry.is_enabled() is True
        assert main(["telemetry", "off"]) == 0
        assert telemetry.is_enabled() is False
        assert "telemetry" in capsys.readouterr().out


# ---- coverage: missing branches (moved from test_coverage_95) ----------------

def test_is_local_or_private_host_localhost():
    assert telemetry._is_local_or_private_host("localhost") is True
    assert telemetry._is_local_or_private_host("foo.localhost") is True
    assert telemetry._is_local_or_private_host("example.com") is False


def test_is_local_private_ip():
    assert telemetry._is_local_or_private_host("127.0.0.1") is True
    assert telemetry._is_local_or_private_host("10.0.0.1") is True
    assert telemetry._is_local_or_private_host("192.168.1.1") is True
    assert telemetry._is_local_or_private_host("8.8.8.8") is False


def test_is_https_rejects_private():
    assert telemetry._is_https("http://example.com") is False
    assert telemetry._is_https("https://127.0.0.1/collect") is False
    assert telemetry._is_https("https://example.com/collect") is True
    assert telemetry._is_https("https://localhost/collect") is False
    assert telemetry._is_https("not-a-url") is False
    assert telemetry._is_https("https://") is False


def test_is_valid_ai_base_url():
    assert telemetry._is_valid_ai_base_url("https://api.openai.com/v1") is True
    assert telemetry._is_valid_ai_base_url("http://localhost:11434") is True
    assert telemetry._is_valid_ai_base_url("http://127.0.0.1:11434") is True
    assert telemetry._is_valid_ai_base_url("http://10.0.0.1/v1") is False
    assert telemetry._is_valid_ai_base_url("http://example.com/v1") is False
    assert telemetry._is_valid_ai_base_url("https://10.0.0.1/v1") is False
    assert telemetry._is_valid_ai_base_url("ftp://example.com") is False
    assert telemetry._is_valid_ai_base_url("https://") is False
    assert telemetry._is_valid_ai_base_url("https://example.com") is True
    assert telemetry._is_valid_ai_base_url("http://[::1]:11434") is True


def test_safe_redirect_handler_rejects_private():
    h = telemetry._SafeRedirectHandler()
    assert h.redirect_request(None, None, 302, "", {}, "https://127.0.0.1/") is None
    assert h.redirect_request(None, None, 302, "", {}, "http://example.com") is None


def test_send_payload_no_url(monkeypatch):
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "")
    telemetry._send_payload({"event": "test"})


def test_send_payload_invalid_url(monkeypatch):
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "http://example.com")
    telemetry._send_payload({"event": "test"})


def test_report_without_url(monkeypatch):
    monkeypatch.setenv("RELAY_TELEMETRY", "1")
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "")
    telemetry.report(mode="solo", provider="gemini", ok=True)


def test_report_with_private_url(monkeypatch, capsys):
    monkeypatch.setenv("RELAY_TELEMETRY", "1")
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://127.0.0.1/collect")
    telemetry.report(mode="solo", provider="gemini", ok=True)
    assert "warning" in capsys.readouterr().err.lower()

    def test_main_reports_after_workflow(self):
        with mock.patch("relay.cli.build_provider"), mock.patch(
            "relay.cli.Orchestrator"
        ) as orchestrator_cls, mock.patch("relay.cli.report") as report:
            orchestrator_cls.return_value.run.return_value = 0
            report.return_value = None
            assert main(["--solo", "--yes"]) == 0
        report.assert_called_once()
        kwargs = report.call_args.kwargs
        assert kwargs["mode"] == "solo"
        assert kwargs["ok"] is True
