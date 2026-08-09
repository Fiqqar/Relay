"""Opt-in usage telemetry for Relay. Off by default; never sends a thing unless
the user explicitly enables it AND configures a collection endpoint.

Privacy contract (matches the zero-config, zero-phone-home philosophy):
    * Opt-in, default off. Nothing leaves the machine until the user runs
      ``relay telemetry on`` (or sets ``RELAY_TELEMETRY=1``).
    * No diffs, no commit messages, no file names — only ``mode``/``provider``
      and a boolean outcome, plus the relay version.
    * The collection URL must be supplied by the operator via
      ``RELAY_TELEMETRY_URL``; with no URL set, ``report()`` is a no-op even
      when telemetry is enabled. A consent marker without an endpoint is
      harmless by construction.
    * ``report()`` never raises: it is fire-and-forget in a background thread
      with a short timeout and catches every exception, so an unreachable
      endpoint can never slow down or break the workflow.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path

from . import __version__

# Truthy values accepted for RELAY_TELEMETRY (and the opt-in marker file).
_TRUTHY = {"1", "true", "yes", "on", "enabled"}


def _state_file() -> Path | None:
    """Persisted opt-in decision, next to the config directory.

    Lookup mirrors config.config_file_path(): $XDG_CONFIG_HOME/relay/telemetry
    on POSIX, $APPDATA\\relay\\telemetry on Windows, else ~/.config/relay/telemetry.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "relay" / "telemetry"
    return Path.home() / ".config" / "relay" / "telemetry"


def is_enabled() -> bool:
    """True only when the user opted in (env var or the marker file)."""
    env = os.environ.get("RELAY_TELEMETRY")
    if env is not None:
        return env.strip().lower() in _TRUTHY
    state = _state_file()
    if state and state.is_file():
        return state.read_text(encoding="utf-8").strip().lower() in _TRUTHY
    return False


def set_enabled(enabled: bool) -> Path:
    """Persist the opt-in decision to the marker file. Returns the written path."""
    state = _state_file() or Path.home() / ".config" / "relay" / "telemetry"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("1\n" if enabled else "0\n", encoding="utf-8")
    return state


def _collect_url() -> str:
    return os.environ.get("RELAY_TELEMETRY_URL", "").strip()


def _send_payload(payload: dict) -> None:
    """Post the JSON payload once, best-effort; swallow every failure."""
    url = _collect_url()
    if not url:
        return
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3):
            pass
    except Exception:  # noqa: BLE001 - telemetry must never interfere
        pass


def report(*, mode: str, provider: str, ok: bool) -> None:
    """Record a single workflow run. Safe to call anywhere; never raises."""
    if not is_enabled():
        return
    if not _collect_url():
        return
    payload = {
        "event": "relay_run",
        "version": __version__,
        "mode": mode,
        "provider": provider,
        "ok": bool(ok),
    }
    # Fire-and-forget on a background thread so a slow endpoint can never
    # block the terminal workflow.
    threading.Thread(target=_send_payload, args=(payload,), daemon=True).start()


__all__ = ["is_enabled", "report", "set_enabled"]