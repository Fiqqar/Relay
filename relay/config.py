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
DEFAULT_BRANCH_TEMPLATE = "<type>/<feature>"

# Performance knobs: keep the diff payload small and give the LLM a realistic
# window to respond. 30s is enough for normal network conditions (and large
# diffs) while still falling back to manual input if the provider hangs.
DEFAULT_AI_TIMEOUT_SECONDS = 30
MAX_AI_TIMEOUT_SECONDS = 120  # safety clamp: never wait longer than this on an LLM
DEFAULT_MAX_DIFF_LINES = 120


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


def ai_timeout(override: int | None = None) -> int:
    """HTTP timeout in seconds for AI calls.

    Resolution order: explicit ``override`` (CLI ``--timeout``) > the
    ``RELAY_AI_TIMEOUT`` env var > the default. The result is always clamped to
    the safety range [1, MAX_AI_TIMEOUT_SECONDS] so a typo like ``--timeout 0``
    or ``99999`` can never disable the fallback or hang the workflow forever.
    """
    try:
        requested = int(
            os.environ.get("RELAY_AI_TIMEOUT", DEFAULT_AI_TIMEOUT_SECONDS)
            if override is None
            else override
        )
    except (ValueError, TypeError):
        requested = DEFAULT_AI_TIMEOUT_SECONDS
    return max(1, min(requested, MAX_AI_TIMEOUT_SECONDS))


def max_diff_lines() -> int:
    """Line cap applied to the staged diff before it is sent to the LLM."""
    try:
        return int(os.environ.get("RELAY_MAX_DIFF_LINES", DEFAULT_MAX_DIFF_LINES))
    except ValueError:
        return DEFAULT_MAX_DIFF_LINES


def pr_open_browser() -> bool:
    """Whether ``relay pr`` should auto-open the PR in the default browser.

    Honors a truthy ``RELAY_PR_OPEN`` env var (1/true/yes/on), so the behavior
    can be enabled globally without repeating ``--open`` on every invocation.
    """
    return os.environ.get("RELAY_PR_OPEN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
