"""Thin configuration layer.

v1 keeps configuration to environment variables + CLI flags (matching the
"global CLI" goal: nothing to install or manage). Everything is resolved here,
so a ~/.config/relay/config.toml file could be added later without touching
any call site.
"""
from __future__ import annotations

import os

DEFAULT_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_BRANCH_TEMPLATE = "status/<feature>"


def provider_from_env() -> str:
    return os.environ.get("RELAY_AI_PROVIDER", DEFAULT_PROVIDER).lower()


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def branch_template() -> str:
    return os.environ.get("RELAY_BRANCH_TEMPLATE", DEFAULT_BRANCH_TEMPLATE)
