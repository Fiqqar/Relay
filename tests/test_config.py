"""Unit tests for relay/config.py — env-driven settings and the safety caps
(30s HTTP timeout default, 120s hard cap, 120-line diff budget)."""
import pytest

from relay import config


@pytest.fixture(autouse=True)
def clear_relay_env(monkeypatch):
    """Make every test start from a clean Relay environment."""
    for key in (
        "RELAY_AI_TIMEOUT",
        "RELAY_MAX_DIFF_LINES",
        "RELAY_AI_PROVIDER",
        "GEMINI_MODEL",
        "OLLAMA_MODEL",
        "OLLAMA_BASE_URL",
        "RELAY_BRANCH_TEMPLATE",
    ):
        monkeypatch.delenv(key, raising=False)


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
