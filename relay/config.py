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

The parsed config file is cached per (path, mtime, size) so a CLI run reads it
at most once even though individual getters (provider, model, branch template,
timeouts, protected branches) each resolve through it.
"""
from __future__ import annotations

import os
import re
import sys
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
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MISTRAL_MODEL = "mistral-small-latest"
DEFAULT_MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_XAI_MODEL = "grok-beta"
DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_BRANCH_TEMPLATE = "<type>/<feature>"

# Branches the default-branch safety rule refuses to touch, when neither the
# env var nor the config file overrides them. `main`/`master` cover the two
# canonical GitHub/older default-branch names.
DEFAULT_PROTECTED_BRANCHES = ["main", "master"]

# GitLab hosts `relay pr` may send GITLAB_TOKEN to without an explicit opt-in.
# The host comes from the repo's `origin` remote — attacker-controllable data —
# so anything outside this allowlist is refused unless the user trusts it
# explicitly (RELAY_TRUSTED_GITLAB_HOSTS / `trusted_gitlab_hosts`).
DEFAULT_TRUSTED_GITLAB_HOSTS = ("gitlab.com",)

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
    "OLLAMA_MODEL": "ollama_model",
    "OPENAI_MODEL": "openai_model",
    "ANTHROPIC_MODEL": "anthropic_model",
    "MISTRAL_MODEL": "mistral_model",
    "GROQ_MODEL": "groq_model",
    "XAI_MODEL": "xai_model",
    "RELAY_BRANCH_TEMPLATE": "branch_template",
    "RELAY_AI_TIMEOUT": "ai_timeout",
    "RELAY_MAX_DIFF_LINES": "max_diff_lines",
    "RELAY_PR_OPEN": "pr_open",
}

# Secret env vars that must never be resolved from the config file.
# ``provider`` is not secret but follows the same env-first rule so the file can
# stay free of credentials; these are excluded from _CFG_KEYS' file fallback.
# AI base URLs are also env-only: a config file that can be pointed at an
# untrusted repo must not be able to redirect credential-bearing requests.
_ENV_ONLY = {
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

# Parsed config-file cache: {(path, mtime_ns, size): document}. Invalidated by
# a file change (mtime/size), so getters resolve the file only once per state.
_RAW_CACHE: dict[tuple[str, int, int], dict] = {}


def _warn_invalid(setting: str, value) -> None:
    """One-line stderr notice when a numeric setting cannot be parsed, so a
    typo like ``RELAY_AI_TIMEOUT=abc`` is visible instead of silently ignored."""
    print(
        f"[relay] warning: ignoring invalid {setting}={value!r}; using the default",
        file=sys.stderr,
    )


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


def _load_raw() -> dict:
    """Parse the whole TOML config file (or {} when absent/unparseable).

    ``_load_config`` and ``_load_team_protected`` slice the document they
    need, so the ``[relay]`` and ``[team.protected]`` tables can coexist in
    one file without the parser opening it twice.

    The result is cached keyed on (path, mtime, size): the file is re-read
    only when it actually changes on disk, so a single CLI run that resolves
    several settings touches the file once instead of once per getter.
    """
    path = config_file_path()
    if path is None or not path.is_file():
        return {}
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = _RAW_CACHE.get(key)
        if cached is not None:
            return cached
        with open(path, "rb") as fh:
            data = _load_toml(fh)
        _RAW_CACHE[key] = data
        return data
    except OSError:
        return {}
    except _TOML_DECODE_ERROR:
        # A malformed config file is not a hard error (the defaults still make
        # Relay run), but it must not be silent either — the developer wrote
        # something and it is not being honored (L-15). Cache the failure so the
        # warning is printed once per state, not once per getter.
        print(
            f"[relay] warning: ignoring malformed config file {path}; using defaults",
            file=sys.stderr,
        )
        _RAW_CACHE[key] = {}
        return {}


def _load_config() -> dict:
    """Parse the ``[relay]`` table from the config file (or {} when absent)."""
    section = _load_raw().get("relay")
    if not isinstance(section, dict):
        return {}
    return section


def _load_team_protected() -> dict:
    """Parse the ``[team.protected]`` table from the config file (or {})."""
    team = _load_raw().get("team")
    if not isinstance(team, dict):
        return {}
    protected = team.get("protected")
    return protected if isinstance(protected, dict) else {}


def _load_ai() -> dict:
    """Parse the ``[ai]`` table from the config file (or {} when absent)."""
    section = _load_raw().get("ai")
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
    """The default AI provider, lowercased.

    Resolution order: ``RELAY_AI_PROVIDER`` env var > ``[relay] provider`` in
    the config file > ``[ai] default`` in the config file > the built-in
    default (``gemini``). The ``[ai]`` table gives a config file a second,
    dedicated knob for the default provider without touching the ``[relay]``
    table or the env var — useful when a team wants to standardize on one
    provider across machines.
    """
    env_val = os.environ.get("RELAY_AI_PROVIDER")
    if env_val is not None:
        return str(env_val).lower()
    relay_provider = _load_config().get("provider")
    if relay_provider is not None:
        return str(relay_provider).lower()
    ai_default = _load_ai().get("default")
    if ai_default is not None:
        return str(ai_default).lower()
    return DEFAULT_PROVIDER


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def gemini_model() -> str:
    return str(_resolve("GEMINI_MODEL", "gemini_model", DEFAULT_GEMINI_MODEL))


def ollama_base_url() -> str:
    return str(_resolve("OLLAMA_BASE_URL", "ollama_base_url", DEFAULT_OLLAMA_BASE_URL))


def ollama_model() -> str:
    return str(_resolve("OLLAMA_MODEL", "ollama_model", DEFAULT_OLLAMA_MODEL))


def openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


def openai_model() -> str:
    return str(_resolve("OPENAI_MODEL", "openai_model", DEFAULT_OPENAI_MODEL))


def openai_base_url() -> str:
    """Base URL for OpenAI-compatible endpoints (also covers llama.cpp).

    Point ``OPENAI_BASE_URL`` at a local server to talk to llama.cpp or
    vLLM, which expose the same ``/chat/completions`` API.
    """
    return str(_resolve("OPENAI_BASE_URL", "openai_base_url", DEFAULT_OPENAI_BASE_URL))


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def anthropic_model() -> str:
    return str(_resolve("ANTHROPIC_MODEL", "anthropic_model", DEFAULT_ANTHROPIC_MODEL))


def anthropic_base_url() -> str:
    return str(_resolve("ANTHROPIC_BASE_URL", "anthropic_base_url", DEFAULT_ANTHROPIC_BASE_URL))


def mistral_api_key() -> str | None:
    return os.environ.get("MISTRAL_API_KEY")


def mistral_model() -> str:
    return str(_resolve("MISTRAL_MODEL", "mistral_model", DEFAULT_MISTRAL_MODEL))


def mistral_base_url() -> str:
    """Base URL for the Mistral API (OpenAI-compatible ``/chat/completions``)."""
    return str(_resolve("MISTRAL_BASE_URL", "mistral_base_url", DEFAULT_MISTRAL_BASE_URL))


def groq_api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY")


def groq_model() -> str:
    return str(_resolve("GROQ_MODEL", "groq_model", DEFAULT_GROQ_MODEL))


def groq_base_url() -> str:
    """Base URL for the Groq API (OpenAI-compatible ``/chat/completions``)."""
    return str(_resolve("GROQ_BASE_URL", "groq_base_url", DEFAULT_GROQ_BASE_URL))


def xai_api_key() -> str | None:
    return os.environ.get("XAI_API_KEY")


def xai_model() -> str:
    return str(_resolve("XAI_MODEL", "xai_model", DEFAULT_XAI_MODEL))


def xai_base_url() -> str:
    """Base URL for the xAI API (OpenAI-compatible ``/chat/completions``)."""
    return str(_resolve("XAI_BASE_URL", "xai_base_url", DEFAULT_XAI_BASE_URL))


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
        _warn_invalid("RELAY_AI_TIMEOUT", requested)
        requested = DEFAULT_AI_TIMEOUT_SECONDS
    return max(1, min(requested, MAX_AI_TIMEOUT_SECONDS))


def max_diff_lines() -> int:
    """Line cap applied to the staged diff before it is sent to the LLM.

    Resolution order mirrors ``ai_timeout``: env > file > default, with the
    same tolerant parsing — a non-numeric value (``RELAY_MAX_DIFF_LINES=abc``)
    or a wrong-typed config entry (``max_diff_lines = [1, 2]`` or ``= true``)
    falls back to the default instead of crashing or silently capping the diff
    at an absurd one line.
    """
    resolved = _resolve("RELAY_MAX_DIFF_LINES", "max_diff_lines", DEFAULT_MAX_DIFF_LINES)
    if isinstance(resolved, bool):
        _warn_invalid("RELAY_MAX_DIFF_LINES", resolved)
        return DEFAULT_MAX_DIFF_LINES
    try:
        value = int(resolved)
    except (ValueError, TypeError):
        _warn_invalid("RELAY_MAX_DIFF_LINES", resolved)
        return DEFAULT_MAX_DIFF_LINES
    return max(1, value)  # a floor of 0 would send the AI an empty prompt


def pr_open_browser() -> bool:
    """Whether ``relay pr`` should auto-open the PR in the default browser.

    Honors a truthy ``RELAY_PR_OPEN`` env var (1/true/yes/on) or the
    ``pr_open`` config-file key, so it can be enabled globally without repeating
    ``--open`` on every invocation.
    """
    resolved = str(_resolve("RELAY_PR_OPEN", "pr_open", "")).strip().lower()
    return resolved in ("1", "true", "yes", "on")


def _split_branch_list(raw: str) -> list[str]:
    """Split a comma/space-separated env list of branch names."""
    return [item.strip() for item in re.split(r"[, ]+", raw) if item.strip()]


def _normalize_hosts(raw) -> list[str]:
    """Lowercase and dedupe a host list, dropping empties."""
    seen: set[str] = set()
    result: list[str] = []
    for entry in raw:
        host = str(entry).strip().lower()
        if host and host not in seen:
            seen.add(host)
            result.append(host)
    return result


def trusted_gitlab_hosts() -> list[str]:
    """GitLab hosts `relay pr` may send the token to (always lowercased).

    ``gitlab.com`` is always trusted; any other host (a self-hosted instance)
    must be opted in explicitly via the ``RELAY_TRUSTED_GITLAB_HOSTS`` env var
    (comma/space separated). The allowlist is additive: forgetting to repeat
    ``gitlab.com`` can never break the canonical host. This is the trust
    boundary that stops a malicious ``origin`` remote from redirecting
    GITLAB_TOKEN to an attacker's host. Config-file `trusted_gitlab_hosts` is
    intentionally ignored (env-only) so an untrusted repo-local config cannot
    expand the credential destination.
    """
    extra: list[str] = []
    env_raw = os.environ.get("RELAY_TRUSTED_GITLAB_HOSTS")
    if env_raw is not None and env_raw.strip():
        extra = _split_branch_list(env_raw)
    return _normalize_hosts([*DEFAULT_TRUSTED_GITLAB_HOSTS, *extra])


def _load_hooks() -> dict:
    """Parse the ``[hooks]`` tables from the config file (or {})."""
    data = _load_raw().get("hooks")
    return data if isinstance(data, dict) else {}


def _parse_hook_command(raw) -> list[str] | None:
    """Normalize a hook table into an argv list or None."""
    # Supported shapes:
    #   [hooks.pre_commit] command = ["./scripts/check.sh", "--strict"]
    #   [hooks] pre_commit = ["echo", "hi"]  (direct list, compat)
    if raw is None:
        return None
    if isinstance(raw, list):
        # Direct list form: [hooks] pre_commit = ["echo", "hi"]
        if not raw:
            return None
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, dict):
        cmd = raw.get("command")
        if cmd is None:
            return None
        if isinstance(cmd, list) and cmd:
            return [str(x).strip() for x in cmd if str(x).strip()]
        if isinstance(cmd, str) and cmd.strip():
            # Single-string form splits on whitespace (compat), but argv is still a list
            return [cmd.strip()]
    return None


def hook_pre_commit() -> list[str] | None:
    """Argv for the pre-commit hook, or None when not configured."""
    hooks = _load_hooks()
    # Preferred: [hooks.pre_commit] table
    raw = hooks.get("pre_commit")
    parsed = _parse_hook_command(raw)
    if parsed is not None:
        return parsed
    # Legacy fallback: [hooks] table may have been mis-nested; already covered
    return None


def hook_post_push() -> list[str] | None:
    """Argv for the post-push hook, or None when not configured."""
    hooks = _load_hooks()
    raw = hooks.get("post_push")
    parsed = _parse_hook_command(raw)
    if parsed is not None:
        return parsed
    return None


def _load_repos() -> dict:
    """Parse the ``[repos]`` table from the config file (or {})."""
    data = _load_raw().get("repos")
    return data if isinstance(data, dict) else {}


def repos() -> list[str]:
    """Repo paths for multi-repo runs.

    Resolution order: ``RELAY_REPOS`` env var (comma-separated) > ``[repos]``
    table in config.toml (``paths = [...]`` or ``repos = [...]``) > default
    (empty, meaning the current directory).

    The list is meant for ``relay --repo <path>`` without repeating the flag;
    ``--repo`` on the CLI appends to (and wins over) this list, so a team can
    standardize on a set of worktrees/submodules without touching every
    invocation.
    """
    env_raw = os.environ.get("RELAY_REPOS")
    if env_raw is not None and env_raw.strip():
        return [p.strip() for p in env_raw.split(",") if p.strip()]
    data = _load_repos()
    # Supported keys: `paths` (preferred) or `repos` (compat)
    for key in ("paths", "repos"):
        raw = data.get(key)
        if isinstance(raw, list) and raw:
            return [str(p).strip() for p in raw if str(p).strip()]
    return []


def _load_ignore() -> dict:
    """Parse the ``[relay.ignore]`` table from the config file (or {})."""
    relay_section = _load_raw().get("relay")
    if not isinstance(relay_section, dict):
        return {}
    ignore = relay_section.get("ignore")
    return ignore if isinstance(ignore, dict) else {}


def ignore_paths() -> list[str]:
    """Glob patterns whose diffs are hidden from the AI prompt.

    Resolution order: ``RELAY_IGNORE_PATHS`` env var (comma-separated globs)
    > ``[relay.ignore] paths`` in config.toml
    > the built-in default (no ignores).

    The filter applies only to the LLM prompt; ``git commit`` still commits
    whatever is staged. Env var example: ``RELAY_IGNORE_PATHS="*.lock,dist/*"``.
    """
    env_raw = os.environ.get("RELAY_IGNORE_PATHS")
    if env_raw is not None and env_raw.strip():
        return [p.strip() for p in env_raw.split(",") if p.strip()]
    file_paths = _load_ignore().get("paths")
    if isinstance(file_paths, list) and file_paths:
        return [str(p).strip() for p in file_paths if str(p).strip()]
    return []


def protected_branches() -> list[str]:
    """Branch names the default-branch safety rule refuses to touch.

    Resolution order (mirrors the rest of the config):
    ``RELAY_PROTECTED_BRANCHES`` env var (comma/space separated)
    > ``[team.protected] branches`` in config.toml
    > the built-in default (``main``, ``master``).

    A team-mode run (or a solo push) targeting one of these is refused at
    the ``CONFIRM`` boundary and at push time unless ``--allow-protected``
    opts out explicitly. ``--yes`` skips the confirmation prompt only; it
    never overrides this rule.
    """
    env_raw = os.environ.get("RELAY_PROTECTED_BRANCHES")
    if env_raw is not None and env_raw.strip():
        return _split_branch_list(env_raw)
    file_branches = _load_team_protected().get("branches")
    if isinstance(file_branches, list) and file_branches:
        return [str(b) for b in file_branches]
    return list(DEFAULT_PROTECTED_BRANCHES)
