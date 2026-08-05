"""GitManager: the only place that talks to the git CLI.

Design notes
------------
* We shell out to the real `git` binary (argv as a list, never shell=True)
  instead of a pure-Python git library, so Relay inherits the user's
  credential helpers, SSH agent, and hooks exactly like normal git usage.
* Every call captures stdout/stderr and raises GitError on failure, so the
  Orchestrator can decide how to recover without parsing terminal output.
"""
from __future__ import annotations

import subprocess

from .errors import GitError


def parse_remote_url(url: str) -> tuple[str, str]:
    """Parse an HTTPS or SSH GitHub remote URL into ``(owner, repo)``.

    Handles the two formats ``git`` writes for ``remote.origin.url``, with or
    without the trailing ``.git`` suffix::

        https://github.com/owner/repo.git
        git@github.com:owner/repo.git

    Raises ValueError when the URL is empty, not a GitHub remote, or has no
    owner/repo path, so the caller can surface a clear, actionable error.
    """
    url = url.strip()
    if not url:
        raise ValueError("empty remote URL")

    if "://" in url:
        # URL style: https://host/owner/repo.git  (ssh:// is also handled here)
        rest = url.split("://", 1)[1]
        host, _, path = rest.partition("/")
    elif "@" in url:
        # scp style: git@host:owner/repo.git
        host, _, path = url.rpartition(":")
    else:
        raise ValueError(f"unsupported remote URL: {url}")

    # Drop a trailing slash and any username prefix (git@github.com -> github.com).
    host = host.rstrip("/").rsplit("@", 1)[-1].lower()
    if host != "github.com":
        raise ValueError(f"not a GitHub remote (host: {host})")

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"cannot extract owner/repo from remote URL: {url}")

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValueError(f"cannot extract owner/repo from remote URL: {url}")
    return owner, repo


class GitManager:
    def __init__(self, cwd: str | None = None, verbose: bool = False):
        self.cwd = cwd
        self.verbose = verbose

    def _run(
        self,
        *args: str,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a git command safely.

        Args are passed as a list (never a shell string) so filenames with
        spaces or special characters cannot be injected into the shell.
        """
        cmd = ["git", *args]
        if self.verbose:
            print(f"[relay] $ {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            input=input_text,
        )
        if check and proc.returncode != 0:
            raise GitError(
                f"git command failed (exit {proc.returncode})",
                command=" ".join(cmd),
                stderr=proc.stderr.strip(),
            )
        return proc

    # ---- Preflight helpers -------------------------------------------------

    def is_repo(self) -> bool:
        """True if the current directory is inside a git work tree."""
        try:
            out = self._run("rev-parse", "--is-inside-work-tree").stdout.strip()
            return out == "true"
        except GitError:
            return False

    def has_changes(self) -> bool:
        """True if there is anything git could commit (staged or unstaged)."""
        return bool(self._run("status", "--porcelain").stdout.strip())

    def has_remote(self) -> bool:
        """True if at least one remote is configured."""
        return bool(self._run("remote").stdout.strip())

    def current_branch(self) -> str:
        """Name of the checked-out branch (empty string if HEAD is detached)."""
        return self._run("branch", "--show-current").stdout.strip()

    def config_get(self, key: str) -> str:
        """Value of a git config key ('' when unset, local or global).

        ``git config --get`` exits 1 when the key is absent; that is treated as
        "unset" rather than an error so callers can give their own message
        (e.g. a missing user.name before a commit).
        """
        proc = self._run("config", "--get", key, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def remote_url(self, name: str = "origin") -> str:
        """Value of ``remote.<name>.url`` ('' if that remote is not configured)."""
        return self.config_get(f"remote.{name}.url")

    def remote_has_branch(self, branch: str, remote: str = "origin") -> bool:
        """True when ``branch`` exists on the given remote.

        ``git ls-remote --exit-code --heads`` exits 0 when the ref is found and
        1 otherwise, so a missing branch (or an offline remote) simply yields
        False instead of raising.
        """
        proc = self._run(
            "ls-remote", "--exit-code", "--heads", remote, branch, check=False
        )
        return proc.returncode == 0

    def latest_commit_message(self) -> str:
        """Full message of the most recent commit ('' if the repo has no commits)."""
        proc = self._run("log", "-1", "--format=%B", check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def log_between(self, base: str, head: str) -> str:
        """One-line subjects of commits reachable from ``head`` but not ``base``.

        Empty when ``base`` does not exist yet (or the range is empty), so
        callers can fall back to a plain body without handling git errors.
        """
        proc = self._run("log", "--format=%s", f"{base}..{head}", check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    # ---- Staging / diff -----------------------------------------------------

    def stage_all(self) -> None:
        self._run("add", ".")

    def staged_diff(self) -> str:
        """Optimized staged diff for the AI: changed lines only (``--unified=0``).

        Dropping unchanged context shrinks the payload sent to the LLM by a
        large margin — for commit-message generation the actual +/- lines are
        what matter, and a smaller prompt means a much faster generation. The
        concise ``--stat`` summary is available separately via staged_stat().
        """
        return self._run("diff", "--cached", "--unified=0").stdout

    def staged_stat(self) -> str:
        """Short diffstat of staged changes (context for the AI prompt)."""
        return self._run("diff", "--cached", "--stat").stdout

    # ---- Commit / branch / push ---------------------------------------------

    def commit(
        self, message: str, *, amend: bool = False, no_verify: bool = False
    ) -> None:
        """Commit with the message piped via stdin (`git commit -F -`).

        Using stdin instead of `-m` avoids shell-quoting bugs with special
        characters and lets multi-line manual messages pass through unchanged.
        ``amend`` rewrites the last commit (`git commit --amend`) instead of
        creating a new one; ``no_verify`` skips pre-commit and commit-msg hooks.
        """
        cmd = ["commit"]
        if no_verify:
            cmd.append("--no-verify")
        if amend:
            cmd.append("--amend")
        cmd += ["-F", "-"]
        self._run(*cmd, input_text=message)

    def create_branch(self, name: str) -> None:
        """Create and check out a new branch (`git checkout -b`)."""
        self._run("checkout", "-b", name)

    def push(self, branch: str, set_upstream: bool = False) -> None:
        cmd = ["push"]
        if set_upstream:
            cmd.append("-u")
        cmd += ["origin", branch]
        self._run(*cmd)

    def fetch(self, remote: str = "origin", ref: str = "", check: bool = True) -> None:
        """Fetch ``ref`` from ``remote`` into the local refs.

        A best-effort sync so PR helpers can compare against the *remote* state
        (e.g. ``origin/main``) instead of a possibly-stale local branch. Callers
        that tolerate an offline network should pass ``check=False`` — a failed
        fetch falls back to whatever refs are already present.
        """
        cmd = ["fetch", remote]
        if ref:
            cmd.append(ref)
        self._run(*cmd, check=check)

    # ---- Undo helpers ---------------------------------------------------------

    def has_commits(self) -> bool:
        """True if the current HEAD points at a real commit (repo is not empty)."""
        return self._run("rev-parse", "--verify", "HEAD", check=False).returncode == 0

    def rev_parse(self, ref: str) -> str:
        """Full SHA of a ref ('' when the ref does not exist)."""
        proc = self._run("rev-parse", ref, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """True when ``ancestor`` is reachable from ``descendant``."""
        return self._run(
            "merge-base", "--is-ancestor", ancestor, descendant, check=False
        ).returncode == 0

    def reset_soft(self) -> None:
        """Non-destructive undo: move HEAD back one commit, keep the changes staged.

        Nothing is discarded — the undone commit's diff stays in the index, so a
        new commit (or an amend) can reuse it exactly.
        """
        self._run("reset", "--soft", "HEAD~1")
