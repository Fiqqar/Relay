"""Gemini provider (Google Generative Language REST API).

Deliberately uses only the stdlib (``urllib``) instead of the
``google-generativeai`` SDK so Relay keeps its zero-runtime-dependency promise
— ``pip install .`` works even on a fully offline machine.

``GEMINI_BASE_URL`` (env-only) points the provider at a proxy or an enterprise
gateway, giving Gemini the same BYO-endpoint story as every other provider. The
value is validated with the shared SSRF guard before any request is built.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from ..config import ai_timeout, gemini_api_key, gemini_base_url, gemini_model
from ..errors import AIError, ConfigError
from ..telemetry import _is_valid_ai_base_url
from .base import AIManager, decode_provider_json, normalize_transport_error, read_limited_response

# Path appended to the configured base URL. A gateway may hang Gemini off a
# prefix (``https://gateway.example/gemini``), so this is joined to the base
# rather than replacing it.
_ENDPOINT_PATH = "/v1beta/models/{model}:generateContent"


class GeminiProvider(AIManager):
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or gemini_api_key()
        if not self.api_key:
            # No key: raise ConfigError with setup instructions. The CLI
            # catches this and degrades to manual input (ADR-004) instead of
            # aborting — so this must stay a ConfigError, never an exit here.
            raise ConfigError(
                "GEMINI_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set GEMINI_API_KEY=your_key        (Windows cmd)\n'
                '    $env:GEMINI_API_KEY="your_key"     (PowerShell)\n'
                '    export GEMINI_API_KEY=your_key     (macOS/Linux)'
            )
        self.model = model or gemini_model()
        # Proxies / enterprise gateways front the API through their own host.
        # The shared guard keeps the API key from following a redirect to a
        # private address (or riding along over plain http to a public host).
        self.base_url = (base_url or gemini_base_url()).rstrip("/")
        if not _is_valid_ai_base_url(self.base_url):
            raise ConfigError(
                f"invalid AI base URL {self.base_url!r} (use https:// for public hosts, http:// only for localhost; see `relay --help`)"
            )
        # Give the API a realistic window to respond (default 30s, safety cap
        # 120s). A genuinely hung provider still hits the cap and the
        # Orchestrator falls back to manual input.
        self.timeout = ai_timeout(timeout)

    def generate_commit_message(
        self,
        diff: str,
        stat: str,
        branch: str,
        recent_commits: list[str] | None = None,
        rejected_message: str | None = None,
    ) -> str:
        prompt = self.build_prompt(
            diff,
            stat,
            branch,
            recent_commits=recent_commits,
            rejected_message=rejected_message,
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }

        headers = {"Content-Type": "application/json"}
        assert self.api_key is not None
        if self.api_key.startswith("AQ."):
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["X-Goog-Api-Key"] = self.api_key

        quoted_model = urllib.parse.quote(self.model, safe="")
        request = urllib.request.Request(
            f"{self.base_url}{_ENDPOINT_PATH.format(model=quoted_model)}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                data = decode_provider_json(
                    read_limited_response(response, self.provider_name), self.provider_name
                )
        except (
            urllib.error.HTTPError,
            TimeoutError,
            urllib.error.URLError,
            ConnectionError,
        ) as exc:
            raise normalize_transport_error(
                exc, provider=self.provider_name, timeout=self.timeout
            ) from exc

        if "error" in data:
            raise AIError(self.provider_name, "bad_response", str(data["error"]))

        # Gemini wraps the answer in candidates[0].content.parts[0].text.
        # A JSON null there yields None, not a string — reject it here so a
        # non-string can never reach sanitize_ai_message downstream.
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}") from exc
        if not isinstance(text, str):
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}")
        return text
