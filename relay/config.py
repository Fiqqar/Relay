"""Thin configuration layer.

v1 keeps configuration to environment variables + CLI flags (matching the
"global CLI" goal: nothing to install or manage). Everything is resolved here,
so a ~/.config/relay/config.toml file can be added later without touching any
call site.

Precedence: flags > environment variables > config file > defaults. Flags are
applied by the CLI layer (via the ``override`` args); this module resolves the
file-vs-env-vs-default ordering for everything else. Secrets (``GEMINI_API_KEY``,
``GITHUB_TOKEN`` / ``GH_TOKEN``) deliberately stay env-variable-only — they are
never read from the config file (NFR-3), so a config file can happily live in a
repo or be shared without leaking credentials.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # Python 3.11+
    import tomllib

    # Stdlib parser. tomllib.TOMLDecodeError is a ValueError subclass.
    _load_toml = tomllib.load
    _TOML_DECODE_ERROR = tomllib.TOMLDecodeError
except ModuleNotFoundError:  # Python 3.10 — fall back to the bundled parser
    from . import toml

    # relay/toml.py is a tiny dependency-free parser with a tomllib-compatible
    # load(); it raises ValueError (with a line number) on malformed TOML.
    _load_toml = toml.load
    _TOML_DECODE_ERROR = ValueError

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

# Maps each environment variable to its ``[relay]`` table key in config.toml.
_CFG_KEYS = {
    "RELAY_AI_PROVIDER": "provider",
    "GEMINI_MODEL": "gemini_model",
    "OLLAMA_BASE_URL": "ollama_base_url",
    "OLLAMA_MODEL": "ollama_model",
    "RELAY_BRANCH_TEMPLATE": "branch_template",
    "RELAY_AI_TIMEOUT": "ai_timeout",
    "RELAY_MAX_DIFF_LINES": "max_diff_lines",
    "RELAY_PR_OPEN": "pr_open",
}

# Secret env vars that must never be resolved from the config file.
# ``provider`` is not secret but follows the same env-first rule so the file can
# stay free of credentials; these are excluded from _CFG_KEYS' file fallback.
_ENV_ONLY = {"GEMINI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"}


def config_file_path() -> Path | None:
    """Path of the TOML config file, honoring ``RELAY_CONFIG``.

    Lookup order: the ``RELAY_CONFIG`` env var if set > platform default
    (``$XDG_CONFIG_HOME/relay/config.toml`` on POSIX, ``%APPDATA%\\relay\\
    config.toml`` on Windows). Returns None when the platform default cannot be
    determined (e.g. no APPDATA on Windows).
    """
    explicit = os.environ.get("RELAY_CONFIG")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return Path(base) / "relay" / "config.toml" if base else None
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "relay" / "config.toml"
    return Path.home() / ".config" / "relay" / "config.toml"


def _load_config() -> dict:
    """Parse the ``[relay]`` table from the config file (or {} when absent)."""
    path = config_file_path()
    if path is None or not path.is_file():
        return {}
    try:
        with open(path, "rb") as fh:
            data = _load_toml(fh)
    except (OSError, _TOML_DECODE_ERROR):
        return {}
    section = data.get("relay")
    if not isinstance(section, dict):
        return {}
    return section


def _resolve(env_key: str, cfg_key: str, default):
    """resolve(env_key, cfg_key, default): env > file > default.

    Returns ``default`` when neither the env var nor the config file defines a
    value. Secrets are env-only because their ``cfg_key`` is never consulted.
    """
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val
    if env_key not in _ENV_ONLY:
        file_val = _load_config().get(cfg_key)
        if file_val is not None:
            return file_val
    return default


def provider_from_env() -> str:
    resolved = _resolve("RELAY_AI_PROVIDER", "provider", DEFAULT_PROVIDER)
    return str(resolved).lower()


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def gemini_model() -> str:
    return str(_resolve("GEMINI_MODEL", "gemini_model", DEFAULT_GEMINI_MODEL))


def ollama_base_url() -> str:
    return str(_resolve("OLLAMA_BASE_URL", "ollama_base_url", DEFAULT_OLLAMA_BASE_URL))


def ollama_model() -> str:
    return str(_resolve("OLLAMA_MODEL", "ollama_model", DEFAULT_OLLAMA_MODEL))


def branch_template() -> str:
    return str(_resolve("RELAY_BRANCH_TEMPLATE", "branch_template", DEFAULT_BRANCH_TEMPLATE))


def ai_timeout(override: int | None = None) -> int:
    """HTTP timeout in seconds for AI calls.

    Resolution order: explicit ``override`` (CLI ``--timeout``) > the
    ``RELAY_AI_TIMEOUT`` env var > the ``ai_timeout`` config-file key > the
    default. The result is always clamped to the safety range
    [1, MAX_AI_TIMEOUT_SECONDS] so a typo like ``--timeout 0`` or ``99999`` can
    never disable the fallback or hang the workflow forever.
    """
    if override is None:
        requested = _resolve("RELAY_AI_TIMEOUT", "ai_timeout", DEFAULT_AI_TIMEOUT_SECONDS)
    else:
        requested = override
    try:
        requested = int(requested)
    except (ValueError, TypeError):
        requested = DEFAULT_AI_TIMEOUT_SECONDS
    return max(1, min(requested, MAX_AI_TIMEOUT_SECONDS))


def max_diff_lines() -> int:
    """Line cap applied to the staged diff before it is sent to the LLM."""
    try:
        return int(_resolve("RELAY_MAX_DIFF_LINES", "max_diff_lines", DEFAULT_MAX_DIFF_LINES))
    except ValueError:
        return DEFAULT_MAX_DIFF_LINES


def pr_open_browser() -> bool:
    """Whether ``relay pr`` should auto-open the PR in the default browser.

    Honors a truthy ``RELAY_PR_OPEN`` env var (1/true/yes/on) or the
    ``pr_open`` config-file key, so it can be enabled globally without repeating
    ``--open`` on every invocation.
    """
    resolved = str(_resolve("RELAY_PR_OPEN", "pr_open", "")).strip().lower()
    return resolved in ("1", "true", "yes", "on")