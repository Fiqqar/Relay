"""Gemini provider (Google Generative Language REST API).

Deliberately uses only the stdlib (``urllib``) instead of the
``google-generativeai`` SDK so Relay keeps its zero-runtime-dependency promise
— ``pip install .`` works even on a fully offline machine.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from ..config import ai_timeout, gemini_api_key, gemini_model
from ..errors import AIError, ConfigError
from .base import AIManager, read_limited_response

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class GeminiProvider(AIManager):
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: int | None = None):
        self.api_key = api_key or gemini_api_key()
        if not self.api_key:
            # Fail fast with a clear, platform-specific message BEFORE the
            # workflow mutates anything. This becomes a ConfigError -> exit 1.
            raise ConfigError(
                "GEMINI_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set GEMINI_API_KEY=your_key        (Windows cmd)\n'
                '    $env:GEMINI_API_KEY="your_key"     (PowerShell)\n'
                '    export GEMINI_API_KEY=your_key     (macOS/Linux)'
            )
        self.model = model or gemini_model()
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
    ) -> str:
        prompt = self.build_prompt(
            diff, stat, branch, recent_commits=recent_commits
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
            _ENDPOINT.format(model=quoted_model),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                data = json.loads(
                    read_limited_response(response, self.provider_name).decode("utf-8")
                )
        except urllib.error.HTTPError as exc:
            # Map HTTP status codes to AIError kinds the fallback understands:
            # 429 = rate limited (transient), 5xx = server unavailable.
            if exc.code == 429:
                kind = "rate_limited"
            elif exc.code >= 500:
                kind = "unavailable"
            else:
                kind = "api_error"
            raise AIError(self.provider_name, kind, f"HTTP {exc.code}: {exc.reason}") from exc
        except TimeoutError as exc:
            # Timeout hit (a real network outage or a hung provider): treat as
            # "unavailable" so the Orchestrator falls back to manual input
            # instead of hanging.
            raise AIError(self.provider_name, "unavailable", f"timeout after {self.timeout}s") from exc
        except urllib.error.URLError as exc:
            # urllib wraps socket.timeout (and other OSErrors) in URLError; a
            # wrapped timeout must be treated identically to a direct one.
            if isinstance(exc.reason, TimeoutError):
                raise AIError(self.provider_name, "unavailable", f"timeout after {self.timeout}s") from exc
            raise AIError(self.provider_name, "unavailable", f"network error: {exc}") from exc
        except ConnectionError as exc:
            raise AIError(self.provider_name, "unavailable", f"connection error: {exc}") from exc

        if "error" in data:
            raise AIError(self.provider_name, "bad_response", str(data["error"]))

        # Gemini wraps the answer in candidates[0].content.parts[0].text.
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}") from exc
