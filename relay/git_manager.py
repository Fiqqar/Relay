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

    def commit(self, message: str) -> None:
        """Commit with the message piped via stdin (`git commit -F -`).

        Using stdin instead of `-m` avoids shell-quoting bugs with special
        characters and lets multi-line manual messages pass through unchanged.
        """
        self._run("commit", "-F", "-", input_text=message)

    def create_branch(self, name: str) -> None:
        """Create and check out a new branch (`git checkout -b`)."""
        self._run("checkout", "-b", name)

    def push(self, branch: str, set_upstream: bool = False) -> None:
        cmd = ["push"]
        if set_upstream:
            cmd.append("-u")
        cmd += ["origin", branch]
        self._run(*cmd)
