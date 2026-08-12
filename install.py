#!/usr/bin/env python3
"""Cross-platform installer for Relay. Pure stdlib only (no pip deps).

What it does
------------
1. Verifies the prerequisites: Python 3.10+ and `git` on PATH.
2. Installs Relay as a user-level editable package:
       <python> -m pip install --user -e .
   If the --user install fails (e.g. an externally-managed environment), it
   retries once without --user.
3. Locates the directory where pip dropped the `relay` console script
   (sysconfig's user "scripts" dir) and, if it isn't already there, adds it
   to the *user* PATH:
       Windows -> PowerShell [Environment]::SetEnvironmentVariable(...,'User')
       Unix    -> appends `export PATH=...:$PATH` to ~/.bashrc / ~/.zshrc
   Changes are written to the persistent profile, not just the current shell,
   so `relay` is available in every new terminal.

Usage
-----
    python install.py           # interactive (asks before touching PATH)
    python install.py --yes     # accept all prompts
    python install.py --no-path # install but leave PATH alone
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

MIN_PYTHON = (3, 10)
REPO_ROOT = Path(__file__).resolve().parent


def _cmd(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(args)}")
    return subprocess.run(args, **kwargs)


def _ok(text: str) -> None:
    print(f"  [ok]   {text}")


def _warn(text: str) -> None:
    print(f"  [warn] {text}")


def _fail(text: str) -> None:
    print(f"  [fail] {text}")


def check_python() -> bool:
    print("\nChecking prerequisites ...")
    if sys.version_info < MIN_PYTHON:
        _fail(
            f"Python {sys.version_info.major}.{sys.version_info.minor} found, "
            f"but Relay needs 3.{MIN_PYTHON[1]}+."
        )
        return False
    _ok(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return True


def check_git() -> bool:
    git = shutil.which("git")
    if not git:
        _fail("git was not found on PATH.")
        _hint_git()
        return False
    _ok(f"git at {git}")
    return True


def _hint_git() -> None:
    if sys.platform.startswith("win"):
        print("       Install Git for Windows: https://git-scm.com/download/win")
    elif sys.platform == "darwin":
        print("       Install via Homebrew:  brew install git")
    else:
        print("       Install via your package manager, e.g.  sudo apt install git")


def check_pip() -> bool:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True,
        )
    except OSError:
        proc = None
    if proc is None or proc.returncode != 0:
        _fail("pip is not available for this Python.")
        print("       Bootstrapping pip with ensurepip ...")
        boot = subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            capture_output=True, text=True,
        )
        if boot.returncode != 0:
            _fail(f"ensurepip failed: {boot.stderr.strip()}")
            return False
    _ok(f"pip: {proc.stdout.splitlines()[0].strip()}" if proc and proc.returncode == 0 else "pip ready")
    return True


def install_package() -> bool:
    """pip-install the project from REPO_ROOT, preferring --user."""
    print("\nInstalling Relay ...")
    for user in (True, False):
        args = [sys.executable, "-m", "pip", "install"]
        if user:
            args.append("--user")
        args += ["-e", str(REPO_ROOT)]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode == 0:
            _ok(f"installed editable package ({'--user' if user else 'default'})")
            return True
        if user:
            _warn(f"--user install failed ({proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'unknown reason'})")
            _warn("retrying without --user ...")
        else:
            _fail("pip install failed.")
            print(proc.stderr)
    return False


def scripts_dir() -> Path:
    """Where pip places console scripts for the user install scheme."""
    scheme = "nt_user" if os.name == "nt" else "posix_user"
    return Path(sysconfig.get_path("scripts", scheme))


def _powershell(script: str) -> str:
    """Run a PowerShell one-liner, returning its trimmed stdout (or '' on error)."""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def update_path_windows(scripts: Path, yes: bool) -> bool:
    target = str(scripts)
    user_path = _powershell(
        "[Environment]::GetEnvironmentVariable('Path','User')"
    )

    entries = [p for p in user_path.split(";") if p]
    if target.lower() in [p.lower().rstrip("\\") for p in entries]:
        _ok(f"PATH already contains {target}")
        return True

    if not yes:
        answer = input(f"\nAdd {target} to your user PATH? [Y/n] ").strip().lower()
        if answer and answer not in ("y", "yes"):
            print("  Skipping PATH update. Run `relay doctor` for a reminder.")
            return True
    script = (
        f"[Environment]::SetEnvironmentVariable('Path', "
        f"[Environment]::GetEnvironmentVariable('Path','User') + ';{target}', 'User')"
    )
    if _powershell(script) == "" and not user_path:
        _warn("could not update user PATH (PowerShell unavailable or denied).")
        _warn(f'add it manually:  setx PATH "%PATH%;{target}"')
        return True
    _ok(f"added {target} to your user PATH")
    print("       New terminals will find `relay`; this one won't until restarted.")
    return True


def update_path_unix(scripts: Path, yes: bool) -> bool:
    target = str(scripts)
    home = Path.home()
    profiles = ["~/.bashrc", "~/.zshrc", "~/.profile"]
    candidates = []
    for p in profiles:
        path = home / p.replace("~/", "")
        if path.exists():
            candidates.append(path)
    if not candidates:
        candidates.append(home / ".profile")

    line = f'export PATH="{target}:$PATH"'
    for profile in candidates:
        text = profile.read_text(encoding="utf-8", errors="replace")
        if line in text:
            _ok(f"{target} already in {profile}")
            return True
    if not yes:
        answer = input(f"\nAppend '{line}' to {candidates[0]}? [Y/n] ").strip().lower()
        if answer and answer not in ("y", "yes"):
            print("  Skipping PATH update. Run `relay doctor` for a reminder.")
            return True
    with candidates[0].open("a", encoding="utf-8") as fh:
        fh.write(f"\n# added by Relay installer\n{line}\n")
    _ok(f"appended to {candidates[0]}")
    print("       Run `source " + str(candidates[0]) + "` in current shells.")
    return True


def update_path(scripts: Path, yes: bool) -> bool:
    print("\nWiring `relay` into your PATH ...")
    if os.name == "nt":
        return update_path_windows(scripts, yes)
    return update_path_unix(scripts, yes)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install Relay (editable, user-level) and put `relay` on your PATH.",
    )
    parser.add_argument("--yes", action="store_true", help="accept all prompts")
    parser.add_argument("--no-path", action="store_true", help="install but do not touch PATH")
    args = parser.parse_args()

    print(f"Relay installer (Python {sys.version.split()[0]})")
    if not (check_python() and check_git() and check_pip()):
        return 1
    if not install_package():
        return 1

    scripts = scripts_dir()
    if args.no_path:
        print("\nSkipping PATH update (--no-path).")
        print(f"  `relay` was installed into: {scripts}")
    else:
        update_path(scripts, args.yes)

    print("\nDone. Next steps:")
    print("  1. Open a NEW terminal, then run:  relay doctor")
    print("  2. Set your AI key once (if provider is gemini):")
    print("     Windows cmd:    set GEMINI_API_KEY=your_key")
    print("     PowerShell:     $env:GEMINI_API_KEY=\"your_key\"")
    print("     macOS/Linux:    export GEMINI_API_KEY=your_key")
    print("  3. In a git repository:  git add . && relay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
