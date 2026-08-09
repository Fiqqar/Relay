"""AI provider registry — the single place that maps a flag/config value to a
provider class. Add a new provider here and it becomes selectable everywhere.
"""
from __future__ import annotations

from ..errors import ConfigError
from .anthropic import AnthropicProvider
from .base import AIManager
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider

_PROVIDERS = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}

PROVIDER_NAMES = tuple(sorted(_PROVIDERS))


def build_provider(name: str | None = None, timeout: int | None = None) -> AIManager:
    """Construct the requested provider (or the default from the environment).

    ``timeout`` is an optional per-run override in seconds (e.g. from
    ``relay --timeout``); the provider still clamps it to a safe maximum.

    Imported lazily to avoid a circular import at module load time.
    """
    from ..config import provider_from_env

    chosen = (name or provider_from_env()).lower()
    if chosen not in _PROVIDERS:
        raise ConfigError(
            f"unknown AI provider '{chosen}'; choose from: {', '.join(sorted(_PROVIDERS))}"
        )
    return _PROVIDERS[chosen](timeout=timeout)


__all__ = [
    "AIManager",
    "PROVIDER_NAMES",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "build_provider",
]
