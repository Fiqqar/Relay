"""AIManager: the provider-agnostic AI interface.

To add a new provider later (e.g. another hosted model):
    1. Subclass AIManager in this package.
    2. Implement ``provider_name`` and ``generate_commit_message()``.
    3. Register it in the ``_PROVIDERS`` dict in ``__init__.py``.

The Orchestrator only ever sees the ``AIManager`` interface and never knows
which provider is behind it — which is exactly what makes the fallback logic
provider-independent.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import urllib.error
from abc import ABC, abstractmethod
from pathlib import PurePath

from ..config import max_diff_lines
from ..errors import AIError

# Cap on the HTTP body read from any provider. A commit-message response is a
# few hundred bytes; anything near 1 MiB is a misbehaving endpoint, not an
# answer. Rejecting oversized bodies keeps a runaway provider from holding a
# multi-megabyte blob in memory.
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB

# Diagnostic error payload read cap
MAX_ERROR_BODY_BYTES = 10 * 1024  # 10 KiB


def extract_http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Extract a human-readable diagnostic error message from an HTTPError.

    Reads up to 10 KiB from the error body and attempts to parse JSON error payloads
    returned by AI gateways (OpenAI, Gemini, Anthropic, Ollama), falling back to
    exc.reason if no message is extractable.
    """
    try:
        raw = exc.read(MAX_ERROR_BODY_BYTES + 1)
        if not raw:
            return exc.reason or ""
        text = raw[:MAX_ERROR_BODY_BYTES].decode("utf-8", "replace")
        try:
            payload = json.loads(text)
        except Exception:
            return text.strip() or exc.reason or ""

        if isinstance(payload, dict):
            # 1. Standard OpenAI / Anthropic format: {"error": {"message": "..."}}
            err = payload.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if msg and isinstance(msg, str):
                    return msg.strip()
            elif isinstance(err, str) and err.strip():
                return err.strip()
            # 2. Gemini format: {"error": {"message": "...", "status": "..."}} or {"message": "..."}
            msg = payload.get("message")
            if msg and isinstance(msg, str):
                return msg.strip()
            # 3. Ollama format: {"detail": "..."}
            detail = payload.get("detail")
            if detail and isinstance(detail, str):
                return detail.strip()
        return text.strip() or exc.reason or ""
    except Exception:
        return exc.reason or ""

# Byte budget for the diff sent to the LLM. Even if line-count is within cap,
# a single line (e.g. minified file) could be huge.
MAX_DIFF_BYTES = 512 * 1024  # 512 KiB


def read_limited_response(response, provider: str) -> bytes:
    """Read the HTTP body, rejecting anything larger than ``MAX_RESPONSE_BYTES``.

    Reads ``MAX_RESPONSE_BYTES + 1`` so the length check detects oversize
    without forcing urllib to swallow the whole stream. Raises AIError
    (``bad_response``) so the Orchestrator's fallback treats a giant payload
    exactly like any other unusable answer.
    """
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise AIError(
            provider,
            "bad_response",
            f"response exceeded the {MAX_RESPONSE_BYTES}-byte limit",
        )
    return body

# The single source of truth for how the AI must write commit messages.
# It lives here (not inside a provider) so every provider produces the same
# shape of output, which the validator in relay/commit.py can then check.
SYSTEM_PROMPT = (
    "You are a Git commit message generator.\n"
    "Given a staged diff, write EXACTLY ONE LINE in the Conventional Commits format:\n"
    "    type(scope): subject\n"
    "Rules:\n"
    "    - type must be one of: feat, fix, refactor, docs, style, test, chore, perf, build, ci, revert\n"
    "    - scope is optional and lowercase, e.g. type(auth): subject\n"
    "    - subject is imperative mood, concise, at most 72 characters, no trailing period\n"
    "    - output ONLY the single commit-message line.\n"
    "    - no markdown, no code fences, no quotes, no explanation.\n"
)


def _path_matches(path: str, patterns: list[str]) -> bool:
    """True if ``path`` matches any glob in ``patterns`` (fnmatch + PurePath)."""
    for pat in patterns:
        pat = pat.strip()
        if not pat:
            continue
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(os.path.basename(path), pat):
            return True
        try:
            if PurePath(path).match(pat):
                return True
        except Exception:
            pass
    return False


_DIFF_HEADER_RE = re.compile(r"(?m)^diff --git ")


def filter_ignored_diff(diff: str, patterns: list[str]) -> str:
    """Remove file blocks whose path matches an ignore glob.

    The filter applies only to the AI prompt; git still commits everything.
    """
    if not patterns or not diff.strip():
        return diff
    if not _DIFF_HEADER_RE.search(diff):
        return diff
    # Split on the git diff header anchored to start of line; each block after
    # the first delimiter is one file.
    parts = _DIFF_HEADER_RE.split(diff)
    kept: list[str] = []
    # parts[0] is content before first header (usually empty)
    if parts[0].strip():
        kept.append(parts[0])
    for part in parts[1:]:
        first_line = part.splitlines()[0] if part else ""
        path = ""
        if " b/" in first_line:
            path = first_line.split(" b/", 1)[1].strip()
        elif first_line.startswith("a/"):
            # Fallback for unusual header without b/ separator
            path = first_line[2:].split()[0] if len(first_line) > 2 else ""
        # Strip quotes that git may add for unusual paths
        path = path.strip().strip('"')
        if path and _path_matches(path, patterns):
            continue
        kept.append("diff --git " + part)
    # Re-assemble kept diff blocks
    return "".join(kept)


def filter_ignored_stat(stat: str, patterns: list[str]) -> str:
    """Remove stat lines whose file path matches an ignore glob."""
    if not patterns or not stat.strip():
        return stat
    kept: list[str] = []
    for line in stat.splitlines():
        if not line.strip():
            continue
        # stat format: " path | 1 +-" or " path | Bin ..."
        if "|" in line:
            path = line.split("|", 1)[0].strip()
        else:
            path = line.strip().split()[0] if line.strip() else ""
        path = path.strip().strip('"')
        if path and _path_matches(path, patterns):
            continue
        kept.append(line)
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    """Split a ``git diff`` into per-file blocks.

    Returns ``[(path, block), ...]`` where ``block`` is the full
    ``diff --git`` section for that file (including its header). The path is
    the ``b/`` side of the header, or ``""`` when it cannot be parsed.
    """
    if not diff.strip():
        return []
    if not _DIFF_HEADER_RE.search(diff):
        return [("", diff)]
    parts = _DIFF_HEADER_RE.split(diff)
    blocks: list[tuple[str, str]] = []
    for part in parts[1:]:
        block = "diff --git " + part
        first_line = part.splitlines()[0] if part else ""
        path = ""
        if " b/" in first_line:
            path = first_line.split(" b/", 1)[1].strip().strip('"')
        elif first_line.startswith("a/"):
            path = first_line[2:].split()[0].strip().strip('"') if len(first_line) > 2 else ""
        blocks.append((path, block))
    return blocks



def truncate_diff(diff: str, max_lines: int | None = None, max_bytes: int | None = None):
    """Cap a staged diff to ``max_lines`` lines and ``max_bytes`` bytes.

    Large diffs are the single biggest latency driver for LLM commit messages.
    We keep the first ``max_lines`` lines (the most representative hunk) and
    append a one-line notice; the concise ``--stat`` summary is passed to the
    provider separately and is never truncated. A byte cap prevents a single
    huge line from blowing the token budget.

    Returns ``(truncated_diff, was_truncated)``.
    """
    cap = max_lines if max_lines is not None else max_diff_lines()
    byte_cap = max_bytes if max_bytes is not None else MAX_DIFF_BYTES
    lines = diff.splitlines()
    orig_len = len(lines)
    was_truncated = False
    if orig_len > cap:
        lines = lines[:cap]
        lines.append(f"... [{orig_len - cap} more diff lines truncated]")
        was_truncated = True
        diff = "\n".join(lines)
    # Fast path: ascii diff smaller than byte cap needs no encode
    if not was_truncated and len(diff) <= byte_cap and diff.isascii():
        return diff, False
    # Byte budget: slice the UTF-8 payload if still too large
    encoded = diff.encode("utf-8")
    if len(encoded) > byte_cap:
        # Truncate bytes and decode safely; trim trailing incomplete multi-byte sequence
        truncated_bytes = encoded[:byte_cap]
        for i in range(min(4, len(truncated_bytes)) + 1):
            chunk = truncated_bytes[: len(truncated_bytes) - i] if i > 0 else truncated_bytes
            try:
                diff = chunk.decode("utf-8")
                break
            except UnicodeDecodeError:
                continue
        else:
            diff = truncated_bytes.decode("utf-8", errors="ignore")
        # Ensure we don't cut in the middle of the truncation notice
        if not was_truncated:
            diff += f"\n... [diff truncated to {byte_cap} bytes]"
        was_truncated = True
    elif was_truncated:
        # diff already rebuilt from lines
        pass
    else:
        # no line truncation and no byte overflow
        return diff, False
    return diff, was_truncated


# Cap on the `--stat` summary lines sent to the LLM. Per-file one-liners
# carry near-zero commit-message signal past the first screenful, while an
# accidentally un-ignored mass-add (e.g. `node_modules`) can produce
# megabytes of stat. Unlike the diff body, stat lines are short, so a line
# cap alone suffices (no byte budget needed).
MAX_STAT_LINES = 50


def truncate_stat(stat: str, max_lines: int = MAX_STAT_LINES) -> str:
    """Cap a ``--stat`` summary to ``max_lines`` lines plus an ellipsis marker.

    Mirrors :func:`truncate_diff` for the summary block, so one shared call
    site (``AIManager.build_prompt``) covers all providers.
    """
    lines = stat.splitlines()
    if len(lines) <= max_lines:
        return stat
    kept = lines[:max_lines]
    kept.append(f"... [{len(lines) - max_lines} more stat lines truncated]")
    return "\n".join(kept) + "\n"


class AIManager(ABC):
    """Interface every provider implements."""

    provider_name = "base"

    @staticmethod
    def build_prompt(
        diff: str,
        stat: str,
        branch: str,
        max_lines: int | None = None,
        recent_commits: list[str] | None = None,
        rejected_message: str | None = None,
    ) -> str:
        """Compose the full prompt: repo context (branch + diffstat) + diff.

        The diff is truncated to a strict line budget before it is sent; the
        ``--stat`` summary is capped to ``MAX_STAT_LINES`` lines (per-file
        one-liners carry no signal past the first screenful).
        """
        diff, was_truncated = truncate_diff(diff, max_lines)
        stat = truncate_stat(stat)
        cap = max_lines if max_lines is not None else max_diff_lines()
        notice = f"\nNote: the diff was truncated to its first {cap} lines.\n" if was_truncated else ""
        recent_section = ""
        if recent_commits:
            items = "\n".join(f"- {c}" for c in recent_commits[:5] if c.strip())
            if items:
                recent_section = (
                    f"Recent commit subjects in this repository (for scope and style reference):\n"
                    f"{items}\n"
                )
        retry_section = ""
        if rejected_message:
            retry_section = (
                f"The previously suggested commit message was rejected:\n"
                f'"{rejected_message.strip()}"\n'
                f"Please generate an ALTERNATIVE Conventional Commit message with a different perspective, scope, or phrasing.\n"
            )
        return (
            f"Current branch: {branch}\n"
            f"Changed files summary:\n{stat}\n"
            f"{recent_section}"
            f"{retry_section}"
            f"Staged diff:\n{diff}\n"
            f"---\n{SYSTEM_PROMPT}"
            f"{notice}"
        )

    @abstractmethod
    def generate_commit_message(
        self,
        diff: str,
        stat: str,
        branch: str,
        recent_commits: list[str] | None = None,
        rejected_message: str | None = None,
    ) -> str:
        """Return the raw AI text. Raise AIError on any failure."""

    def generate(
        self,
        diff: str,
        stat: str,
        branch: str,
        recent_commits: list[str] | None = None,
        rejected_message: str | None = None,
    ) -> str:
        """Public entry point used by the Orchestrator.

        Wraps the concrete implementation so ANY unexpected exception (network
        flake, malformed JSON, provider SDK bug) becomes a typed AIError. This
        is the exact seam the fallback logic in the Orchestrator catches.
        A present-but-null (or otherwise non-string) message field is also
        normalized here: without this, a bare `None` would reach
        `sanitize_ai_message()` and crash on `.strip()` instead of falling
        back to manual input.
        """
        try:
            result = self.generate_commit_message(
                diff,
                stat,
                branch,
                recent_commits=recent_commits,
                rejected_message=rejected_message,
            )
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider internals are opaque
            raise AIError(self.provider_name, "unexpected", str(exc)) from exc
        if not isinstance(result, str) or not result.strip():
            raise AIError(
                self.provider_name, "bad_response", "empty response from provider"
            )
        return result
