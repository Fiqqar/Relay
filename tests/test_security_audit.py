"""Static AST security audit tests for NFR-3.

NFR-3: Secrets are environment-only, never read from config files, never logged.
Subprocesses must always use shell=False and argv-as-list.
"""
from __future__ import annotations

from pathlib import Path

from relay.config import _CFG_KEYS, _ENV_ONLY

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_secrets_are_strictly_env_only():
    """All secret credential tokens and AI base URLs must be in _ENV_ONLY.

    A repo-local RELAY_CONFIG must never be able to define credentials or redirect
    credential-bearing requests (ADR-005).
    """
    required_secrets = {
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "OLLAMA_BASE_URL",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "MISTRAL_BASE_URL",
        "GROQ_BASE_URL",
        "XAI_BASE_URL",
    }
    assert required_secrets <= _ENV_ONLY

    # No secret key may appear in _CFG_KEYS (which maps env vars to config file keys)
    for secret in required_secrets:
        assert secret not in _CFG_KEYS, f"Secret {secret} must not be mapped to config file"
