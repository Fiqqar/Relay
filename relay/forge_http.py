"""Shared HTTP transport for the forge clients (GitHub/GitLab/Bitbucket).

All three forges run the same request shape over ``urllib.request``: capped
reads, transient (429/5xx) retry with backoff+jitter, and normalized errors.
The per-forge differences — error class, reason extraction, display names —
arrive as parameters so ``github.py`` / ``gitlab.py`` / ``bitbucket.py`` stay
thin wrappers around :func:`request_json`.

Pure stdlib only, matching the zero-dependency philosophy of the rest of
the tool.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .errors import RelayError

DEFAULT_TIMEOUT_SECONDS = 30
# Error bodies are for diagnostics only — a pathological response must not be
# slurped in full into memory, so reads are capped at 10 KiB.
_MAX_ERROR_BODY_BYTES = 10 * 1024
# Cap on a successful API body. A PR/MR listing is a few KiB at most;
# anything near 1 MiB is a misbehaving endpoint, and holding a giant blob
# in memory is not worth it (mirrors the AI providers' response cap).
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB
# Transient failures worth retrying: rate limits and bad-gateway-class 5xx.
TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})


def parse_json_body(text: str):
    """Best-effort JSON decode of a response body (None when it is not JSON)."""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def join_error_messages(errors, *, bare_strings: bool = False) -> str:
    """Collect human-readable messages from an ``errors`` list payload.

    Entries are dicts carrying a string ``message``; when ``bare_strings``
    is set (GitHub's shape), bare non-empty strings count too. Anything
    else is skipped so a malformed entry can never crash error reporting.
    Returns the messages joined with "; " ("" when nothing usable).
    """
    if not isinstance(errors, list):
        return ""
    reasons = []
    for entry in errors:
        if isinstance(entry, dict):
            message = entry.get("message")
            if isinstance(message, str) and message:
                reasons.append(message)
        elif bare_strings and isinstance(entry, str) and entry:
            reasons.append(entry)
    return "; ".join(reasons)


def request_json(
    request: urllib.request.Request,
    *,
    forge: str,
    tag: str,
    error_cls: Callable[..., RelayError],
    extract_reason: Callable[[Any], str],
    unreachable: str,
    verbose: bool = False,
    retries: int = 2,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    max_error_body_bytes: int = _MAX_ERROR_BODY_BYTES,
):
    """Run one forge request, decoding JSON and normalizing failures.

    ``forge`` is the display name used in messages (``"GitHub"``), ``tag``
    the lowercase verbose-log tag (``"github"``), ``error_cls`` the
    forge-specific error, ``extract_reason`` its payload-shape reader, and
    ``unreachable`` the connection-failure prefix (``"cannot reach GitHub"``).
    """
    for attempt in range(retries + 1):
        if verbose:
            print(f"[relay] {tag} {request.get_method()} {request.full_url}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:  # nosec B310
                body = resp.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise error_cls(
                        f"{forge} API response exceeded the {max_response_bytes}-byte limit"
                    )
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in TRANSIENT_STATUSES and attempt < retries:
                time.sleep(1.0 * (attempt + 1) + random.uniform(0.1, 0.5))
                continue
            body = exc.read(max_error_body_bytes).decode("utf-8", "replace")
            payload = parse_json_body(body)
            detail = extract_reason(payload) or body.strip() or "unknown error"
            raise error_cls(
                f"{forge} API error {exc.code}: {detail}",
                status=exc.code,
                body=body,
                payload=payload,
                detail=detail,
            ) from exc
        except urllib.error.URLError as exc:
            raise error_cls(f"{unreachable}: {exc.reason}") from exc
