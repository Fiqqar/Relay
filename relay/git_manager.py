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

# Commands that talk to a remote and must never hang the CLI forever. A local
# git op that stalls (locks, hooks) still blocks, but a network command that
# has lost its connection would otherwise wait on the OS default (indefinitely).
_NETWORK_COMMANDS = frozenset({"push", "fetch", "ls-remote"})
_NETWORK_TIMEOUT_SECONDS = 60.0


def parse_remote(url: str) -> tuple[str, str, str]:
    """Parse an HTTPS or SSH remote URL into ``(host, namespace, repo)``.

    Host-agnostic: works for ``github.com``, ``gitlab.com``, and self-hosted
    instances (``gitlab.example.com``). Handles the formats ``git`` writes for
    ``remote.origin.url``, with or without the trailing ``.git`` suffix::

        https://github.com/owner/repo.git
        git@github.com:owner/repo.git
        git@gitlab.com:group/subgroup/repo.git

    The ``namespace`` keeps every path segment before the final one joined with
    ``/``, so GitLab nested groups round-trip correctly
    (``group/subgroup/repo`` -> ``group/subgroup`` + ``repo``). Raises
    ValueError when the URL is empty, has no host, or has no owner/repo path.
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
    if not host:
        raise ValueError(f"cannot extract host from remote URL: {url}")

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"cannot extract owner/repo from remote URL: {url}")

    repo = parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not parts[0] or not repo:
        raise ValueError(f"cannot extract owner/repo from remote URL: {url}")
    namespace = "/".join(parts[:-1])
    return host, namespace, repo


def parse_remote_url(url: str) -> tuple[str, str]:
    """Parse a GitHub remote URL into ``(owner, repo)`` (GitHub only).

    Delegates to :func:`parse_remote` and rejects anything that is not
    ``github.com``, so the caller can surface a clear, actionable error. GitHub
    does not nest repositories, so ``owner`` is the first path segment and
    ``repo`` the second.
    """
    host, owner, repo = parse_remote(url)
    if host != "github.com":
        raise ValueError(f"not a GitHub remote (host: {host})")
    if "/" in owner:
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
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a git command safely.

        Args are passed as a list (never a shell string) so filenames with
        spaces or special characters cannot be injected into the shell.
        Network commands (push/fetch/ls-remote) get a hard timeout so an
        unreachable or hung remote can never stall the workflow forever; a
        timeout surfaces as GitError just like any other git failure.
        """
        cmd = ["git", *args]
        if self.verbose:
            print(f"[relay] $ {' '.join(cmd)}")
        if timeout is None and args and args[0] in _NETWORK_COMMANDS:
            timeout = _NETWORK_TIMEOUT_SECONDS
        kwargs: dict = {
            "cwd": self.cwd,
            "capture_output": True,
            "text": True,
            "input": input_text,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            proc = subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise GitError(
                f"git command timed out after {timeout:.0f}s",
                command=" ".join(cmd),
            ) from exc
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

    def diff_range(self, base: str, head: str) -> str:
        """Combined diff of commits ``base``..``head``, changed lines only.

        Mirrors ``staged_diff`` but for a commit range instead of the index:
        ``git diff {base}..{head} --unified=0``. This is the diff a squash
        (or anything comparing two commits) actually needs — the working tree /
        index may hold unrelated changes that would otherwise leak into an
        AI-generated message.
        """
        return self._run("diff", f"{base}..{head}", "--unified=0").stdout

    def stat_range(self, base: str, head: str) -> str:
        """Short diffstat of commits ``base``..``head`` (context for AI prompts)."""
        return self._run("diff", f"{base}..{head}", "--stat").stdout

    # ---- Staging / diff -----------------------------------------------------

    def stage_all(self) -> None:
        self._run("add", ".")

    def stage_files(self, *paths: str) -> None:
        """Stage exactly the given paths (`git add -- <paths>`)."""
        if not paths:
            return
        self._run("add", "--", *paths)

    def unstage(self, *paths: str) -> None:
        """Remove the given paths from the index; working tree unchanged."""
        if not paths:
            return
        self._run("reset", "--", *paths)

    def unstaged_changes(self) -> list[str]:
        """Names of files that could still be staged (unstaged or untracked).

        ``git status --porcelain`` (v1) prefixes each path with two columns:
            XY path
        ``X`` is the index column, ``Y`` the worktree column. A file with a
        worktree change (Y != ' ') or an untracked file ('??') is one ``git
        add`` away from being staged, so those are the candidates an
        interactive pick should offer.
        """
        out = self._run("status", "--porcelain").stdout
        files = []
        for line in out.splitlines():
            prefix, name = line[:2], line[3:]
            if prefix == "??":
                files.append(name)
                continue
            if prefix[1] != " ":
                files.append(name)
        return files

    def add_interactive(self) -> None:
        """Run git's own ``git add -p`` (patch mode) reading from the terminal.

        Relay delegates to the real interactive interface so the developer sees
        the exact hunks and diff context git produces. The subprocess inherits
        stdin/stdout, so arrow keys and y/n/etc. behave exactly as in a normal
        terminal.
        """
        subprocess.run(["git", "add", "-p"], cwd=self.cwd)

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

    def staged_diff_binary_only(self) -> bool:
        """True when the staged diff consists only of binary entries.

        ``git diff --cached --numstat`` prints ``<added>\\t<deleted>\\t<path>``
        and uses ``-`` for both counters on binary files. If every changed path
        is binary, the AI would be guessing at a commit message from a diff it
        cannot read, so callers fall back to manual input instead.
        """
        out = self._run("diff", "--cached", "--numstat").stdout
        lines = [line for line in out.splitlines() if line.strip()]
        if not lines:
            return False
        return all(line.startswith("-\t-\t") for line in lines)

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

    def checkout(self, branch: str) -> None:
        """Check out an existing branch (`git checkout <branch>`)."""
        self._run("checkout", branch)

    def delete_branch(self, name: str, force: bool = True) -> None:
        """Delete a branch. Force-deletes by default (`-D`) so an unmerged
        orphan branch can be cleaned up; the branch must not be checked out."""
        self._run("branch", "-D" if force else "-d", name)

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

    def commit_count(self) -> int:
        """Number of commits reachable from HEAD (0 when the repo has no commits)."""
        proc = self._run("rev-list", "--count", "HEAD", check=False)
        return int(proc.stdout.strip()) if proc.returncode == 0 else 0

    def root_commit(self) -> str:
        """SHA of the first (root) commit on HEAD ('' when the repo has no commits).

        The root is the commit with no parents, i.e. the oldest commit the
        current branch descends from. ``git rev-list --max-parents=0 HEAD``
        prints it (for a normal single-root history, exactly one line).
        """
        proc = self._run("rev-list", "--max-parents=0", "HEAD", check=False)
        if proc.returncode != 0:
            return ""
        return proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""

    def rev_parse(self, ref: str) -> str:
        """Full SHA of a ref ('' when the ref does not exist)."""
        proc = self._run("rev-parse", ref, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def has_staged_changes(self) -> bool:
        """True when the index holds staged changes (the index differs from HEAD).

        Untracked files are not included: a path counts only once it has been
        ``git add``-ed. This is the guard squash uses to refuse folding when the
        index carries unrelated changes that a ``reset --soft`` would sweep into
        the new commit.
        """
        return bool(self._run("diff", "--cached", "--name-only").stdout.strip())

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """True when ``ancestor`` is reachable from ``descendant``."""
        return self._run(
            "merge-base", "--is-ancestor", ancestor, descendant, check=False
        ).returncode == 0

    def reset_soft(self, target: str = "HEAD~1") -> None:
        """Non-destructive reset: move HEAD to ``target``, keep changes staged.

        Nothing is discarded — the reset range's diff stays in the index, so a
        new commit (or an amend) can reuse it exactly. ``undo`` uses the default
        ``HEAD~1``; ``squash`` passes ``HEAD~N`` to fold several commits.
        """
        self._run("reset", "--soft", target)
