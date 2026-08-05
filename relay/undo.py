"""relay undo — non-destructive undoing of the last commit.

Pure local operation: ``git reset --soft HEAD~1`` moves HEAD back one commit
and keeps every change staged, so nothing is lost and the working tree is never
touched. Mirrors the tool's "no destructive git" guarantee — it never
force-pushes and never deletes anything.

If the undone commit was already pushed, the local branch is now behind the
remote by one commit, so the warning explains how to sync.
"""
from __future__ import annotations

from .errors import GitError
from .git_manager import GitManager


def run_undo(git: GitManager | None = None, verbose: bool = False) -> int:
    """Undo the last commit. Returns the process exit code."""
    git = git or GitManager(verbose=verbose)

    if not git.is_repo():
        raise GitError("not a git repository - run `relay undo` from inside a work tree")
    if not git.has_commits():
        raise GitError("no commits to undo (the repository has no HEAD)")

    branch = git.current_branch() or "HEAD"
    tip = git.rev_parse("HEAD")
    pushed = bool(tip and git.is_ancestor(tip, f"origin/{branch}"))

    git.reset_soft()
    print(f"[relay] undone last commit on '{branch}' (changes are staged, nothing lost)")

    if pushed:
        print(
            "[relay] warning: that commit was already pushed; the remote is now "
            "one commit ahead of this branch (sync needs a force-push or a new commit)"
        )
    return 0


__all__ = ["run_undo"]
