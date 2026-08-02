"""Commit-message helpers: Conventional Commit validation, sanitization, and
team-mode branch-name building.

The AI can return junk (markdown fences, quotes, multi-line rants), so every
message the AI produces must pass through this module before it is committed.
"""
from __future__ import annotations

import re

CONVENTIONAL_TYPES = {
    "feat", "fix", "refactor", "docs", "style",
    "test", "chore", "perf", "build", "ci", "revert",
}

# Matches:  type(scope): subject  |  type(scope)!: subject  |  type: subject
_CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)"               # commit type
    r"(\((?P<scope>[^)]+)\))?"            # optional (scope)
    r"(?P<breaking>!)?"                   # optional breaking-change bang
    r":\s+(?P<subject>[^\s].*?[^\s])$"    # subject (no leading/trailing ws)
)


def sanitize_ai_message(raw: str) -> str:
    """Clean raw LLM output down to a single candidate line.

    Handles the two ways models commonly disobey the "one line" rule:
    wrapping the answer in a ```code fence``` and adding preamble/blank lines.
    """
    text = raw.strip()
    # Strip a markdown code fence if the model wrapped its answer in one.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Keep only the first non-empty line.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else ""


def validate_conventional(message: str):
    """Validate the subject line against the Conventional Commits grammar.

    Returns (is_valid, reason). The optional body of a manual message is left
    untouched — only the first line must obey the format.
    """
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    match = _CONVENTIONAL_RE.match(first_line)
    if not match:
        return False, "expected format: type(scope): subject"
    if match.group("type").lower() not in CONVENTIONAL_TYPES:
        return False, f"unknown type '{match.group('type')}'"
    return True, ""


def build_branch_name(template: str, feature: str) -> str:
    """Expand a template like ``status/<feature>`` into a valid git ref name.

    Sanitizes the feature so it can never produce an illegal ref: lowercase,
    whitespace -> '-', strip dangerous chars, drop '.' / '..' path segments,
    cap length. The result is still run through `git checkout -b`, which is
    git's final authority.
    """
    slug = feature.strip().lower()
    # Anything that is not word/period/underscore/slash/dash becomes a dash.
    slug = re.sub(r"[^a-z0-9._/-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)  # collapse runs of dashes
    # Drop empty segments and the forbidden "." / ".." path segments.
    parts = [p for p in slug.split("/") if p and p not in (".", "..")]
    slug = "/".join(parts).strip(".-")[:100]
    if not slug:
        raise ValueError("feature name is empty after sanitization")
    return template.replace("<feature>", slug)
