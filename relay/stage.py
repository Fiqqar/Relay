"""relay stage — pick exactly which files (or hunks) to stage, then hand off.

Staging gate of the blocking workflow:
    1. With no arguments, list every unstaged/untracked file.
    2. Let the user select a subset (numbers, ranges, ``all``, or cancel).
    3. Stage exactly that subset with ``git add -- <paths>``.
    4. ``-p`` / ``--patch`` launches git's real ``git add -p`` hunk picker,
       which allows selecting individual hunks, not just whole files.

This covers the "commit the red file, not the scratch notes" case the one-shot
solo flow cannot express. A plain ``relay`` run afterwards commits exactly what
was staged (like ``--staged``).
"""
from __future__ import annotations

from .errors import GitError, sanitize_terminal
from .git_manager import GitManager


def _parse_selection(spec: str, total: int) -> set[int] | None:
    """Parse a selection spec into 1-based indexes (None when canceled).

    Supported syntax:
        'all'              -> every file
        '2' / '1,3,5'      -> individual
        '2-4'              -> a range (inclusive)
        ''  or 'none'      -> None (user canceled; stage nothing)
    """
    spec = spec.strip().lower()
    if not spec or spec == "none":
        return None
    if spec == "all":
        return set(range(1, total + 1))

    picked: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk and chunk.count("-") == 1:
            lo_s, _, hi_s = chunk.partition("-")
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError as exc:
                raise GitError(
                    f"invalid range: {chunk} (use 'all' or forms like 2-4, 1,3,5)"
                ) from exc
            if lo < 1 or hi > total or lo > hi:
                raise GitError(
                    f"range {chunk} out of 1..{total}; use numbers between 1 and {total}"
                )
            picked.update(range(lo, hi + 1))
            continue
        try:
            n = int(chunk)
        except ValueError as exc:
            raise GitError(
                f"invalid selection: {chunk} (use numbers, 'all', or 'none')"
            ) from exc
        if not 1 <= n <= total:
            raise GitError(
                f"{n} out of range (1..{total}); pick a number in that range"
            )
        picked.add(n)
    if not picked:
        raise GitError("no files selected; pick at least one file (or 'all')")
    return picked


def _input(prompt: str) -> str:
    import builtins

    return builtins.input(prompt)


def run_stage(
    *,
    git: GitManager | None = None,
    patch: bool = False,
    verbose: bool = False,
) -> int:
    """Interactively stage a subset (or hunks) of the working tree."""
    git = git or GitManager(verbose=verbose)
    if not git.is_repo():
        raise GitError("not a git repository - run Relay from inside a work tree")

    if patch:
        return git.add_interactive()

    files = git.unstaged_changes()
    if not files:
        print("[relay] nothing to stage; working tree has no unstaged changes.")
        return 0

    print("[relay] unstaged / untracked files:")
    for i, name in enumerate(files, start=1):
        print(f"    {i:>3}. {sanitize_terminal(name)}")

    selection = _input("Select files to stage (e.g. '1,2', '3-5', 'all', 'none'): ")
    picked = _parse_selection(selection, len(files))
    if picked is None:
        print("[relay] stage canceled - nothing changed.")
        return 0
    paths = [files[i - 1] for i in picked]
    git.stage_files(*paths)
    safe = ", ".join(sanitize_terminal(p) for p in paths)
    print(f"[relay] staged {len(paths)} file(s): {safe}")
    return 0


__all__ = ["run_stage"]
