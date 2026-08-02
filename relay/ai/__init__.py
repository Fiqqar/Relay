"""AI provider registry — the single place that maps a flag/config value to a
provider class. Add a new provider here and it becomes selectable everywhere.
"""
from __future__ import annotations

from ..errors import ConfigError
from .base import AIManager
from .gemini import GeminiProvider
from .ollama import OllamaProvider

_PROVIDERS = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def build_provider(name: str | None = None) -> AIManager:
    """Construct the requested provider (or the default from the environment).

    Imported lazily to avoid a circular import at module load time.
    """
    from ..config import provider_from_env

    chosen = (name or provider_from_env()).lower()
    if chosen not in _PROVIDERS:
        raise ConfigError(
            f"unknown AI provider '{chosen}'; choose from: {', '.join(sorted(_PROVIDERS))}"
        )
    return _PROVIDERS[chosen]()


__all__ = ["AIManager", "build_provider"]
