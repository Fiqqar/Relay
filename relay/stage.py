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

Every offered row carries a git status badge (``[?]`` untracked, ``[M]``
modified, ``[D]`` deleted, ``[A]`` added) and a selection that contains a
sensitive path (``.env``, ``*.pem``, …) asks for confirmation before it touches
the index — the same guard the one-shot flow applies, applied here where the
choice is explicit.
"""
from __future__ import annotations

from .errors import GitError, sanitize_terminal
from .git_manager import GitManager, is_sensitive_path


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


def _status_badges(git: GitManager) -> dict[str, str]:
    """Best-effort path -> badge table (empty when git cannot provide one).

    The picker still works without badges, so a lookup failure must never stop
    the staging flow — it just falls back to a neutral ``?`` for every row.
    """
    lookup = getattr(git, "unstaged_badges", None)
    if not callable(lookup):
        return {}
    try:
        table = lookup()
    except Exception:
        return {}
    if not isinstance(table, dict):
        return {}
    return {str(path): str(badge) for path, badge in table.items()}


def _confirm_sensitive(paths: list[str], allow_sensitive: bool) -> bool:
    """True when staging may proceed over the selected sensitive paths.

    Warns once and asks ``[y/N]``; ``--allow-sensitive`` (or a non-interactive
    caller that already consented to sensitive files) skips the prompt. A "no"
    answer reports the cancellation and stages nothing.
    """
    flagged = [p for p in paths if is_sensitive_path(p)]
    if not flagged or allow_sensitive:
        return True
    shown = ", ".join(sanitize_terminal(p) for p in flagged[:5])
    extra = f" (+{len(flagged) - 5} more)" if len(flagged) > 5 else ""
    print(
        "[relay] warning: selected file(s) look sensitive: "
        f"{shown}{extra}; the next relay run would commit them."
    )
    answer = _input("Stage these sensitive files anyway? [y/N]: ").strip().lower()
    if answer in ("y", "yes"):
        return True
    print("[relay] stage canceled - sensitive file(s) not staged.")
    return False


def run_stage(
    *,
    git: GitManager | None = None,
    patch: bool = False,
    verbose: bool = False,
    allow_sensitive: bool = False,
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

    badges = _status_badges(git)
    print("[relay] unstaged / untracked files:")
    for i, name in enumerate(files, start=1):
        badge = badges.get(name, "?")
        print(f"    {i:>3}. [{badge}] {sanitize_terminal(name)}")

    selection = _input("Select files to stage (e.g. '1,2', '3-5', 'all', 'none'): ")
    picked = _parse_selection(selection, len(files))
    if picked is None:
        print("[relay] stage canceled - nothing changed.")
        return 0
    paths = [files[i - 1] for i in picked]
    if not _confirm_sensitive(paths, allow_sensitive):
        return 0
    git.stage_files(*paths)
    safe = ", ".join(sanitize_terminal(p) for p in paths)
    print(f"[relay] staged {len(paths)} file(s): {safe}")
    return 0


__all__ = ["run_stage"]
