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
import urllib.request

from .errors import RelayError

API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 30
_USER_AGENT = "relay-cli"


class GitHubError(RelayError):
    """A GitHub API call failed. ``status`` is the HTTP status (0 when unknown)."""

    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def github_token() -> str | None:
    """The GitHub personal access token from ``GITHUB_TOKEN`` or ``GH_TOKEN``."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


class GitHubClient:
    def __init__(self, owner: str, repo: str, token: str | None = None):
        self.owner = owner
        self.repo = repo
        self.token = token if token is not None else github_token()

    @property
    def pulls_url(self) -> str:
        return f"{API_BASE}/repos/{self.owner}/{self.repo}/pulls"

    def open_pull(
        self,
        *,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
    ) -> dict:
        """Open a pull request and return the created resource as a dict.

        Raises GitHubError when the token is missing, the request fails, or
        GitHub rejects it (422 for a duplicate PR, 404 for a bad repo, etc.).
        """
        if not self.token:
            raise GitHubError(
                "GITHUB_TOKEN (or GH_TOKEN) is not set; run `relay doctor` for help"
            )
        payload = {"title": title, "head": head, "base": base, "body": body}
        request = urllib.request.Request(
            self.pulls_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GitHubError(
                f"GitHub API error {exc.code}",
                status=exc.code,
                body=exc.read().decode("utf-8", "replace"),
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"cannot reach GitHub: {exc.reason}") from exc


__all__ = ["GitHubClient", "GitHubError", "github_token"]
