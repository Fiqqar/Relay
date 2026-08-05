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

import webbrowser

from .commit import sanitize_ai_message
from .errors import RelayError
from .git_manager import GitManager, parse_remote_url
from .github import DuplicatePullRequestError, GitHubClient, GitHubError

_PR_TITLE_MAX = 200


def _pr_url(owner: str, repo: str, number) -> str:
    return f"https://github.com/{owner}/{repo}/pull/{number}"


def _exit_existing_pr(
    client: GitHubClient, owner: str, repo: str, existing, open_browser: bool
) -> int:
    """Report an existing PR (or the best URL we can build) and stop gracefully."""
    if existing is not None:
        url = existing.get("html_url") or _pr_url(owner, repo, existing.get("number"))
    else:
        url = f"https://github.com/{owner}/{repo}/pulls"
    print(f"[relay] PR already exists: {url}")
    if open_browser:
        webbrowser.open(url)
    return 0


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
    open_browser: bool = False,
    verbose: bool = False,
) -> int:
    """Open a PR for the current branch. Returns the process exit code.

    ``open_browser`` opens the PR URL (created or pre-existing) in the default
    web browser via ``webbrowser``. The duplicate check happens up front, so a
    branch that already has an open PR never triggers a fetch or an AI call.
    """
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

    # GitHub cannot open a PR for a branch it has never seen: fail fast with the
    # exact push command instead of surfacing a confusing 422 from the API.
    if not git.remote_has_branch(head):
        raise RelayError(
            f"branch '{head}' has not been pushed to origin; "
            f"run `git push -u origin {head}` first"
        )

    client = GitHubClient(owner, repo, verbose=verbose)

    # Anti-duplicate: an open PR for this head branch is a no-op, not a 422.
    existing = client.find_open_pr(head=head)
    if existing is not None:
        return _exit_existing_pr(client, owner, repo, existing, open_browser)

    # Refresh the remote base so the body reflects commits GitHub actually knows
    # about, not a stale local branch. A failed fetch is fine — log_between()
    # then falls back to the local base ref.
    git.fetch("origin", base, check=False)

    pr_title = _resolve_title(git, title=title, provider=provider)
    body = _build_body(git, base=base, head=head)

    try:
        created = client.open_pull(title=pr_title, head=head, base=base, body=body)
    except DuplicatePullRequestError:
        # Safety net: the GET above missed it (race, or a fork-owner head), but
        # GitHub rejected the POST as a duplicate. Re-query and exit gracefully
        # instead of surfacing a raw 422 to the user.
        return _exit_existing_pr(
            client, owner, repo, client.find_open_pr(head=head), open_browser
        )
    except GitHubError as exc:
        if exc.status == 422:
            # No commits between base and head, or the PR is already merged or
            # closed: GitHub refused to create it. Report the exact reason
            # instead of letting a cryptic 422 crash the workflow.
            print(f"[relay] Cannot open PR: {exc.reason}")
            return 1
        raise

    number = created.get("number")
    url = created.get("html_url") or _pr_url(owner, repo, number)
    print(f"[relay] opened PR #{number}: {url}")
    if open_browser:
        webbrowser.open(url)
    return 0


__all__ = ["run_pr"]
