"""GitHubClient: a tiny, zero-dependency GitHub pull-request client.

Reads the personal access token from ``GITHUB_TOKEN`` or ``GH_TOKEN``, builds
the PR payload, and POSTs it to ``https://api.github.com/repos/{owner}/{repo}/pulls``
using only ``urllib.request`` — no third-party SDK, matching the tool's
zero-dependency philosophy (works offline-of-GitHub and behind any proxy that
the stdlib honors).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .errors import RelayError

API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 30
_USER_AGENT = "relay-cli"
# Error bodies are for diagnostics only — a pathological response must not be
# slurped in full into memory, so reads are capped at 10 KiB.
_MAX_ERROR_BODY_BYTES = 10 * 1024
# Cap on a successful API body. A PR listing is a few KiB at most; anything
# near 1 MiB is a misbehaving endpoint, and holding a giant blob in memory
# is not worth it (mirrors the AI providers' response cap).
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB


class GitHubError(RelayError):
    """A GitHub API call failed. ``status`` is the HTTP status (0 when unknown).

    ``body`` holds the raw response text, ``payload`` the parsed JSON body (or
    None when GitHub did not return JSON), and ``detail`` the exact reason
    GitHub reported (its ``message`` plus any ``errors``), without the HTTP
    wrapper.
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
        """The exact reason GitHub gave, falling back to the wrapped message."""
        return self.detail or str(self)


class DuplicatePullRequestError(GitHubError):
    """GitHub rejected a POST because an open PR already exists for this head."""


def _parse_json(text: str):
    """Best-effort JSON decode of a response body (None when it is not JSON)."""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _extract_reason(payload) -> str:
    """Human-readable reason from a parsed GitHub error payload.

    Mirrors GitHub's JSON error shape: a top-level ``message`` plus an optional
    ``errors`` list whose entries each carry their own ``message``.
    """
    if not isinstance(payload, dict):
        return ""
    detail = payload.get("message") or ""
    errors = payload.get("errors")
    if errors:
        reasons = []
        for err in errors:
            if isinstance(err, dict) and err.get("message"):
                reasons.append(err["message"])
            elif isinstance(err, str) and err:
                reasons.append(err)
        if reasons:
            joined = "; ".join(reasons)
            detail = f"{detail} ({joined})" if detail else joined
    return detail


def _is_duplicate_error(body: str) -> bool:
    """True when a 422 body is the "PR already exists" validation error."""
    return "already exists" in body.lower()


def github_token() -> str | None:
    """The GitHub personal access token from ``GITHUB_TOKEN`` or ``GH_TOKEN``."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


class GitHubClient:
    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        verbose: bool = False,
    ):
        self.owner = owner
        self.repo = repo
        self.token = token if token is not None else github_token()
        self.verbose = verbose

    @property
    def pulls_url(self) -> str:
        return f"{API_BASE}/repos/{self.owner}/{self.repo}/pulls"

    def _require_token(self) -> str:
        if not self.token:
            raise GitHubError(
                "GITHUB_TOKEN (or GH_TOKEN) is not set; run `relay doctor` for help"
            )
        return self.token

    def _request(self, request: urllib.request.Request):
        """Run a request, decoding JSON and normalizing failures to GitHubError."""
        if self.verbose:
            print(f"[relay] github {request.get_method()} {request.full_url}")
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
                body = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise GitHubError(
                        f"GitHub API response exceeded the {MAX_RESPONSE_BYTES}-byte limit"
                    )
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read(_MAX_ERROR_BODY_BYTES).decode("utf-8", "replace")
            payload = _parse_json(body)
            detail = _extract_reason(payload) or body.strip() or "unknown error"
            raise GitHubError(
                f"GitHub API error {exc.code}: {detail}",
                status=exc.code,
                body=body,
                payload=payload,
                detail=detail,
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"cannot reach GitHub: {exc.reason}") from exc

    def find_open_pr(self, *, head: str, owner: str | None = None) -> dict | None:
        """Return the first open PR for ``head`` (``owner:branch``), else None.

        Queries ``GET /pulls?head={owner}:{head}&state=open`` so callers can
        detect an existing PR and skip posting a duplicate. The ``head`` filter
        uses GitHub's ``{owner}:{branch}`` format; both parts are stripped of
        whitespace before building the query. Raises GitHubError on a missing
        token or a failed request, exactly like ``open_pull``.
        """
        token = self._require_token()
        head = head.strip()
        owner = (owner or self.owner).strip()
        query = urllib.parse.urlencode({"head": f"{owner}:{head}", "state": "open"})
        request = urllib.request.Request(
            f"{self.pulls_url}?{query}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        prs = self._request(request)
        return prs[0] if isinstance(prs, list) and prs else None

    def open_pull(
        self,
        *,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
        draft: bool = False,
    ) -> dict:
        """Open a pull request and return the created resource as a dict.

        ``draft=True`` creates a draft pull request (visible to the repository
        but not ready for review). Raises GitHubError when the token is missing
        or the request fails. Raises DuplicatePullRequestError (a GitHubError
        subclass) when GitHub rejects the POST with a 422 "PR already exists"
        error, so callers can recover gracefully instead of crashing on the
        duplicate.
        """
        token = self._require_token()
        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": draft,
        }
        request = urllib.request.Request(
            self.pulls_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            return self._request(request)
        except GitHubError as exc:
            if exc.status == 422 and _is_duplicate_error(exc.body):
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
    "GitHubClient",
    "GitHubError",
    "github_token",
]
