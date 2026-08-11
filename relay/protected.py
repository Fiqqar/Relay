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
escape hatch (``--allow-protected`` / ``--yes``) are printed before anything
is staged or committed.
"""
from __future__ import annotations

from .errors import ProtectedBranchError


def is_protected(branch: str, protected_branches: list[str]) -> bool:
    """True when ``branch`` is in the configured protected set."""
    return branch in protected_branches


def assert_branch_allowed(
    branch: str,
    protected_branches: list[str],
    *,
    force: bool = False,
) -> None:
    """Raise ProtectedBranchError when ``branch`` is protected and ``force`` is off.

    ``force`` is the escape hatch wired from ``--allow-protected`` / ``--yes``:
    an explicit, deliberate opt-out for someone who really means to work on a
    protected branch.
    """
    if force:
        return
    if is_protected(branch, protected_branches):
        raise ProtectedBranchError(
            f"'{branch}' is a protected branch; refusing to commit to it by default. "
            f"Re-run with --allow-protected (or --yes) to override."
        )


__all__ = ["assert_branch_allowed", "is_protected"]