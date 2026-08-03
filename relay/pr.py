"""relay pr — open a GitHub pull request for the current branch.

Follows the same shape as ``doctor.py``: a small ``run_pr()`` orchestrator that
lives in its own module so the CLI just routes to it. It only reads from git
and posts to GitHub — it never mutates the working tree.

Title resolution order (first match wins):
    1. the explicit ``--title`` flag
    2. the latest commit message (first line)
    3. an AI-generated subject, only if a provider was injected
    otherwise it fails with an actionable message.
"""
from __future__ import annotations

from .commit import sanitize_ai_message
from .errors import RelayError
from .git_manager import GitManager, parse_remote_url
from .github import GitHubClient

_PR_TITLE_MAX = 200


def _resolve_title(
    git: GitManager, *, title: str | None, provider=None
) -> str:
    """Pick the PR title; raises RelayError when none can be derived."""
    if title and title.strip():
        return title.strip()[:_PR_TITLE_MAX]
    commit_msg = git.latest_commit_message()
    if commit_msg:
        return commit_msg.splitlines()[0][:_PR_TITLE_MAX]
    if provider is not None:
        subject = sanitize_ai_message(
            provider.generate(git.staged_diff(), git.staged_stat(), git.current_branch())
        )
        if subject:
            return subject[:_PR_TITLE_MAX]
    raise RelayError(
        "could not derive a PR title (no --title and no commits to read); "
        "pass --title"
    )


def _build_body(git: GitManager, *, base: str, head: str) -> str:
    """A short markdown body listing the commits on ``head`` since the remote base.

    Compares against ``origin/{base}`` (refreshed by ``run_pr`` via fetch) so a
    stale local base branch cannot make the body list already-merged commits.
    """
    remote_base = f"origin/{base}"
    subjects = git.log_between(remote_base, head)
    if not subjects:
        return ""
    lines = [f"Commits in `{head}` (vs `{remote_base}`):", ""]
    lines += [f"- {subject}" for subject in subjects.splitlines()]
    return "\n".join(lines)


def run_pr(
    *,
    git: GitManager | None = None,
    base: str = "main",
    title: str | None = None,
    provider=None,
    verbose: bool = False,
) -> int:
    """Open a PR for the current branch. Returns the process exit code."""
    git = git or GitManager(verbose=verbose)

    if not git.is_repo():
        raise RelayError("not a git repository - run `relay pr` from inside a work tree")

    remote = git.remote_url()
    if not remote:
        raise RelayError(
            "no 'origin' remote configured; cannot determine the GitHub repository"
        )
    try:
        owner, repo = parse_remote_url(remote)
    except ValueError as exc:
        raise RelayError(str(exc)) from exc

    head = git.current_branch()
    if not head:
        raise RelayError("HEAD is detached; check out a branch before opening a PR")

    # Refresh the remote base so the body reflects commits GitHub actually knows
    # about, not a stale local branch. A failed fetch is fine — log_between()
    # then falls back to the local base ref.
    git.fetch("origin", base, check=False)

    pr_title = _resolve_title(git, title=title, provider=provider)
    body = _build_body(git, base=base, head=head)

    client = GitHubClient(owner, repo)
    created = client.open_pull(title=pr_title, head=head, base=base, body=body)

    number = created.get("number")
    url = created.get("html_url") or f"https://github.com/{owner}/{repo}/pull/{number}"
    print(f"[relay] opened PR #{number}: {url}")
    return 0


__all__ = ["run_pr"]
