"""relay doctor — a self-diagnostic for a Relay installation.

Runs a battery of read-only checks against the local environment and prints a
pass/warn/fail report. Exits 0 when nothing is broken, 1 when a fix is needed,
so it composes cleanly with installers and CI smoke tests.

Pure stdlib only, matching the zero-dependency philosophy of the rest of the
tool. Every check degrades gracefully and never raises.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import __version__
from .bitbucket import bitbucket_token
from .config import (
    DEFAULT_OLLAMA_BASE_URL,
    anthropic_api_key,
    anthropic_base_url,
    gemini_api_key,
    groq_api_key,
    groq_base_url,
    mistral_api_key,
    mistral_base_url,
    ollama_base_url,
    openai_api_key,
    openai_base_url,
    protected_branches,
    provider_from_env,
    xai_api_key,
    xai_base_url,
)
from .errors import sanitize_terminal
from .git_manager import GitManager
from .github import github_token
from .gitlab import gitlab_token
from .protected import is_protected

_MARKS = {"ok": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}

# Cap on a probe response body. A `/user` payload is a few hundred bytes;
# anything near this is a misbehaving endpoint, matching the 10 KiB
# diagnostic cap used by the AI providers and forge clients.
_MAX_PROBE_BODY_BYTES = 10 * 1024


# Keyed providers share one credential-check shape: a display label, the
# name of a zero-arg key reader (resolved late via globals() so
# mock.patch("relay.doctor.<name>_api_key") keeps working in tests), and
# the env var named in the user-facing message. Ollama stays special-cased
# (reachability probe, no key); unknown names fall through to the warn
# branch in run_doctor.
_KEYED_PROVIDERS: dict[str, tuple[str, str, str]] = {
    "gemini": ("Gemini API", "gemini_api_key", "GEMINI_API_KEY"),
    "openai": ("OpenAI-compatible API", "openai_api_key", "OPENAI_API_KEY"),
    "anthropic": ("Anthropic API", "anthropic_api_key", "ANTHROPIC_API_KEY"),
    "mistral": ("Mistral API", "mistral_api_key", "MISTRAL_API_KEY"),
    "groq": ("Groq API", "groq_api_key", "GROQ_API_KEY"),
    "xai": ("xAI API", "xai_api_key", "XAI_API_KEY"),
}


def _apply_keyed_provider_credential(chosen: str, checks: list[Check]) -> bool:
    """Fill checks[5]/checks[6] from _KEYED_PROVIDERS. True when handled."""
    entry = _KEYED_PROVIDERS.get(chosen)
    if entry is None:
        return False
    label, key_attr, env = entry
    key_fn: Callable[[], str | None] = globals()[key_attr]
    checks[5].detail = label
    if key_fn():
        checks[6].status = "ok"
        checks[6].detail = f"{env} is set"
    else:
        checks[6].status = "fail"
        checks[6].detail = f"{env} is not set; see `relay --help`"
    return True


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
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return False, f"cannot parse URL: {url}"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # Strip brackets for IPv6 literals for socket API
        host = host.strip("[]")
    except (IndexError, ValueError) as exc:
        return False, f"cannot parse URL: {url} ({exc})"
    try:
        with socket.create_connection((host, port), timeout=1):
            return True, f"reachable at {url}"
    except OSError as exc:
        return False, f"not reachable at {url} ({exc})"


def _probe_provider(chosen: str) -> Check:
    start = time.perf_counter()
    timeout = 5
    req: urllib.request.Request | None = None
    if chosen == "gemini":
        key = gemini_api_key()
        if not key:
            return Check("AI probe", "skip", "GEMINI_API_KEY is not set")
        headers = {"User-Agent": "relay-cli"}
        if key.startswith("AQ."):
            headers["Authorization"] = f"Bearer {key}"
        else:
            headers["X-Goog-Api-Key"] = key
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
            headers=headers,
        )
    elif chosen in ("openai", "groq", "mistral", "xai"):
        if chosen == "openai":
            key, base = openai_api_key(), openai_base_url()
        elif chosen == "groq":
            key, base = groq_api_key(), groq_base_url()
        elif chosen == "mistral":
            key, base = mistral_api_key(), mistral_base_url()
        else:
            key, base = xai_api_key(), xai_base_url()
        if not key:
            return Check("AI probe", "skip", f"{chosen.upper()}_API_KEY is not set")
        req = urllib.request.Request(
            f"{base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}", "User-Agent": "relay-cli"},
        )
    elif chosen == "anthropic":
        key, base = anthropic_api_key(), anthropic_base_url()
        if not key:
            return Check("AI probe", "skip", "ANTHROPIC_API_KEY is not set")
        req = urllib.request.Request(
            f"{base.rstrip('/')}/models",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "User-Agent": "relay-cli",
            },
        )
    elif chosen == "ollama":
        base = ollama_base_url()
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/tags",
            headers={"User-Agent": "relay-cli"},
        )
    else:
        return Check("AI probe", "skip", f"unknown provider '{chosen}'")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as _:  # nosec B310
            elapsed = int((time.perf_counter() - start) * 1000)
            return Check("AI probe", "ok", f"authenticated ({elapsed}ms)")
    except urllib.error.HTTPError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return Check("AI probe", "fail", f"HTTP {exc.code} {exc.reason} ({elapsed}ms)")
    except Exception as exc:
        return Check("AI probe", "fail", f"connection failed ({exc})")


def _probe_forge_endpoint(
    *,
    label: str,
    token: str | None,
    url: str,
    headers: dict,
    user_field: str,
) -> Check | None:
    """Probe one forge token endpoint. None when no token is configured."""
    if not token:
        return None
    start = time.perf_counter()
    timeout = 5
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            elapsed = int((time.perf_counter() - start) * 1000)
            raw = resp.read(_MAX_PROBE_BODY_BYTES + 1)
            if len(raw) > _MAX_PROBE_BODY_BYTES:
                return Check("Forge probe", "fail", f"{label} response too large ({elapsed}ms)")
            body = json.loads(raw.decode("utf-8", "replace"))
            user = body.get(user_field) or "user"
            return Check("Forge probe", "ok", f"{label} @{user} ({elapsed}ms)")
    except urllib.error.HTTPError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return Check("Forge probe", "fail", f"{label} HTTP {exc.code} ({elapsed}ms)")
    except Exception as exc:
        return Check("Forge probe", "fail", f"{label} connection failed ({exc})")


def _probe_forge() -> Check | None:
    check = _probe_forge_endpoint(
        label="GitHub",
        token=github_token(),
        url="https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {github_token()}",
            "User-Agent": "relay-cli",
            "Accept": "application/vnd.github+json",
        },
        user_field="login",
    )
    if check is not None:
        return check
    check = _probe_forge_endpoint(
        label="GitLab",
        token=gitlab_token(),
        url="https://gitlab.com/api/v4/user",
        headers={"PRIVATE-TOKEN": gitlab_token(), "User-Agent": "relay-cli"},
        user_field="username",
    )
    if check is not None:
        return check
    return _probe_forge_endpoint(
        label="Bitbucket",
        token=bitbucket_token(),
        url="https://api.bitbucket.org/2.0/user",
        headers={
            "Authorization": f"Bearer {bitbucket_token()}",
            "User-Agent": "relay-cli",
        },
        user_field="username",
    )


def run_doctor(
    provider: str | None = None,
    probe: bool = False,
    verbose: bool = False,
) -> int:
    """Run all checks and print the report. Returns the exit code."""
    git = GitManager(verbose=verbose)
    chosen = (provider or provider_from_env()).lower()

    checks: list[Check] = [
        Check("Python 3.11+", "ok" if sys.version_info >= (3, 11) else "fail",
              f"{sys.version.split()[0]}"),
        Check("relay on PATH", "skip", ""),
        Check("git installed", "skip", ""),
        Check("inside a git repo", "skip", ""),
        Check("git identity", "skip", ""),
        Check(f"provider: {chosen}", "skip", ""),
        Check("AI credentials", "skip", ""),
        Check("Forge token", "skip", ""),
        Check("Protected branches", "skip", ""),
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
    if _apply_keyed_provider_credential(chosen, checks):
        pass
    elif chosen == "ollama":
        base = ollama_base_url()
        checks[5].detail = "Ollama"
        if base != DEFAULT_OLLAMA_BASE_URL:
            checks[5].detail = f"Ollama ({base})"
        reachable, detail = _ollama_reachable(base)
        checks[6].status = "ok" if reachable else "warn"
        checks[6].detail = detail
    else:
        checks[6].status = "warn"
        checks[6].detail = f"unknown provider '{chosen}' (expected gemini|ollama|openai|anthropic|mistral|groq|xai)"

    # Forge token for `relay pr`. Missing is a warning, not a failure, since
    # `relay pr` is an optional part of the workflow.
    if github_token():
        checks[7].status = "ok"
        checks[7].detail = "GITHUB_TOKEN is set"
    elif gitlab_token():
        checks[7].status = "ok"
        checks[7].detail = "GITLAB_TOKEN is set"
    elif bitbucket_token():
        checks[7].status = "ok"
        checks[7].detail = "BITBUCKET_TOKEN is set"
    else:
        checks[7].status = "warn"
        checks[7].detail = (
            "GITHUB_TOKEN / GITLAB_TOKEN / BITBUCKET_TOKEN is not set; `relay pr` cannot open PRs/MRs"
        )

    # Protected branches: report the configured default-branch safety rules and
    # warn when the current branch is itself protected (a risky state — team
    # mode would refuse, and solo mode would commit straight onto it).
    protected = protected_branches()
    current = git.current_branch() if git.is_repo() else ""
    checks[8].detail = ", ".join(protected) or "none"
    if current and is_protected(current, protected):
        checks[8].status = "warn"
        checks[8].detail = (
            f"{', '.join(protected)} — currently on protected branch '{current}'"
        )
    else:
        checks[8].status = "ok"

    if probe:
        checks.append(_probe_provider(chosen))
        forge_probe = _probe_forge()
        if forge_probe:
            checks.append(forge_probe)

    # ---- report -----------------------------------------------------------
    print(f"[relay doctor] Relay {__version__} - {chosen} provider")
    print()
    width = max(len(c.name) for c in checks) + 2
    for c in checks:
        mark = _MARKS[c.status]
        # Details can carry attacker-controlled text (git user.name/email
        # from a cloned repo's config) — strip terminal escapes like every
        # other user-facing print path does.
        print(f"  {sanitize_terminal(c.name):<{width}}{mark:<7}{sanitize_terminal(c.detail)}")

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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_doctor())
