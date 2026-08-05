"""relay doctor — a self-diagnostic for a Relay installation.

Runs a battery of read-only checks against the local environment and prints a
pass/warn/fail report. Exits 0 when nothing is broken, 1 when a fix is needed,
so it composes cleanly with installers and CI smoke tests.

Pure stdlib only, matching the zero-dependency philosophy of the rest of the
tool. Every check degrades gracefully and never raises.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass

from . import __version__
from .config import (
    DEFAULT_OLLAMA_BASE_URL,
    gemini_api_key,
    ollama_base_url,
    provider_from_env,
)
from .git_manager import GitManager
from .github import github_token

_MARKS = {"ok": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str = ""


def _git_version() -> str:
    try:
        out = subprocess.run(
            ["git", "--version"], capture_output=True, text=True
        ).stdout.strip()
        return out.replace("git version ", "")
    except OSError:
        return ""


def _git_status(git: GitManager) -> tuple[bool, str]:
    """Return (clean, detail): `clean` is True when the repo is ready to run."""
    if not git.is_repo():
        return False, "not inside a git repository (run: git init)"
    parts = [f"branch: {git.current_branch() or '(detached)'}"]
    parts.append("remote: yes" if git.has_remote() else "remote: none")
    if git.has_changes():
        parts.append("uncommitted changes: yes")
        return True, ", ".join(parts)
    parts.append("working tree: clean")
    return True, ", ".join(parts)


def _ollama_reachable(url: str) -> tuple[bool, str]:
    """Best-effort TCP probe of the Ollama endpoint (1s timeout, never blocks)."""
    try:
        host = url.split("://", 1)[1].split("/", 1)[0]
        port = 80
        if ":" in host:
            host, _, port_s = host.rpartition(":")
            port = int(port_s)
    except (IndexError, ValueError):
        return False, f"cannot parse URL: {url}"
    try:
        with socket.create_connection((host, port), timeout=1):
            return True, f"reachable at {url}"
    except OSError as exc:
        return False, f"not reachable at {url} ({exc})"


def run_doctor(provider: str | None = None, verbose: bool = False) -> int:
    """Run all checks and print the report. Returns the exit code."""
    git = GitManager(verbose=verbose)
    chosen = (provider or provider_from_env()).lower()

    checks: list[Check] = [
        Check("Python 3.10+", "ok" if sys.version_info >= (3, 10) else "fail",
              f"{sys.version.split()[0]}"),
        Check("relay on PATH", "skip", ""),
        Check("git installed", "skip", ""),
        Check("inside a git repo", "skip", ""),
        Check("git identity", "skip", ""),
        Check(f"provider: {chosen}", "skip", ""),
        Check("AI credentials", "skip", ""),
        Check("GitHub token", "skip", ""),
    ]

    # relay on PATH
    resolved = shutil.which("relay")
    if resolved:
        checks[1].status = "ok"
        checks[1].detail = resolved
    else:
        checks[1].status = "warn"
        checks[1].detail = "not found; run `python install.py` (or `pip install -e .`)"

    # git
    git_path = shutil.which("git")
    if git_path:
        checks[2].status = "ok"
        checks[2].detail = f"{git_path} ({_git_version()})"
    else:
        checks[2].status = "fail"
        checks[2].detail = "not found on PATH"

    # repo
    clean, detail = _git_status(git)
    checks[3].status = "ok" if clean else "warn"
    checks[3].detail = detail

    # git identity: a commit is impossible without user.name / user.email.
    name = git.config_get("user.name")
    email = git.config_get("user.email")
    if name and email:
        checks[4].status = "ok"
        checks[4].detail = f"{name} <{email}>"
    else:
        missing = [k for k, v in (("user.name", name), ("user.email", email)) if not v]
        checks[4].status = "fail"
        checks[4].detail = (
            f"not set ({', '.join(missing)}); run "
            f"`git config --global {missing[0]} \"you@example.com\"`"
        )

    # provider-specific credential checks
    checks[5].status = "ok"
    if chosen == "gemini":
        checks[5].detail = "Gemini API"
        key = gemini_api_key()
        if key:
            checks[6].status = "ok"
            checks[6].detail = "GEMINI_API_KEY is set"
        else:
            checks[6].status = "fail"
            checks[6].detail = "GEMINI_API_KEY is not set; see `relay --help`"
    else:
        checks[5].detail = "Ollama"
        base = ollama_base_url()
        if base != DEFAULT_OLLAMA_BASE_URL:
            checks[5].detail = f"Ollama ({base})"
        if chosen != "ollama":
            checks[6].status = "warn"
            checks[6].detail = f"unknown provider '{chosen}' (expected gemini|ollama)"
        else:
            reachable, detail = _ollama_reachable(base)
            checks[6].status = "ok" if reachable else "warn"
            checks[6].detail = detail

    # GitHub token for `relay pr`. Missing is a warning, not a failure, since
    # `relay pr` is an optional part of the workflow.
    if github_token():
        checks[7].status = "ok"
        checks[7].detail = "GITHUB_TOKEN is set"
    else:
        checks[7].status = "warn"
        checks[7].detail = "GITHUB_TOKEN is not set; `relay pr` cannot open pull requests"

    # ---- report -----------------------------------------------------------
    print(f"[relay doctor] Relay {__version__} - {chosen} provider")
    print()
    width = max(len(c.name) for c in checks) + 2
    for c in checks:
        mark = _MARKS[c.status]
        print(f"  {c.name:<{width}}{mark:<7}{c.detail}")

    counts = {"ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        if c.status in counts:
            counts[c.status] += 1
    verdict = "all good" if counts["fail"] == 0 else f"{counts['fail']} issue(s) need fixing"
    print()
    print(
        f"  {counts['ok']} pass, {counts['warn']} warn, {counts['fail']} fail - {verdict}."
    )
    return 0 if counts["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(run_doctor())
