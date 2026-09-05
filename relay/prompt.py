"""Interactive confirmation menu for AI-generated commit messages.

The Accept/Edit/Retry/Abort key mapping lives here so it can be unit-tested in
isolation. Case-sensitivity is deliberate: the raw input is matched BEFORE any
lowercasing, so ``a`` (Accept) and ``A`` (Abort) can never collide. Pressing
Enter aborts — matching the capitalized ``A`` that marks Abort as the default
choice — because a bare ``choice.lower()`` would turn Shift+A into Accept and
accidentally commit & push.

This module also owns the other two user-interaction helpers: ``open_in_editor``
(Edit an AI/manual draft in the developer's editor) and ``manual_input`` (the
offline fallback prompt). They live here instead of the Orchestrator so the
workflow driver stays a thin state machine and the prompting logic can be
tested without building an Orchestrator.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING

from .errors import UserAbort

if TYPE_CHECKING:
    from .git_manager import GitManager

CONFIRM_PROMPT = "[Accept] [Edit] [Retry] [Abort] (a/e/r/A): "

# Actions returned by interpret_choice().
ACCEPT = "accept"
EDIT = "edit"
RETRY = "retry"
ABORT = "abort"


def interpret_choice(raw: str) -> str:
    """Map a raw menu response to ``accept | edit | retry | abort``.

    * ``a``, ``y``, ``accept``, ``yes`` -> accept
    * ``e``, ``edit``                -> edit
    * ``r``, ``retry``               -> retry
    * ``A``, ``q``, ``c``, ``abort``, ``cancel``, Enter, or anything else -> abort

    Single letters are matched against the raw input (no lowercasing), so ``a``
    accepts while ``A`` aborts. Full words are matched case-insensitively for
    convenience. Unrecognized input aborts rather than committing by accident.
    """
    choice = raw.strip()
    if not choice:
        return ABORT
    if choice == "a" or choice.lower() in ("accept", "y", "yes"):
        return ACCEPT
    if choice == "A" or choice.lower() in ("abort", "cancel", "q", "c"):
        return ABORT
    if choice.lower() in ("edit", "e"):
        return EDIT
    if choice.lower() in ("retry", "r"):
        return RETRY
    return ABORT


def open_in_editor(draft: str = "", git: GitManager | None = None) -> str | None:
    """Open configured editor with the draft commit message in a temporary file.

    Editor resolution precedence:
    1. $GIT_EDITOR
    2. git config core.editor (via the ``git`` manager, when given)
    3. $VISUAL
    4. $EDITOR
    5. Default: notepad (Windows) / nano (Unix)

    Returns the edited content if saved and non-empty, or None if the editor
    is unavailable, exits with an error, or the terminal is not interactive.
    """
    if not sys.stdin.isatty():
        return None

    git_editor_cfg = ""
    if git is not None:
        try:
            cfg = git.config_get("core.editor")
            if isinstance(cfg, str) and cfg.strip():
                git_editor_cfg = cfg.strip()
        except Exception:
            pass

    raw_editor = (
        os.environ.get("GIT_EDITOR")
        or git_editor_cfg
        or os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
    )
    editor = raw_editor.strip() if isinstance(raw_editor, str) else ""
    if not editor:
        editor = "notepad" if sys.platform == "win32" else "nano"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".commit.txt", delete=False, encoding="utf-8"
        ) as tmp:
            if draft:
                tmp.write(draft)
            tmp_path = tmp.name

        if sys.platform == "win32":
            if os.path.isfile(editor):
                cmd = [editor, tmp_path]
            else:
                cmd = [a.strip('"') for a in shlex.split(editor, posix=False)] + [tmp_path]
        else:
            cmd = shlex.split(editor) + [tmp_path]

        ret = subprocess.run(cmd, check=False)
        if ret.returncode == 0 and os.path.exists(tmp_path):
            with open(tmp_path, encoding="utf-8") as f:
                content = f.read().strip()
            return content or None
        return None
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def manual_input(draft: str = "") -> str:
    """The fallback manual input prompt.

    Supports multi-paragraph Conventional Commits:
    - Press Enter on an empty line to finish.
    - Enter '.' on an empty line to insert a paragraph separator.
    - Ctrl-C or empty answer aborts.
    """
    print("Enter your commit message (subject, then optional body;")
    print("blank line to finish, '.' for paragraph break, Ctrl-C to abort):")
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except (EOFError, StopIteration):
            break
        stripped = line.strip()
        if stripped == ".":
            lines.append("")
        elif not stripped:
            break
        else:
            lines.append(line.rstrip())
    message = "\n".join(lines).strip()
    if not message and draft:
        message = draft.strip()
    if not message:
        raise UserAbort("aborted - no commit message provided")
    first, _, rest = message.partition("\n")
    if rest:
        rest = rest.lstrip("\n")
        return f"{first}\n\n{rest}"
    return message


__all__ = [
    "ABORT",
    "ACCEPT",
    "CONFIRM_PROMPT",
    "EDIT",
    "RETRY",
    "interpret_choice",
    "manual_input",
    "open_in_editor",
]
