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

from relay.ai import (
    AIManager,
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    build_provider,
)
from relay.ai.base import truncate_diff
from relay.errors import AIError, ConfigError


def fake_http(payload):
    """A context-manager response whose .read() yields JSON bytes."""
    response = mock.Mock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    return response


GEMINI_SUCCESS = {"candidates": [{"content": {"parts": [{"text": "feat(api): add login"}]}}]}
OLLAMA_SUCCESS = {"response": "fix: update docs"}
OPENAI_SUCCESS = {"choices": [{"message": {"content": "feat(api): add login"}}]}
ANTHROPIC_SUCCESS = {"content": [{"type": "text", "text": "fix: tighten validation"}]}


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

    def test_http_4xx_maps_to_api_error_aierror(self):
        http_error = urllib.error.HTTPError(
            "https://example.com", 401, "Unauthorized", {}, None
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "api_error"

    def test_connection_refused_maps_to_unavailable_aierror(self):
        network_error = urllib.error.URLError(ConnectionError("connection refused"))
        with mock.patch("urllib.request.urlopen", side_effect=network_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_direct_timeout_maps_to_unavailable_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"
        assert "timeout" in str(exc_info.value)

    def test_wrapped_timeout_maps_to_unavailable_aierror(self):
        wrapped = urllib.error.URLError(TimeoutError("timed out"))
        with mock.patch("urllib.request.urlopen", side_effect=wrapped):
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

    def test_direct_timeout_maps_to_unavailable_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_error_field_maps_to_bad_response_aierror(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http({"error": "model not found"})
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"


class TestOpenAI:
    def make_provider(self):
        return OpenAIProvider(api_key="test-key", model="gpt-4o-mini", base_url="https://api.openai.com/v1", timeout=5)

    def test_success_returns_content_and_sends_correct_request(self, sample_diff, sample_stat):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(OPENAI_SUCCESS)
            result = self.make_provider().generate_commit_message(sample_diff, sample_stat, "main")

        assert result == "feat(api): add login"
        request = mock_urlopen.call_args.args[0]
        assert request.full_url == "https://api.openai.com/v1/chat/completions"
        headers = {key.lower(): value for key, value in request.headers.items()}
        assert headers["authorization"] == "Bearer test-key"
        assert headers["content-type"] == "application/json"

    def test_custom_base_url_targets_llama_compatible_endpoint(self):
        provider = OpenAIProvider(api_key="k", model="llama3", base_url="http://localhost:8080/v1", timeout=5)
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(OPENAI_SUCCESS)
            provider.generate_commit_message("d", "s", "b")
        assert mock_urlopen.call_args.args[0].full_url == "http://localhost:8080/v1/chat/completions"

    def test_http_429_maps_to_rate_limited_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://example.com", 429, "Too Many Requests", {}, None
        )):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "rate_limited"

    def test_http_4xx_maps_to_api_error_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://example.com", 401, "Unauthorized", {}, None
        )):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "api_error"

    def test_error_field_maps_to_bad_response_aierror(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http({"error": {"message": "bad"}})
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"


class TestAnthropic:
    def make_provider(self):
        return AnthropicProvider(api_key="test-key", model="claude-3-5-haiku-latest", base_url="https://api.anthropic.com/v1", timeout=5)

    def test_success_returns_text_and_sends_correct_request(self, sample_diff, sample_stat):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(ANTHROPIC_SUCCESS)
            result = self.make_provider().generate_commit_message(sample_diff, sample_stat, "main")

        assert result == "fix: tighten validation"
        request = mock_urlopen.call_args.args[0]
        assert request.full_url == "https://api.anthropic.com/v1/messages"
        headers = {key.lower(): value for key, value in request.headers.items()}
        assert headers["x-api-key"] == "test-key"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_http_500_maps_to_unavailable_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://api.anthropic.com", 500, "Internal Server Error", {}, None
        )):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_http_4xx_maps_to_api_error_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://api.anthropic.com", 403, "Forbidden", {}, None
        )):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "api_error"

    def test_http_429_maps_to_rate_limited_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://api.anthropic.com", 429, "Too Many Requests", {}, None
        )):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "rate_limited"

    def test_direct_timeout_maps_to_unavailable_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"
        assert "timeout after" in str(exc_info.value)

    def test_wrapped_timeout_maps_to_unavailable_aierror(self):
        wrapped = urllib.error.URLError(TimeoutError("timed out"))
        with mock.patch("urllib.request.urlopen", side_effect=wrapped):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"

    def test_connection_error_maps_to_unavailable_aierror(self):
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"
        assert "connection error" in str(exc_info.value)

    def test_plain_url_error_maps_to_network_error(self):
        network_error = urllib.error.URLError(ConnectionError("connection refused"))
        with mock.patch("urllib.request.urlopen", side_effect=network_error):
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "unavailable"
        assert "network error" in str(exc_info.value)

    def test_error_field_maps_to_bad_response_aierror(self):
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http({"error": "overloaded"})
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"
        assert "overloaded" in str(exc_info.value)

    def test_malformed_payload_maps_to_bad_response_aierror(self):
        payload = {"unexpected": "shape"}
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = fake_http(payload)
            with pytest.raises(AIError) as exc_info:
                self.make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"
        assert "unexpected payload" in str(exc_info.value)


class TestResponseLimit:
    """A provider that returns a body larger than MAX_RESPONSE_BYTES must be
    rejected as bad_response (H-02) — never parsed, never returned."""

    @pytest.mark.parametrize(
        "make_provider",
        [
            lambda: GeminiProvider(api_key="k", model="m", timeout=5),
            lambda: OllamaProvider(model="m", timeout=5),
            lambda: OpenAIProvider(api_key="k", model="m", base_url="http://x/v1", timeout=5),
            lambda: AnthropicProvider(api_key="k", model="m", base_url="http://x/v1", timeout=5),
        ],
    )
    def test_oversized_response_is_rejected(self, make_provider):
        from relay.ai.base import MAX_RESPONSE_BYTES

        response = mock.Mock()
        response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = response
            with pytest.raises(AIError) as exc_info:
                make_provider().generate_commit_message("d", "s", "b")
        assert exc_info.value.kind == "bad_response"

    def test_read_limited_accepts_exactly_at_limit(self):
        from relay.ai.base import MAX_RESPONSE_BYTES, read_limited_response

        response = mock.Mock()
        response.read.return_value = b"x" * MAX_RESPONSE_BYTES
        assert read_limited_response(response, "gemini") == b"x" * MAX_RESPONSE_BYTES

    def test_read_limited_rejects_over_limit(self):
        from relay.ai.base import MAX_RESPONSE_BYTES, read_limited_response

        response = mock.Mock()
        response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        with pytest.raises(AIError) as exc_info:
            read_limited_response(response, "gemini")
        assert exc_info.value.kind == "bad_response"
        response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)


class TestBuildPrompt:
    def test_includes_context_and_commit_rules(self):
        prompt = AIManager.build_prompt("DIFF", "STAT", "main")
        assert "DIFF" in prompt
        assert "STAT" in prompt
        assert "main" in prompt
        assert "type(scope): subject" in prompt


class TestDiffTruncation:
    def test_small_diff_is_passthrough(self):
        small = "line1\nline2\n"
        result, was_truncated = truncate_diff(small, max_lines=120)
        assert result == small
        assert was_truncated is False

    def test_large_diff_is_capped_with_notice(self):
        big = "\n".join(f"+line {i}" for i in range(200))
        result, was_truncated = truncate_diff(big, max_lines=100)
        assert was_truncated is True
        assert result.startswith("+line 0")
        assert "+line 199" not in result
        assert "truncated" in result

    def test_build_prompt_keeps_stat_and_caps_diff(self):
        big = "\n".join(f"+line {i}" for i in range(500))
        prompt = AIManager.build_prompt(big, "STAT-SUMMARY", "main", max_lines=120)
        assert "STAT-SUMMARY" in prompt  # --stat summary is always intact
        assert "+line 499" not in prompt
        assert "truncated" in prompt

    def test_build_prompt_small_diff_has_no_truncation_notice(self):
        prompt = AIManager.build_prompt("+small\n", "S", "main", max_lines=120)
        assert "truncated" not in prompt


class TestTimeoutCaps:
    def test_gemini_timeout_clamped_to_120_seconds_max(self):
        assert GeminiProvider(api_key="k", model="m", timeout=999).timeout == 120

    def test_gemini_reasonable_override_is_preserved(self):
        assert GeminiProvider(api_key="k", model="m", timeout=45).timeout == 45

    def test_gemini_timeout_defaults_from_env(self, monkeypatch):
        monkeypatch.delenv("RELAY_AI_TIMEOUT", raising=False)
        assert GeminiProvider(api_key="k", model="m").timeout == 30

    def test_ollama_timeout_clamped_to_120_seconds_max(self):
        assert OllamaProvider(model="m", timeout=999).timeout == 120

    def test_ollama_reasonable_override_is_preserved(self):
        assert OllamaProvider(model="m", timeout=45).timeout == 45

    def test_openai_timeout_clamped_to_120_seconds_max(self):
        p = OpenAIProvider(api_key="k", model="m", base_url="http://x/v1", timeout=999)
        assert p.timeout == 120

    def test_anthropic_timeout_clamped_to_120_seconds_max(self):
        p = AnthropicProvider(api_key="k", model="m", base_url="http://x/v1", timeout=999)
        assert p.timeout == 120


class TestMissingApiKey:
    def test_openai_requires_key(self):
        with mock.patch("relay.ai.openai.openai_api_key", return_value=None):
            with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
                OpenAIProvider(base_url="http://x/v1")

    def test_anthropic_requires_key(self):
        with mock.patch("relay.ai.anthropic.anthropic_api_key", return_value=None):
            with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
                AnthropicProvider(base_url="http://x/v1")


class TestBuildProvider:
    """The registry (relay/ai/__init__.py) maps a flag/env value to a provider."""

    def test_explicit_name_constructs_that_provider(self):
        with mock.patch("relay.ai.openai.openai_api_key", return_value="k"), mock.patch(
            "relay.ai.anthropic.anthropic_api_key", return_value="k"
        ):
            assert isinstance(build_provider("ollama"), OllamaProvider)
            assert isinstance(build_provider("openai"), OpenAIProvider)
            assert isinstance(build_provider("anthropic"), AnthropicProvider)

    def test_explicit_gemini_constructs_gemini(self):
        with mock.patch("relay.ai.gemini.gemini_api_key", return_value="k"):
            assert isinstance(build_provider("gemini"), GeminiProvider)

    def test_name_is_case_insensitive(self):
        with mock.patch("relay.ai.openai.openai_api_key", return_value="k"):
            assert isinstance(build_provider("OpenAI"), OpenAIProvider)

    def test_default_provider_comes_from_env(self):
        with mock.patch("relay.config.provider_from_env", return_value="gemini"), mock.patch(
            "relay.ai.gemini.gemini_api_key", return_value="k"
        ):
            assert isinstance(build_provider(), GeminiProvider)

    def test_explicit_name_beats_env_default(self):
        with mock.patch("relay.config.provider_from_env", return_value="gemini"), mock.patch(
            "relay.ai.openai.openai_api_key", return_value="k"
        ):
            assert isinstance(build_provider("openai"), OpenAIProvider)

    def test_unknown_provider_raises_config_error(self):
        with mock.patch("relay.config.provider_from_env", return_value="gemini"):
            with pytest.raises(ConfigError) as exc_info:
                build_provider("warp-drive")
        assert "unknown AI provider 'warp-drive'" in str(exc_info.value)
        assert "gemini" in str(exc_info.value)
        assert "ollama" in str(exc_info.value)

    def test_unknown_provider_from_env_raises_config_error(self):
        with mock.patch("relay.config.provider_from_env", return_value="warp-drive"):
            with pytest.raises(ConfigError, match="unknown AI provider"):
                build_provider()


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
