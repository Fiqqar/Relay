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

from abc import ABC, abstractmethod

from ..config import max_diff_lines
from ..errors import AIError

# Cap on the HTTP body read from any provider. A commit-message response is a
# few hundred bytes; anything near 1 MiB is a misbehaving endpoint, not an
# answer. Rejecting oversized bodies keeps a runaway provider from holding a
# multi-megabyte blob in memory.
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB

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
    was_truncated = False
    if len(lines) > cap:
        lines = lines[:cap]
        lines.append(f"... [{len(diff.splitlines()) - cap} more diff lines truncated]")
        was_truncated = True
        diff = "\n".join(lines)
    # Byte budget: slice the UTF-8 payload if still too large
    encoded = diff.encode("utf-8")
    if len(encoded) > byte_cap:
        # Truncate bytes and decode safely; append notice if not already truncated
        truncated_bytes = encoded[:byte_cap]
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


class AIManager(ABC):
    """Interface every provider implements."""

    provider_name = "base"

    @staticmethod
    def build_prompt(diff: str, stat: str, branch: str, max_lines: int | None = None) -> str:
        """Compose the full prompt: repo context (branch + diffstat) + diff.

        The diff is truncated to a strict line budget before it is sent; the
        ``--stat`` summary is always included in full.
        """
        diff, was_truncated = truncate_diff(diff, max_lines)
        cap = max_lines if max_lines is not None else max_diff_lines()
        notice = f"\nNote: the diff was truncated to its first {cap} lines.\n" if was_truncated else ""
        return (
            f"Current branch: {branch}\n"
            f"Changed files summary:\n{stat}\n"
            f"Staged diff:\n{diff}\n"
            f"---\n{SYSTEM_PROMPT}"
            f"{notice}"
        )

    @abstractmethod
    def generate_commit_message(self, diff: str, stat: str, branch: str) -> str:
        """Return the raw AI text. Raise AIError on any failure."""

    def generate(self, diff: str, stat: str, branch: str) -> str:
        """Public entry point used by the Orchestrator.

        Wraps the concrete implementation so ANY unexpected exception (network
        flake, malformed JSON, provider SDK bug) becomes a typed AIError. This
        is the exact seam the fallback logic in the Orchestrator catches.
        """
        try:
            return self.generate_commit_message(diff, stat, branch)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider internals are opaque
            raise AIError(self.provider_name, "unexpected", str(exc)) from exc
