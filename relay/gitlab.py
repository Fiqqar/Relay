"""GitLabClient: a tiny, zero-dependency GitLab merge-request client.

Mirrors ``github.py`` in shape, reading the token from ``GITLAB_TOKEN`` (or
``CI_JOB_TOKEN``) and POSTing to ``{host}/api/v4/projects/{project}/merge_requests``
using only ``urllib.request`` — no third-party SDK, matching the tool's
zero-dependency philosophy.

Host is derived from the ``origin`` remote (``gitlab.com`` or a self-hosted
GitLab instance). A project is addressed by its URL-encoded ``group/repo`` path,
the form GitLab's REST API accepts for the ``id`` field.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .errors import RelayError

DEFAULT_TIMEOUT_SECONDS = 30
_USER_AGENT = "relay-cli"
# Error bodies are for diagnostics only — a pathological response must not be
# slurped in full into memory, so reads are capped at 10 KiB.
_MAX_ERROR_BODY_BYTES = 10 * 1024


class GitLabError(RelayError):
    """A GitLab API call failed. ``status`` is the HTTP status (0 when unknown)."""

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
        return self.detail or str(self)


class DuplicateMergeRequestError(GitLabError):
    """GitLab rejected a POST because a MR already exists for this source branch."""


def gitlab_token() -> str | None:
    """The GitLab token from ``GITLAB_TOKEN`` (or ``CI_JOB_TOKEN`` in CI)."""
    return os.environ.get("GITLAB_TOKEN") or os.environ.get("CI_JOB_TOKEN")


def _extract_reason(payload) -> str:
    """GitLab wraps errors in ``message`` (a string or a dict keyed by field)."""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return "; ".join(
            f"{field}: {value}"
            for field, value in message.items()
            if isinstance(field, str)
        )
    return ""


def _parse_json(text: str):
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _is_duplicate(body: str) -> bool:
    text = body.lower()
    return "already exists" in text or (
        "existing" in text and "merge request" in text
    )


class GitLabClient:
    def __init__(
        self,
        host: str,
        project: str,
        token: str | None = None,
        verbose: bool = False,
    ):
        self.host = host.rstrip("/")
        # `project` is the "group/repo" path, URL-encoded for the API's id field.
        self.project = urllib.parse.quote(project, safe="")
        self.token = token if token is not None else gitlab_token()
        self.verbose = verbose

    @property
    def api_base(self) -> str:
        return f"https://{self.host}/api/v4"

    @property
    def mrs_url(self) -> str:
        return f"{self.api_base}/projects/{self.project}/merge_requests"

    def _require_token(self) -> str:
        if not self.token:
            raise GitLabError(
                "GITLAB_TOKEN (or CI_JOB_TOKEN) is not set; run `relay doctor` for help"
            )
        return self.token

    def _request(self, request: urllib.request.Request):
        if self.verbose:
            print(f"[relay] gitlab {request.get_method()} {request.full_url}")
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read(_MAX_ERROR_BODY_BYTES).decode("utf-8", "replace")
            payload = _parse_json(body)
            detail = _extract_reason(payload) or body.strip() or "unknown error"
            raise GitLabError(
                f"GitLab API error {exc.code}: {detail}",
                status=exc.code,
                body=body,
                payload=payload,
                detail=detail,
            ) from exc
        except urllib.error.URLError as exc:
            raise GitLabError(f"cannot reach {self.host}: {exc.reason}") from exc

    def find_open_mr(self, *, source_branch: str) -> dict | None:
        """Return the first open MR for ``source_branch``, else None."""
        token = self._require_token()
        query = urllib.parse.urlencode(
            {"source_branch": source_branch, "state": "opened"}
        )
        request = urllib.request.Request(
            f"{self.mrs_url}?{query}",
            headers={
                "PRIVATE-TOKEN": token,
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        mrs = self._request(request)
        return mrs[0] if isinstance(mrs, list) and mrs else None

    def open_merge_request(
        self,
        *,
        title: str,
        source_branch: str,
        target_branch: str = "main",
        description: str = "",
        draft: bool = False,
    ) -> dict:
        """Open a merge request and return the created resource as a dict."""
        token = self._require_token()
        payload: dict[str, str | bool] = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
        }
        if draft:
            payload["draft"] = True
        request = urllib.request.Request(
            self.mrs_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "PRIVATE-TOKEN": token,
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            return self._request(request)
        except GitLabError as exc:
            if exc.status == 409 and _is_duplicate(exc.body):
                raise DuplicateMergeRequestError(
                    exc.reason,
                    status=exc.status,
                    body=exc.body,
                    payload=exc.payload,
                    detail=exc.detail,
                ) from exc
            raise


__all__ = [
    "DuplicateMergeRequestError",
    "GitLabClient",
    "GitLabError",
    "gitlab_token",
]
