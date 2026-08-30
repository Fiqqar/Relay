"""Custom hooks runner — pre_commit / post_push via TOML.

Hooks are explicit argv lists from ``[hooks.pre_commit]`` / ``[hooks.post_push]``
in the TOML config file. They run via ``subprocess.run(..., shell=False)`` so
a hook like ``["echo", "hi; rm -rf /"]`` still treats the semicolon as a
literal argument, never as a shell metacharacter.
"""
from __future__ import annotations

import subprocess

from .errors import GitError, sanitize_terminal

_HOOK_TIMEOUT = 60.0


def run_hook(argv: list[str], verbose: bool = False) -> None:
    """Run a hook argv. Raises GitError if it exits non-zero."""
    if not argv:
        return
    if verbose:
        print(f"[relay] $ {' '.join(argv)} (hook)")
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_HOOK_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"hook timed out after {_HOOK_TIMEOUT:.0f}s: {' '.join(argv)} — check the hook and retry",
            command=" ".join(argv),
        ) from exc
    except FileNotFoundError as exc:
        raise GitError(
            f"hook not found: {argv[0]} — install the hook or check `[hooks]` in config.toml",
            command=" ".join(argv),
        ) from exc
    if proc.returncode != 0:
        # Surface hook stdout/stderr via GitError.stderr so CLI can print it with --verbose
        err = (proc.stderr or proc.stdout or "").strip()
        raise GitError(
            f"hook failed (exit {proc.returncode}): {sanitize_terminal(' '.join(argv))} — check the hook output and fix the hook command",
            command=" ".join(argv),
            stderr=sanitize_terminal(err),
        )
