"""OpenAI provider (and any OpenAI-compatible server: llama.cpp, vLLM, ...).

Uses only the stdlib (``urllib``) like the other providers, so Relay keeps its
zero-runtime-dependency promise. Because llama.cpp, Ollama's OpenAI endpoint,
vLLM, etc. all speak the ``/chat/completions`` protocol, pointing
``OPENAI_BASE_URL`` at a local server turns this same provider into a bridge to
any of them — no extra code paths needed.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import ai_timeout, openai_api_key, openai_base_url, openai_model
from ..errors import AIError, ConfigError
from .base import AIManager, read_limited_response


class OpenAIProvider(AIManager):
    provider_name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, timeout: int | None = None):
        self.api_key = api_key or openai_api_key()
        if not self.api_key:
            raise ConfigError(
                "OPENAI_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set OPENAI_API_KEY=sk-...        (Windows cmd)\n'
                '    $env:OPENAI_API_KEY="sk-..."     (PowerShell)\n'
                '    export OPENAI_API_KEY=sk-...     (macOS/Linux)'
            )
        self.model = model or openai_model()
        # The API base already includes the /v1 prefix by default, and llama.cpp
        # exposes /v1 too, so /chat/completions is appended verbatim.
        self.base_url = (base_url or openai_base_url()).rstrip("/")
        self.timeout = ai_timeout(timeout)

    def generate_commit_message(self, diff: str, stat: str, branch: str) -> str:
        prompt = self.build_prompt(diff, stat, branch)
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 80,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(
                    read_limited_response(response, self.provider_name).decode("utf-8")
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                kind = "rate_limited"
            elif exc.code >= 500:
                kind = "unavailable"
            else:
                kind = "api_error"
            raise AIError(self.provider_name, kind, f"HTTP {exc.code}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AIError(self.provider_name, "unavailable", f"timeout after {self.timeout}s") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise AIError(self.provider_name, "unavailable", f"timeout after {self.timeout}s") from exc
            raise AIError(self.provider_name, "unavailable", f"network error: {exc}") from exc
        except ConnectionError as exc:
            raise AIError(self.provider_name, "unavailable", f"connection error: {exc}") from exc
        if "error" in data:
            raise AIError(self.provider_name, "bad_response", str(data["error"]))
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}") from exc
