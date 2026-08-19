"""xAI provider (OpenAI-compatible ``/chat/completions`` API).

xAI's hosted API is OpenAI-compatible, so this provider is a thin subclass of
:class:`OpenAIProvider` that reads xAI-specific configuration
(``XAI_API_KEY``, ``XAI_MODEL``, ``XAI_BASE_URL``) instead of the OpenAI ones —
no duplicated request machinery, matching the tool's zero-dependency
philosophy.
"""
from __future__ import annotations

from ..config import ai_timeout, xai_api_key, xai_base_url, xai_model
from ..errors import ConfigError
from .openai import OpenAIProvider


class XaiProvider(OpenAIProvider):
    provider_name = "xai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or xai_api_key()
        if not self.api_key:
            raise ConfigError(
                "XAI_API_KEY is not set. Export it in your shell, e.g.\n"
                '    set XAI_API_KEY=...        (Windows cmd)\n'
                '    $env:XAI_API_KEY="..."     (PowerShell)\n'
                '    export XAI_API_KEY=...     (macOS/Linux)'
            )
        self.model = model or xai_model()
        self.base_url = (base_url or xai_base_url()).rstrip("/")
        self.timeout = ai_timeout(timeout)
