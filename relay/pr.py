"""relay pr — open a pull request / merge request for the current branch.

Detects the remote host from ``origin`` and routes to the matching forge client:
GitHub (``github.com``) or GitLab (``gitlab.com`` / self-hosted instance).

Follows the same shape as ``doctor.py``: a small ``run_pr()`` orchestrator that
lives in its own module so the CLI just routes to it. It only reads from git
and posts to the forge — it never mutates the working tree.

Title resolution order (first match wins):
    1. the explicit ``--title`` flag
    2. the latest commit message (first line)
    3. an AI-generated subject, only if a provider was injected
    otherwise it fails with an actionable message.
"""
from __future__ import annotations

import urllib.parse
import webbrowser

from .bitbucket import BitbucketClient, BitbucketError
from .bitbucket import DuplicatePullRequestError as BitbucketDuplicateError
from .commit import sanitize_ai_message
from .config import trusted_github_hosts, trusted_gitlab_hosts
from .errors import RelayError, sanitize_terminal
from .git_manager import GitManager, parse_remote
from .github import DuplicatePullRequestError, GitHubClient, GitHubError
from .gitlab import DuplicateMergeRequestError, GitLabClient, GitLabError

_PR_TITLE_MAX = 200


def _safe_open_browser(url: str) -> bool:
    """Open *url* in the default browser only if its scheme is http or https."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() in ("http", "https"):
        webbrowser.open(url)
        return True
    print(f"[relay] refusing to open non-http(s) URL in browser: {url}")
    return False


def _host_web_base(host: str, owner: str, repo: str) -> str:
    """Human-visible base URL a browser can open for this host's PR list."""
    if host in trusted_github_hosts():
        return f"https://{host}/{owner}/{repo}/pulls"
    if host == "bitbucket.org":
        return f"https://bitbucket.org/{owner}/{repo}/pull-requests"
    return f"https://{host}/{owner}/{repo}/-/merge_requests"


def _pr_web_url(host: str, owner: str, repo: str, number) -> str:
    if host in trusted_github_hosts():
        return f"https://{host}/{owner}/{repo}/pull/{number}"
    if host == "bitbucket.org":
        return f"https://bitbucket.org/{owner}/{repo}/pull-requests/{number}"
    return f"https://{host}/{owner}/{repo}/-/merge_requests/{number}"


def _existing_url(host: str, owner: str, repo: str, existing) -> str:
    """The best URL for an existing PR/MR resource across the forge clients.

    GitHub and GitLab expose ``html_url``/``web_url`` at the top level while
    Bitbucket nests it under ``links.html.href``, so this helper normalizes all
    three before falling back to a best-effort constructed URL.
    """
    if existing is None:
        return _host_web_base(host, owner, repo)
    url = existing.get("html_url") or existing.get("web_url") or ""
    if not url:
        html = (existing.get("links") or {}).get("html") or {}
        url = html.get("href") or ""
    if url:
        return url
    number = existing.get("number") or existing.get("iid") or existing.get("id")
    return _pr_web_url(host, owner, repo, number)


def _exit_existing_pr_host(
    host: str, owner: str, repo: str, existing, open_browser: bool
) -> int:
    """Report an existing PR/MR (or the best URL we can build) and stop gracefully."""
    url = _existing_url(host, owner, repo, existing)
    print(f"[relay] PR already exists: {sanitize_terminal(url)}")
    if open_browser:
        _safe_open_browser(url)
    return 0


def _resolve_title(
    git: GitManager,
    *,
    title: str | None,
    base: str = "main",
    head: str = "",
    provider=None,
) -> str:
    """Pick the PR title; raises RelayError when none can be derived."""
    if title and title.strip():
        return title.strip()[:_PR_TITLE_MAX]
    commit_msg = git.latest_commit_message()
    if commit_msg:
        return commit_msg.splitlines()[0][:_PR_TITLE_MAX]
    if provider is not None:
        target_head = head or git.current_branch()
        remote_base = f"origin/{base}"
        range_diff = git.diff_range(remote_base, target_head)
        range_stat = git.stat_range(remote_base, target_head)
        subject = sanitize_ai_message(
            provider.generate(range_diff, range_stat, target_head)
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


def _run_github(
    *,
    host: str = "github.com",
    owner: str,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
    draft: bool,
    open_browser: bool,
    verbose: bool,
) -> int:
    if host == "github.com":
        client = GitHubClient(owner, repo, verbose=verbose)
    else:
        client = GitHubClient(owner, repo, host=host, verbose=verbose)
    existing = client.find_open_pr(head=head)
    if existing is not None:
        return _exit_existing_pr_host(host, owner, repo, existing, open_browser)
    try:
        created = client.open_pull(
            title=title, head=head, base=base, body=body, draft=draft
        )
    except DuplicatePullRequestError:
        # Race or a fork-owner head: re-query and exit gracefully instead of a 422.
        existing = client.find_open_pr(head=head)
        return _exit_existing_pr_host(host, owner, repo, existing, open_browser)
    except GitHubError as exc:
        if exc.status == 422:
            print(f"[relay] Cannot open PR: {sanitize_terminal(exc.reason)}")
            return 1
        raise
    number = created.get("number")
    url = created.get("html_url") or _pr_web_url(host, owner, repo, number)
    print(f"[relay] opened PR #{number}: {sanitize_terminal(str(url))}")
    if open_browser:
        _safe_open_browser(url)
    return 0


def _run_bitbucket(
    *,
    owner: str,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
    draft: bool,
    open_browser: bool,
    verbose: bool,
) -> int:
    client = BitbucketClient(owner, repo, verbose=verbose)
    existing = client.find_open_pull(source_branch=head)
    if existing is not None:
        return _exit_existing_pr_host("bitbucket.org", owner, repo, existing, open_browser)
    try:
        created = client.open_pull(
            title=title, source_branch=head, destination_branch=base,
            description=body, draft=draft,
        )
    except BitbucketDuplicateError:
        # Race or a stale lookup: re-query and exit gracefully instead of a 400.
        existing = client.find_open_pull(source_branch=head)
        return _exit_existing_pr_host("bitbucket.org", owner, repo, existing, open_browser)
    except BitbucketError as exc:
        if exc.status in (400, 409):
            print(f"[relay] Cannot open PR: {sanitize_terminal(exc.reason)}")
            return 1
        raise
    number = created.get("id")
    url = (created.get("links") or {}).get("html", {}).get("href") or _pr_web_url(
        "bitbucket.org", owner, repo, number
    )
    print(f"[relay] opened PR #{number}: {sanitize_terminal(str(url))}")
    if open_browser:
        _safe_open_browser(url)
    return 0


def _run_gitlab(
    *,
    host: str,
    owner: str,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
    draft: bool,
    open_browser: bool,
    verbose: bool,
) -> int:
    client = GitLabClient(host, f"{owner}/{repo}", verbose=verbose)
    existing = client.find_open_mr(source_branch=head)
    if existing is not None:
        return _exit_existing_pr_host(host, owner, repo, existing, open_browser)
    try:
        created = client.open_merge_request(
            title=title,
            source_branch=head,
            target_branch=base,
            description=body,
            draft=draft,
        )
    except DuplicateMergeRequestError:
        existing = client.find_open_mr(source_branch=head)
        return _exit_existing_pr_host(host, owner, repo, existing, open_browser)
    except GitLabError as exc:
        if exc.status in (400, 409):
            print(f"[relay] Cannot open MR: {sanitize_terminal(exc.reason)}")
            return 1
        raise
    number = created.get("iid")
    url = created.get("web_url") or _pr_web_url(host, owner, repo, number)
    print(f"[relay] opened MR #{number}: {sanitize_terminal(str(url))}")
    if open_browser:
        _safe_open_browser(url)
    return 0


def run_pr(
    *,
    git: GitManager | None = None,
    base: str = "main",
    title: str | None = None,
    provider=None,
    open_browser: bool = False,
    draft: bool = False,
    verbose: bool = False,
) -> int:
    """Open a PR/MR for the current branch. Returns the process exit code.

    ``open_browser`` opens the PR URL (created or pre-existing) in the default
    web browser via ``webbrowser``. ``draft`` opens it as a draft (visible but
    not ready for review). The duplicate check happens up front, so a branch
    that already has an open PR never triggers a fetch or an AI call.
    """
    git = git or GitManager(verbose=verbose)

    if not git.is_repo():
        raise RelayError("not a git repository - run `relay pr` from inside a work tree")

    remote = git.remote_url()
    if not remote:
        raise RelayError(
            "no 'origin' remote configured; cannot determine the hosting service "
            "(add one with `git remote add origin <url>`)"
        )
    try:
        host, owner, repo = parse_remote(remote)
    except ValueError as exc:
        raise RelayError(str(exc)) from exc

    # The forge host is derived from `origin`, which a malicious repository
    # (e.g. a fork you clone) can point anywhere. Only github.com and
    # bitbucket.org are trusted by default; any other host is refused before
    # any token is read or any request is sent unless it is a GitHub Enterprise
    # or GitLab instance the user explicitly trusts (SECURITY: credential exfil).
    trusted_gh = trusted_github_hosts()
    trusted_gl = trusted_gitlab_hosts()
    if host not in trusted_gh and host != "bitbucket.org" and host not in trusted_gl:
        raise RelayError(
            f"unsupported or untrusted forge host '{host}': `relay pr` supports "
            "github.com and bitbucket.org by default, plus self-hosted instances "
            "listed in RELAY_TRUSTED_GITHUB_HOSTS or RELAY_TRUSTED_GITLAB_HOSTS. "
            "The host comes from your 'origin' remote, which an attacker could control; "
            "refusing to send a forge token to an unvetted host"
        )

    head = git.current_branch()
    if not head:
        raise RelayError("HEAD is detached; check out a branch before opening a PR")
    head_sha = git.rev_parse("HEAD")

    # A forge cannot open a PR/MR for a branch it has never seen: fail fast with
    # the exact push command instead of surfacing a confusing 4xx from the API.
    if not git.remote_has_branch(head):
        raise RelayError(
            f"branch '{head}' has not been pushed to origin; "
            f"run `git push -u origin {head}` first"
        )

    if not base or base.startswith("-") or ".." in base or base.startswith("."):
        raise RelayError(f"invalid base branch name {base!r} (use --base <branch>, e.g. --base main)")

    # Refresh the remote base so the body reflects commits the host actually
    # knows about, not a stale local branch. A failed fetch is fine —
    # log_between() then falls back to the local base ref.
    git.fetch("origin", base, check=False)

    # Branch/HEAD re-verification (shared helper): the fetch above is a
    # network call with a wide window, and a concurrent `git switch` must
    # not open a PR for the wrong branch.
    git.check_branch_and_head(head, head_sha)

    pr_title = _resolve_title(git, title=title, base=base, head=head, provider=provider)
    body = _build_body(git, base=base, head=head)

    if host in trusted_gh:
        return _run_github(
            host=host, owner=owner, repo=repo, head=head, base=base,
            title=pr_title, body=body, draft=draft,
            open_browser=open_browser, verbose=verbose,
        )
    if host in trusted_gl:
        return _run_gitlab(
            host=host, owner=owner, repo=repo, head=head, base=base,
            title=pr_title, body=body, draft=draft,
            open_browser=open_browser, verbose=verbose,
        )
    return _run_bitbucket(
        owner=owner, repo=repo, head=head, base=base,
        title=pr_title, body=body, draft=draft,
        open_browser=open_browser, verbose=verbose,
    )


__all__ = ["run_pr"]
