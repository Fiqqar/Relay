"""Interactive confirmation menu for AI-generated commit messages.

The Accept/Edit/Retry/Abort key mapping lives here so it can be unit-tested in
isolation. Case-sensitivity is deliberate: the raw input is matched BEFORE any
lowercasing, so ``a`` (Accept) and ``A`` (Abort) can never collide. Pressing
Enter aborts — matching the capitalized ``A`` that marks Abort as the default
choice — because a bare ``choice.lower()`` would turn Shift+A into Accept and
accidentally commit & push.
"""
from __future__ import annotations

CONFIRM_PROMPT = "[Accept] [Edit] [Retry] [Abort] (a/e/r/A): "

# Actions returned by interpret_choice().
ACCEPT = "accept"
EDIT = "edit"
RETRY = "retry"
ABORT = "abort"


def interpret_choice(raw: str) -> str:
    """Map a raw menu response to ``accept | edit | retry | abort``.

    * ``a``, ``y``, ``accept``, ``yes`` -> accept
    * ``e``, ``edit``                -> edit
    * ``r``, ``retry``               -> retry
    * ``A``, ``q``, ``c``, ``abort``, ``cancel``, Enter, or anything else -> abort

    Single letters are matched against the raw input (no lowercasing), so ``a``
    accepts while ``A`` aborts. Full words are matched case-insensitively for
    convenience. Unrecognized input aborts rather than committing by accident.
    """
    choice = raw.strip()
    if not choice:
        return ABORT
    if choice == "a" or choice.lower() in ("accept", "y", "yes"):
        return ACCEPT
    if choice == "A" or choice.lower() in ("abort", "cancel", "q", "c"):
        return ABORT
    if choice.lower() in ("edit", "e"):
        return EDIT
    if choice.lower() in ("retry", "r"):
        return RETRY
    return ABORT


__all__ = ["ABORT", "ACCEPT", "CONFIRM_PROMPT", "EDIT", "RETRY", "interpret_choice"]
