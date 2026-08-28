"""Groq provider (OpenAI-compatible ``/chat/completions`` API).

Groq's hosted API is OpenAI-compatible, so this provider is a thin subclass of
:class:`OpenAIProvider` that reads Groq-specific configuration
(``GROQ_API_KEY``, ``GROQ_MODEL``, ``GROQ_BASE_URL``) instead of the OpenAI
ones — no duplicated request machinery, matching the tool's zero-dependency
philosophy.
"""
from __future__ import annotations

from ..config import ai_timeout, groq_api_key, groq_base_url, groq_model
from ..errors import ConfigError
from ..telemetry import _is_valid_ai_base_url
from .openai import OpenAIProvider


class GroqProvider(OpenAIProvider):
    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or groq_api_key()
        if not self.api_key:
            raise ConfigError(
                "GROQ_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set GROQ_API_KEY=...        (Windows cmd)\n'
                '    $env:GROQ_API_KEY="..."     (PowerShell)\n'
                '    export GROQ_API_KEY=...     (macOS/Linux)'
            )
        self.model = model or groq_model()
        self.base_url = (base_url or groq_base_url()).rstrip("/")
        if not _is_valid_ai_base_url(self.base_url):
            raise ConfigError(
                f"invalid AI base URL {self.base_url!r} (use https:// for public hosts, http:// only for localhost; see `relay --help`)"
            )
        self.timeout = ai_timeout(timeout)
