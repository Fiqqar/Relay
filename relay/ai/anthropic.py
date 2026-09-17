"""Anthropic provider (Messages API).

Same stdlib-only approach as the other providers, so Relay keeps its
zero-runtime-dependency promise. Polls ``/v1/messages`` with ``x-api-key``
auth and reads the answer from ``content[0].text``.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import (
    ai_timeout,
    anthropic_api_key,
    anthropic_base_url,
    anthropic_model,
)
from ..errors import AIError, ConfigError
from ..telemetry import _is_valid_ai_base_url
from .base import AIManager, decode_provider_json, normalize_transport_error, read_limited_response


class AnthropicProvider(AIManager):
    provider_name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, timeout: int | None = None):
        self.api_key = api_key or anthropic_api_key()
        if not self.api_key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set ANTHROPIC_API_KEY=sk-ant-...        (Windows cmd)\n'
                '    $env:ANTHROPIC_API_KEY="sk-ant-..."     (PowerShell)\n'
                '    export ANTHROPIC_API_KEY=sk-ant-...     (macOS/Linux)'
            )
        self.model = model or anthropic_model()
        self.base_url = (base_url or anthropic_base_url()).rstrip("/")
        if not _is_valid_ai_base_url(self.base_url):
            raise ConfigError(
                f"invalid AI base URL {self.base_url!r} (use https:// for public hosts, http:// only for localhost; see `relay --help`)"
            )
        self.timeout = ai_timeout(timeout)

    def generate_commit_message(
        self,
        diff: str,
        stat: str,
        branch: str,
        recent_commits: list[str] | None = None,
        rejected_message: str | None = None,
    ) -> str:
        assert self.api_key is not None
        prompt = self.build_prompt(
            diff,
            stat,
            branch,
            recent_commits=recent_commits,
            rejected_message=rejected_message,
        )
        payload = {
            "model": self.model,
            "max_tokens": 80,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        request = urllib.request.Request(
            f"{self.base_url}/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
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
        # Messages API puts the text in content[0].text.
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}") from exc
        if not isinstance(text, str):
            raise AIError(self.provider_name, "bad_response", f"unexpected payload: {data}")
        return text
