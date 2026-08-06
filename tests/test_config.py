"""Unit tests for relay/config.py — env-driven settings and the safety caps
(30s HTTP timeout default, 120s hard cap, 120-line diff budget)."""
import textwrap

import pytest

from relay import config


@pytest.fixture(autouse=True)
def clear_relay_env(monkeypatch):
    """Make every test start from a clean Relay environment."""
    for key in (
        "RELAY_AI_TIMEOUT",
        "RELAY_MAX_DIFF_LINES",
        "RELAY_AI_PROVIDER",
        "RELAY_BRANCH_TEMPLATE",
        "RELAY_PR_OPEN",
        "RELAY_CONFIG",
        "XDG_CONFIG_HOME",
        "APPDATA",
        "GEMINI_MODEL",
        "OLLAMA_MODEL",
        "OLLAMA_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_toml(monkeypatch, tmp_path, body: str) -> None:
    """Point RELAY_CONFIG at a fresh TOML file and write it."""
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setenv("RELAY_CONFIG", str(p))


def test_default_timeout_is_30_seconds():
    assert config.ai_timeout() == 30


def test_timeout_is_capped_at_120_seconds():
    config.os.environ["RELAY_AI_TIMEOUT"] = "999"
    assert config.ai_timeout() == 120


def test_reasonable_override_passes_through():
    config.os.environ["RELAY_AI_TIMEOUT"] = "45"
    assert config.ai_timeout() == 45


def test_timeout_has_a_positive_floor():
    config.os.environ["RELAY_AI_TIMEOUT"] = "0"
    assert config.ai_timeout() == 1


def test_invalid_timeout_falls_back_to_default():
    config.os.environ["RELAY_AI_TIMEOUT"] = "banana"
    assert config.ai_timeout() == 30


def test_explicit_override_beats_env():
    config.os.environ["RELAY_AI_TIMEOUT"] = "5"
    assert config.ai_timeout(override=60) == 60


def test_override_is_still_clamped():
    assert config.ai_timeout(override=99999) == 120
    assert config.ai_timeout(override=0) == 1


def test_max_diff_lines_default_and_override():
    assert config.max_diff_lines() == 120
    config.os.environ["RELAY_MAX_DIFF_LINES"] = "150"
    assert config.max_diff_lines() == 150


def test_invalid_max_diff_lines_falls_back_to_default():
    config.os.environ["RELAY_MAX_DIFF_LINES"] = "huge"
    assert config.max_diff_lines() == 120


# ---- F6: TOML config file (flags > env > file > defaults) --------------------


def test_no_config_file_uses_defaults(monkeypatch, tmp_path):
    assert config.branch_template() == config.DEFAULT_BRANCH_TEMPLATE
    assert config.gemini_model() == config.DEFAULT_GEMINI_MODEL


def test_file_supplies_values_when_env_unset(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        provider = "ollama"
        branch_template = "release/<feature>"
        gemini_model = "gemini-other"
        ai_timeout = 55
        max_diff_lines = 250
        pr_open = true
    """)
    assert config.provider_from_env() == "ollama"
    assert config.branch_template() == "release/<feature>"
    assert config.gemini_model() == "gemini-other"
    assert config.ai_timeout() == 55
    assert config.max_diff_lines() == 250
    assert config.pr_open_browser() is True


def test_env_beats_file(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ai_timeout = 55
    """)
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "10")
    assert config.ai_timeout() == 10


def test_file_timeout_is_still_clamped(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ai_timeout = 99999
    """)
    assert config.ai_timeout() == 120


def test_secret_keys_never_read_from_file(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        gemini_api_key = "leaked"
    """)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.gemini_api_key() is None


def test_missing_file_still_uses_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_CONFIG", str(tmp_path / "nope.toml"))
    assert config.ai_timeout() == 30


def test_invalid_toml_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_CONFIG", str(tmp_path / "bad.toml"))
    p = tmp_path / "bad.toml"
    p.write_text("not [valid", encoding="utf-8")
    assert config.ai_timeout() == 30