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

import ipaddress
import json
import os
import sys
import threading
import urllib.parse
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


def _is_local_or_private_host(host: str) -> bool:
    """True when ``host`` is a loopback/private/link-local address.

    Covers literal IPs (IPv4 + IPv6, including IPv4-mapped IPv6) and the
    well-known ``localhost`` / ``*.localhost`` names, which need no DNS to
    identify. A plain domain name is allowed: resolving it would require a
    DNS lookup, which telemetry must not perform offline.
    """
    host = host.rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an IP literal; treated as a public hostname
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _is_https(url: str) -> bool:
    """True only for a well-formed ``https://`` URL to a public host.

    Any other scheme (``http://``, a bare host, a relative path) is rejected
    before anything is sent, and so is a loopback/private/link-local endpoint:
    telemetry carries only non-secret run metadata, but it must never travel
    over cleartext HTTP or hit a local/private endpoint that a misconfigured
    operator URL could point at.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        return False
    host = parts.hostname
    if host is None:
        return False
    return not _is_local_or_private_host(host)


def _send_payload(payload: dict) -> None:
    """Post the JSON payload once, best-effort; swallow every failure."""
    url = _collect_url()
    if not url or not _is_https(url):
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
    url = _collect_url()
    if not url:
        return
    if not _is_https(url):
        print(
            "[relay] warning: ignoring RELAY_TELEMETRY_URL "
            "(only public https:// endpoints are allowed)",
            file=sys.stderr,
        )
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
