"""Unit tests for relay/telemetry.py — the opt-in reporting gate.

The core contract under test: nothing is ever sent (and no thread even starts)
unless the user explicitly opted in. The rest is the fire-and-forget payload
shape, which is asserted through a fake thread target.
"""
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
        monkeypatch.setenv("RELAY_TELEMETRY", "1")
        monkeypatch.setenv("RELAY_TELEMETRY_URL", "://bad url")
        telemetry.report(mode="solo", provider="gemini", ok=True)  # no exception


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

    def test_main_reports_after_workflow(self):
        with mock.patch("relay.cli.build_provider") as build_provider, mock.patch(
            "relay.cli.Orchestrator"
        ) as orchestrator_cls, mock.patch("relay.cli.report") as report:
            orchestrator_cls.return_value.run.return_value = 0
            report.return_value = None
            assert main(["--solo", "--yes"]) == 0
        report.assert_called_once()
        kwargs = report.call_args.kwargs
        assert kwargs["mode"] == "solo"
        assert kwargs["ok"] is True