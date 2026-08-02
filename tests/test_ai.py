"""Unit tests for the AI providers (relay/ai/).

urllib.request.urlopen is mocked so no real network request is ever made. We
cover, per provider:

* a successful response (text parsed from the expected JSON shape);
* HTTP 429 (rate limit) and 5xx (server unavailable);
* a connection-refused network error;
* a malformed/unexpected payload;
* the AIManager.generate() wrapper that turns unexpected exceptions into AIError.
"""
import json
import urllib.error
from unittest import mock

import pytest

from relay.ai import AIManager, GeminiProvider, OllamaProvider
from relay.errors import AIError, ConfigError


def fake_http(payload):
    """A context-manager response whose .read() yields JSON bytes."""
    response = mock.Mock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


GEMINI_SUCCESS = {"candidates": [{"content": {"parts": [{"text": "feat(api): add login"}]}}]}
OLLAMA_SUCCESS = {"response": "fix: update docs"}


class TestGemini:
    def make_provider(self):
        return GeminiProvider(api_key="test-key", model="gemini-2.5-flash", timeout=5)

    def test_missing_api_key_raises_config_error(self):
        with mock.patch("relay.ai.gemini.gemini_api_key", return_value=None):
            with pytest.raises(ConfigError):
                GeminiProvider(model="gemini-2.5-flash")

    def test_success_returns_text_and_sends_correct_request(self, sample_diff, sample_stat):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(GEMINI_SUCCESS)
            result = self.make_provider().generate_commit_message(sample_diff, sample_stat, "main")

        assert result == "feat(api): add login"
        request = mock_urlopen.call_args.args[0]
        # urllib lower-cases-then-capitalizes header keys, so compare case-insensitively.
        headers = {key.lower(): value for key, value in request.headers.items()}
        assert headers["x-goog-api-key"] == "test-key"
        assert headers["content-type"] == "application/json"
        assert "gemini-2.5-flash" in request.full_url

    def test_http_429_maps_to_rate_limited_aierror(self):
        http_error = urllib.error.HTTPError(
            "https://example.com", 429, "Too Many Requests", {}, None
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.provider == "gemini"
        assert exc_info.value.kind == "rate_limited"

    def test_http_500_maps_to_unavailable_aierror(self):
        http_error = urllib.error.HTTPError(
            "https://example.com", 503, "Service Unavailable", {}, None
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_connection_refused_maps_to_unavailable_aierror(self):
        network_error = urllib.error.URLError(ConnectionError("connection refused"))
        with mock.patch("urllib.request.urlopen", side_effect=network_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_malformed_payload_maps_to_bad_response_aierror(self):
        payload = {"unexpected": "shape"}
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(payload)
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"


class TestOllama:
    def make_provider(self):
        return OllamaProvider(base_url="http://localhost:11434", model="qwen2.5-coder:7b", timeout=5)

    def test_success_returns_response_field(self, sample_diff, sample_stat):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(OLLAMA_SUCCESS)
            result = self.make_provider().generate_commit_message(sample_diff, sample_stat, "main")

        assert result == "fix: update docs"
        request = mock_urlopen.call_args.args[0]
        assert request.full_url == "http://localhost:11434/api/generate"
        headers = {key.lower(): value for key, value in request.headers.items()}
        assert headers["content-type"] == "application/json"

    def test_http_500_maps_to_unavailable_aierror(self):
        http_error = urllib.error.HTTPError(
            "http://localhost:11434", 500, "Internal Server Error", {}, None
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_connection_refused_maps_to_unavailable_aierror(self):
        network_error = urllib.error.URLError(ConnectionError("connection refused"))
        with mock.patch("urllib.request.urlopen", side_effect=network_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_error_field_maps_to_bad_response_aierror(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http({"error": "model not found"})
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"


class TestBuildPrompt:
    def test_includes_context_and_commit_rules(self):
        prompt = AIManager.build_prompt("DIFF", "STAT", "main")
        assert "DIFF" in prompt
        assert "STAT" in prompt
        assert "main" in prompt
        assert "type(scope): subject" in prompt


class TestGenerateWrapper:
    """The seam the Orchestrator's fallback relies on."""

    def test_unexpected_exception_becomes_aierror(self):
        provider = GeminiProvider(api_key="k", model="m", timeout=5)
        provider.generate_commit_message = mock.Mock(side_effect=ValueError("boom"))
        with pytest.raises(AIError) as exc_info:
            provider.generate("d", "s", "b")
        assert exc_info.value.kind == "unexpected"
        assert exc_info.value.provider == "gemini"

    def test_aierror_passes_through_unwrapped(self):
        provider = GeminiProvider(api_key="k", model="m", timeout=5)
        original = AIError("gemini", "bad_response", "x")
        provider.generate_commit_message = mock.Mock(side_effect=original)
        with pytest.raises(AIError) as exc_info:
            provider.generate("d", "s", "b")
        assert exc_info.value is original
