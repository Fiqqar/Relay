"""Default-branch safety: the guard that refuses to let a commit land on a
protected branch.

Solo mode keeps its convention of committing to the current branch (whatever
it is), so this guard is deliberately team-only. The boundaries it polices are
the two places a Relay run could touch a protected branch:

* ``team`` mode resolves a branch name (``<type>/<feature>``); if that name
  collides with a configured protected branch (e.g. a bare ``<feature>``
  template, or a feature literally named ``main``), the run is refused unless
  the developer opts out.
* ``amend`` rewrites history in place and never pushes; it is left alone.

Every refusal is explicit and actionable: the rule, the reason, and the exact
escape hatch (``--allow-protected``) are printed before anything is staged or
committed. ``--yes`` only skips the confirmation prompt — it deliberately does
not bypass this guard, so a scripted/CI run cannot silently land on a
protected branch.
"""
from __future__ import annotations

from .errors import ProtectedBranchError


def is_protected(branch: str, protected_branches: list[str]) -> bool:
    """True when ``branch`` matches a configured protected branch name.

    The match is case-insensitive so ``MAIN`` cannot bypass a rule written for
    ``main`` (M-14).
    """
    lowered = branch.lower()
    return any(item.lower() == lowered for item in protected_branches)


def assert_branch_allowed(
    branch: str,
    protected_branches: list[str],
    *,
    force: bool = False,
) -> None:
    """Raise ProtectedBranchError when ``branch`` is protected and ``force`` is off.

    ``force`` is the escape hatch wired from ``--allow-protected`` only: an
    explicit, deliberate opt-out for someone who really means to work on a
    protected branch.
    """
    if force:
        return
    if is_protected(branch, protected_branches):
        raise ProtectedBranchError(
            f"'{branch}' is a protected branch; refusing to commit to it by default. "
            f"Re-run with --allow-protected to override."
        )


__all__ = ["assert_branch_allowed", "is_protected"]
