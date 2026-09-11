"""Repo-local `.relay.toml` loading (extracted from `relay.config`).

Split out with zero behavior change: `relay.config` re-exports every public
name here so existing imports keep working. The strict security allowlist
stays in this module — untrusted clones must never expand secrets, base URLs,
or trusted hosts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:  # Python 3.11+
    import tomllib

    _load_toml = tomllib.load
    _TOML_DECODE_ERROR = tomllib.TOMLDecodeError
except ModuleNotFoundError:  # Python 3.10 — fall back to the bundled parser
    from . import toml

    _load_toml = toml.load
    _TOML_DECODE_ERROR = ValueError

# Parsed repo-local cache: {(path, mtime_ns, size): document}.
_LOCAL_CACHE: dict[tuple[str, int, int], dict] = {}

# Security allowlist for repo-local `.relay.toml`.
_LOCAL_ALLOWED_RELAY_KEYS = {
    "provider",
    "branch_template",
    "max_diff_lines",
    "ai_timeout",
    "pr_open",
    "validate_manual",
    "gemini_model",
    "openai_model",
    "anthropic_model",
    "ollama_model",
    "mistral_model",
    "groq_model",
    "xai_model",
}
_LOCAL_ALLOWED_AI_KEYS = {
    "default",
    "gemini_model",
    "openai_model",
    "anthropic_model",
    "ollama_model",
    "mistral_model",
    "groq_model",
    "xai_model",
}


def find_repo_root(start: Path | None = None) -> Path | None:
    """Traverse parents from ``start`` (or CWD) looking for a ``.git`` directory or file."""
    current = (start or Path.cwd()).resolve()
    for p in [current, *current.parents]:
        if (p / ".git").exists():
            return p
    return None


def local_config_file_path(root: Path | None = None) -> Path | None:
    """Path to the repo-local ``.relay.toml`` if it exists."""
    explicit = os.environ.get("RELAY_LOCAL_CONFIG")
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    r = root or find_repo_root()
    if r is None:
        return None
    candidate = r / ".relay.toml"
    return candidate if candidate.is_file() else None


def _load_local_raw() -> dict:
    """Parse and sanitize repo-local ``.relay.toml`` with a strict security allowlist."""
    path = local_config_file_path()
    if path is None:
        return {}
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = _LOCAL_CACHE.get(key)
        if cached is not None:
            return cached
        with open(path, "rb") as fh:
            data = _load_toml(fh)
    except OSError:
        return {}
    except _TOML_DECODE_ERROR:
        print(
            f"[relay] warning: ignoring malformed repo config {path}; using defaults",
            file=sys.stderr,
        )
        _LOCAL_CACHE[key] = {}
        return {}

    sanitized: dict = {}
    for section_name, section_val in data.items():
        if not isinstance(section_val, dict):
            continue
        if section_name == "relay":
            filtered_relay = {}
            for k, v in section_val.items():
                if k == "ignore" and isinstance(v, dict):
                    paths = v.get("paths")
                    if isinstance(paths, list):
                        filtered_relay["ignore"] = {"paths": paths}
                elif k in _LOCAL_ALLOWED_RELAY_KEYS:
                    filtered_relay[k] = v
                else:
                    print(
                        f"[relay] warning: ignoring security-restricted key {k!r} in repo config",
                        file=sys.stderr,
                    )
            sanitized["relay"] = filtered_relay
        elif section_name == "ai":
            filtered_ai = {}
            for k, v in section_val.items():
                if k in _LOCAL_ALLOWED_AI_KEYS:
                    filtered_ai[k] = v
                else:
                    print(
                        f"[relay] warning: ignoring security-restricted key {k!r} in repo config",
                        file=sys.stderr,
                    )
            sanitized["ai"] = filtered_ai
        elif section_name == "team":
            protected = section_val.get("protected")
            if isinstance(protected, dict) and "branches" in protected:
                branches = protected.get("branches")
                if isinstance(branches, list):
                    sanitized["team"] = {"protected": {"branches": branches}}
        elif section_name == "ignore":
            paths = section_val.get("paths")
            if isinstance(paths, list):
                sanitized["ignore"] = {"paths": paths}
        else:
            print(
                f"[relay] warning: ignoring security-restricted section {section_name!r} in repo config",
                file=sys.stderr,
            )
    _LOCAL_CACHE[key] = sanitized
    return sanitized


def _load_local_config() -> dict:
    section = _load_local_raw().get("relay")
    return section if isinstance(section, dict) else {}


def _load_local_ai() -> dict:
    section = _load_local_raw().get("ai")
    return section if isinstance(section, dict) else {}


def _load_local_team_protected() -> dict:
    team = _load_local_raw().get("team")
    if not isinstance(team, dict):
        return {}
    protected = team.get("protected")
    return protected if isinstance(protected, dict) else {}


def _load_local_ignore() -> dict:
    local_raw = _load_local_raw()
    relay_sec = local_raw.get("relay")
    if isinstance(relay_sec, dict) and isinstance(relay_sec.get("ignore"), dict):
        return relay_sec["ignore"]
    ign_sec = local_raw.get("ignore")
    if isinstance(ign_sec, dict):
        return ign_sec
    return {}


__all__ = [
    "_LOCAL_ALLOWED_AI_KEYS",
    "_LOCAL_ALLOWED_RELAY_KEYS",
    "_LOCAL_CACHE",
    "_load_local_ai",
    "_load_local_config",
    "_load_local_ignore",
    "_load_local_raw",
    "_load_local_team_protected",
    "find_repo_root",
    "local_config_file_path",
]
