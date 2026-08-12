"""relay squash — fold the last N commits into a single new one.

The workflow is deliberately non-destructive and local-only:
    HEAD~N   → (soft reset) →  everything staged  →  one new commit

A ``git reset --soft HEAD~N`` never touches the working tree: the combined diff
of the squashed commits is staged, ready to become a single commit with a
single (optionally AI-generated) Conventional Commit message. Like ``relay
undo``, squash never pushes — rewriting history is the developer's call, and
syncing a pushed branch needs ``git push --force-with-lease``.

Message resolution order (mirrors pr.py):
    1. explicit ``--message``
    2. an AI-generated subject for the combined diff of the squashed commits
       (``git diff base..tip``, falling back to the top commit's message when
       the AI is unavailable or returns something unusable)
    3. the message of the top commit (HEAD) in the squashed range
"""
from __future__ import annotations

from .commit import sanitize_ai_message, validate_conventional
from .errors import GitError, UserAbort
from .git_manager import GitManager
from .prompt import CONFIRM_PROMPT, interpret_choice


def _confirm(message: str, yes: bool) -> str:
    """Confirm/let the user edit the proposed message (skippable with --yes)."""
    if yes:
        return message
    action = interpret_choice(input(CONFIRM_PROMPT))
    if action == "accept":
        return message
    if action == "edit":
        raise UserAbort(
            "manual message editing is not supported by squash; pass --message"
        )
    raise UserAbort("workflow aborted by user")


def _message_from_ai(provider, diff: str, stat: str, branch: str, fallback: str) -> str:
    """One-shot AI message with a clean fallback to ``fallback`` on any failure.

    Unlike solo/team, squash has no interactive fallback prompt — it is a
    non-destructive, scriptable local operation — so a failed or invalid AI
    response keeps the top commit's message instead of blocking on input() or
    aborting the workflow.
    """
    try:
        raw = provider.generate(diff, stat, branch)
        message = sanitize_ai_message(raw)
        valid, _ = validate_conventional(message)
        if valid:
            return message
        print("[relay] AI response rejected; keeping the top commit's message.")
    except Exception:  # noqa: BLE001 - any provider failure falls back cleanly
        print("[relay] AI unavailable; keeping the top commit's message.")
    return fallback


def run_squash(
    *,
    git: GitManager | None = None,
    provider=None,
    count: int = 2,
    message: str | None = None,
    yes: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Squash the last ``count`` commits into one. Returns the exit code."""
    git = git or GitManager(verbose=verbose)

    if count < 2:
        raise GitError("squash needs at least 2 commits (--count N)")
    if not git.has_commits():
        raise GitError("no commits to squash")
    # The index must be clean: ``reset --soft`` keeps it as-is, so anything
    # staged before the squash (unrelated files) would silently be folded into
    # the new commit. Refuse early, before any AI call or confirmation.
    if git.has_staged_changes():
        raise GitError(
            "the index has unrelated staged changes; commit or unstage them "
            "first (git reset -- <path>) before squashing"
        )

    tip = git.rev_parse("HEAD")
    total = git.commit_count()
    base = git.rev_parse(f"HEAD~{count}")
    squash_all = False
    if not base:
        if total and count <= total:
            # Squashing the entire history: ``HEAD~N`` points past the root
            # commit, so fold everything into the root instead. The reset
            # target becomes the root and the final commit is an --amend, which
            # leaves exactly ONE commit holding the whole tree.
            base = git.root_commit()
            squash_all = True
        else:
            raise GitError(
                f"not enough history to squash {count} commit(s); "
                f"only {total} on HEAD"
            )

    subjects = git.log_between(base, tip)
    branch = git.current_branch()

    # Resolve the message BEFORE any mutation (--dry-run must change nothing).
    # The fallback is the top commit's subject — shared by the AI-failure and
    # no-provider paths so both degrade to the same sensible default.
    top = git.latest_commit_message()
    fallback = top.splitlines()[0] if top else f"squash {count} commits"
    if message and message.strip():
        final_message = message.strip()
    elif provider is not None:
        # The combined diff of the squashed commits — NOT the index. The index
        # still holds whatever the working tree happened to have staged, which
        # is unrelated (or empty) here because reset --soft runs later.
        diff = git.diff_range(base, tip)
        stat = git.stat_range(base, tip)
        final_message = _message_from_ai(provider, diff, stat, branch, fallback)
    else:
        final_message = fallback

    final_message = _confirm(final_message, yes)

    if dry_run:
        print(f"[relay] dry-run (mode=squash): fold {count} commits into one")
        print(f"[relay]     message: {final_message}")
        print(f"[relay]     commits: {subjects or '(none)'}")
        return 0

    # Soft reset stages everything the N commits introduced; the working tree
    # itself is untouched, so nothing can be lost. Squashing the entire history
    # amends the root commit so the fold leaves a single commit behind.
    reset_target = base if squash_all else f"HEAD~{count}"
    git.reset_soft(reset_target)
    try:
        git.commit(final_message, amend=squash_all)
    except GitError:
        # The reset already moved HEAD; a failed commit (e.g. a rejecting hook)
        # must not leave the branch mid-reset. `git reset --soft <tip>` moves
        # HEAD back without touching the working tree or the index, restoring
        # the exact pre-squash state — everything stays staged, nothing is lost.
        try:
            git.reset_soft(tip)
        except GitError:
            pass
        print(
            "[relay] squash commit failed; HEAD restored to its original commit. "
            "Inspect `git status` — your changes are still there (reflog: "
            "`git reflog`)."
        )
        raise
    print(f"[relay] squashed {count} commits into one on '{branch}'")
    if git.is_ancestor(tip, f"origin/{branch}"):
        print(
            "[relay] note: the squashed commits were already pushed; syncing the "
            "remote needs `git push --force-with-lease`"
        )
    return 0


__all__ = ["run_squash"]
