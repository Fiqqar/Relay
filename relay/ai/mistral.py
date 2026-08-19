"""Mistral provider (OpenAI-compatible ``/chat/completions`` API).

Mistral's hosted API speaks the same chat-completions protocol as OpenAI, so
this provider is a thin subclass of :class:`OpenAIProvider` that reads
Mistral-specific configuration (``MISTRAL_API_KEY``, ``MISTRAL_MODEL``,
``MISTRAL_BASE_URL``) instead of the OpenAI ones — no duplicated request
machinery, matching the tool's zero-dependency philosophy.
"""
from __future__ import annotations

from ..config import ai_timeout, mistral_api_key, mistral_base_url, mistral_model
from ..errors import ConfigError
from .openai import OpenAIProvider


class MistralProvider(OpenAIProvider):
    provider_name = "mistral"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or mistral_api_key()
        if not self.api_key:
            raise ConfigError(
                "MISTRAL_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set MISTRAL_API_KEY=...        (Windows cmd)\n'
                '    $env:MISTRAL_API_KEY="..."     (PowerShell)\n'
                '    export MISTRAL_API_KEY=...     (macOS/Linux)'
            )
        self.model = model or mistral_model()
        self.base_url = (base_url or mistral_base_url()).rstrip("/")
        self.timeout = ai_timeout(timeout)
