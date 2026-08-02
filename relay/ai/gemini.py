"""Gemini provider (Google Generative Language REST API).

Deliberately uses only the stdlib (``urllib``) instead of the
``google-generativeai`` SDK so Relay keeps its zero-runtime-dependency promise
— ``pip install .`` works even on a fully offline machine.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import gemini_api_key, gemini_model
from ..errors import AIError, ConfigError
from .base import AIManager

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class GeminiProvider(AIManager):
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: int = 30):
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
        self.timeout = timeout

    def generate_commit_message(self, diff: str, stat: str, branch: str) -> str:
        prompt = self.build_prompt(diff, stat, branch)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        request = urllib.request.Request(
            _ENDPOINT.format(model=self.model),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
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
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise AIError(self.provider_name, "unavailable", f"network error: {exc}") from exc

        # Gemini wraps the answer in candidates[0].content.parts[0].text.
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}") from exc
