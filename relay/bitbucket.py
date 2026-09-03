"""BitbucketClient: a tiny, zero-dependency Bitbucket Cloud pull-request client.

Speaks the Bitbucket Cloud 2.0 REST API (``api.bitbucket.org``) using only
``urllib.request`` — no third-party SDK, matching the tool's zero-dependency
philosophy. Auth is HTTP Basic with an App Password: ``BITBUCKET_TOKEN`` holds
``username:app_password`` and is only ever read from the environment.

Mirrors ``github.py`` / ``gitlab.py`` in shape: the same response-size caps,
error normalization, and duplicate-PR detection so ``relay/pr.py`` can route to
it exactly like the other two forges. Only Bitbucket Cloud (``bitbucket.org``)
is supported; self-hosted Bitbucket Server uses a different REST API and is out
of scope.
"""
from __future__ import annotations

import base64
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import RelayError

DEFAULT_TIMEOUT_SECONDS = 30
_USER_AGENT = "relay-cli"
# Error bodies are for diagnostics only — a pathological response must not be
# slurped in full into memory, so reads are capped at 10 KiB.
_MAX_ERROR_BODY_BYTES = 10 * 1024
# Cap on a successful API body. A PR listing is a few KiB at most; anything
# near 1 MiB is a misbehaving endpoint, and holding a giant blob in memory
# is not worth it (mirrors the AI providers' response cap).
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB


class BitbucketError(RelayError):
    """A Bitbucket API call failed. ``status`` is the HTTP status (0 when
    unknown). ``body`` holds the raw response text, ``payload`` the parsed JSON
    body (or None when Bitbucket did not return JSON), and ``detail`` the
    reason Bitbucket reported, without the HTTP wrapper.
    """

    def __init__(
        self,
        message: str,
        status: int = 0,
        body: str = "",
        payload=None,
        detail: str = "",
    ):
        super().__init__(message)
        self.status = status
        self.body = body
        self.payload = payload
        self.detail = detail

    @property
    def reason(self) -> str:
        """The exact reason Bitbucket gave, falling back to the wrapped message."""
        return self.detail or str(self)


class DuplicatePullRequestError(BitbucketError):
    """Bitbucket rejected a POST because an open PR already exists for the
    source branch."""


def bitbucket_token() -> str | None:
    """The Bitbucket app password in ``username:app_password`` form."""
    return os.environ.get("BITBUCKET_TOKEN")


def _parse_json(text: str):
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _extract_reason(payload) -> str:
    """Human-readable reason from a parsed Bitbucket error payload.

    Bitbucket's 2.0 API reports errors in a few shapes: ``error.message`` +
    ``error.detail``, an ``errors`` list, or a top-level ``message``.
    """
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            detail = error.get("detail")
            return f"{message}: {detail}" if detail else message
    errors = payload.get("errors")
    if isinstance(errors, list):
        reasons: list[str] = []
        for entry in errors:
            if not isinstance(entry, dict):
                continue
            message = entry.get("message")
            if isinstance(message, str):
                reasons.append(message)
        if reasons:
            return "; ".join(reasons)
    message = payload.get("message")
    if isinstance(message, str):
        return message
    return ""


def _is_duplicate(body: str) -> bool:
    """True when a 400 body is the "PR already exists" validation error."""
    text = body.lower()
    return "already exists" in text or "existing pull request" in text


class BitbucketClient:
    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        verbose: bool = False,
    ):
        self.owner = owner
        self.repo = repo
        self.token = token if token is not None else bitbucket_token()
        self.verbose = verbose

    @property
    def api_base(self) -> str:
        return "https://api.bitbucket.org/2.0"

    @property
    def pulls_url(self) -> str:
        owner = urllib.parse.quote(self.owner, safe="")
        repo = urllib.parse.quote(self.repo, safe="")
        return f"{self.api_base}/repositories/{owner}/{repo}/pullrequests"

    def _require_token(self) -> str:
        if not self.token:
            raise BitbucketError(
                "BITBUCKET_TOKEN is not set; run `relay doctor` for help"
            )
        return self.token

    def _basic_auth(self, token: str) -> str:
        """HTTP Basic auth from a ``username:app_password`` token.

        Bitbucket Cloud authenticates with an App Password (username + password)
        rather than a Bearer token, so the env value is split on the first
        colon and base64-encoded — the same credential shape the web UI and
        git over HTTPS use.
        """
        username, sep, password = token.partition(":")
        if not sep or not username or not password:
            raise BitbucketError(
                "BITBUCKET_TOKEN must be 'username:app_password' (Bitbucket "
                "Cloud authenticates with an App Password, not a single token)"
            )
        raw = f"{username}:{password}".encode()
        return base64.b64encode(raw).decode("ascii")

    def _request(self, request: urllib.request.Request, *, retries: int = 2):
        if self.verbose:
            print(f"[relay] bitbucket {request.get_method()} {request.full_url}")
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:  # nosec B310
                    body = resp.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise BitbucketError(
                            f"Bitbucket API response exceeded the {MAX_RESPONSE_BYTES}-byte limit"
                        )
                    return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt < retries:
                    time.sleep(1.0 * (attempt + 1) + random.uniform(0.1, 0.5))
                    continue
                body = exc.read(_MAX_ERROR_BODY_BYTES).decode("utf-8", "replace")
                payload = _parse_json(body)
                detail = _extract_reason(payload) or body.strip() or "unknown error"
                raise BitbucketError(
                    f"Bitbucket API error {exc.code}: {detail}",
                    status=exc.code,
                    body=body,
                    payload=payload,
                    detail=detail,
                ) from exc
            except urllib.error.URLError as exc:
                raise BitbucketError(f"cannot reach Bitbucket: {exc.reason}") from exc

    def find_open_pull(self, *, source_branch: str) -> dict | None:
        """Return the first open PR for ``source_branch``, else None.

        Queries ``GET /pullrequests?q=source.branch.name="<branch>" AND
        state="OPEN"`` so callers can detect an existing PR and skip posting a
        duplicate. Raises BitbucketError on a missing/malformed token or a
        failed request, exactly like ``open_pull``.
        """
        token = self._require_token()
        escaped = source_branch.replace("\\", "\\\\").replace('"', '\\"')
        query = urllib.parse.urlencode(
            {"q": f'source.branch.name="{escaped}" AND state="OPEN"'}
        )
        request = urllib.request.Request(
            f"{self.pulls_url}?{query}",
            headers={
                "Authorization": f"Basic {self._basic_auth(token)}",
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        payload = self._request(request)
        values = payload.get("values") if isinstance(payload, dict) else None
        return values[0] if isinstance(values, list) and values else None

    def open_pull(
        self,
        *,
        title: str,
        source_branch: str,
        destination_branch: str = "main",
        description: str = "",
        draft: bool = False,
    ) -> dict:
        """Open a pull request and return the created resource as a dict.

        Bitbucket Cloud does not expose draft PRs through the 2.0 API (drafts
        are a paid-plan feature in the web UI / legacy 1.0 API), so ``draft``
        is accepted for interface symmetry with GitHub/GitLab and ignored.
        Raises DuplicatePullRequestError (a BitbucketError subclass) when
        Bitbucket rejects the POST because an open PR already exists for the
        source branch, so callers can recover gracefully.
        """
        token = self._require_token()
        payload = {
            "title": title,
            "description": description,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": destination_branch}},
        }
        request = urllib.request.Request(
            self.pulls_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Basic {self._basic_auth(token)}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            return self._request(request)
        except BitbucketError as exc:
            if exc.status == 400 and _is_duplicate(exc.body):
                raise DuplicatePullRequestError(
                    exc.reason,
                    status=exc.status,
                    body=exc.body,
                    payload=exc.payload,
                    detail=exc.detail,
                ) from exc
            raise


__all__ = [
    "DuplicatePullRequestError",
    "BitbucketClient",
    "BitbucketError",
    "bitbucket_token",
]
