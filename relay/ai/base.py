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

from ..errors import AIError

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


class AIManager(ABC):
    """Interface every provider implements."""

    provider_name = "base"

    @staticmethod
    def build_prompt(diff: str, stat: str, branch: str) -> str:
        """Compose the full prompt: repo context (branch + diffstat) + diff."""
        return (
            f"Current branch: {branch}\n"
            f"Changed files summary:\n{stat}\n"
            f"Full staged diff:\n{diff}\n"
            f"---\n{SYSTEM_PROMPT}"
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
