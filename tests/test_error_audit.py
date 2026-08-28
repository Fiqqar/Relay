"""NFR-7 audit: every user-facing workflow error carries an actionable next step.

The CLI turns a ``RelayError`` into ``[relay] error: <message>`` and exits, so
the message is the ONLY guidance the developer gets. This test statically
scans every ``raise <Error>(...)`` site under ``relay/`` and requires the
message to reference an exact command/flag (a backtick or ``--``) or an
imperative verb. Anything else is a workflow error that dead-ends without a
next step.

``AIError`` and ``UserAbort`` are exempt by design:

* ``AIError.kind`` drives the fallback logic — the actionable path for an AI
  failure is the manual-input fallback, not the message text.
* ``UserAbort`` is the user's own deliberate choice to stop; exit 130 already
  tells the story.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import relay.errors as errors_mod

# A message passes if it references an exact command/flag (a backtick or
# ``--``) or contains one of these imperative verbs as a whole word. This is
# a guard rail, not a style judge: the point is that no workflow error leaves
# the developer without an explicit next step (NFR-7).
_ACTION_PUNCTUATION = ("`", "--")
_ACTION_VERBS = (
    "run",
    "use",
    "try",
    "pass",
    "see",
    "check",
    "pick",
    "choose",
    "install",
    "export",
    "set",
    "make",
    "add",
    "create",
    "commit",
    "push",
    "pull",
    "reset",
    "update",
    "wait",
    "retry",
    "re-run",
    "fix",
    "start",
    "stop",
    "delete",
    "fetch",
    "unstage",
    "open",
    "edit",
    "write",
    "configure",
)
_VERB_PATTERNS = [re.compile(rf"\b{re.escape(verb)}\b") for verb in _ACTION_VERBS]


def _audited_error_names() -> set[str]:
    """Names of RelayError subclasses the audit enforces (from errors.py)."""
    names = set()
    for name, cls in vars(errors_mod).items():
        if (
            isinstance(cls, type)
            and issubclass(cls, errors_mod.RelayError)
            and name not in {"AIError", "UserAbort"}
        ):
            names.add(name)
    return names


def _static_message(arg: ast.expr) -> str | None:
    """Static text of a message argument (None when it is not a literal).

    f-strings contribute their literal parts and drop the ``{expr}`` slots,
    so ``f"run --count {total}"`` audits as ``"run --count "``.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr):
        parts = [
            value.value
            for value in arg.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
        return "".join(parts)
    return None


def _raise_sites():
    """Yield ``(path, lineno, error_name, static_message)`` for every audited raise."""
    audited = _audited_error_names()
    root = Path(__file__).resolve().parents[1] / "relay"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            name = ast.unparse(node.exc.func).rsplit(".", 1)[-1]
            if name not in audited or not node.exc.args:
                continue
            message = _static_message(node.exc.args[0])
            if message is None:
                continue
            yield path, node.lineno, name, message


def _is_actionable(message: str) -> bool:
    lower = message.lower()
    if any(punctuation in lower for punctuation in _ACTION_PUNCTUATION):
        return True
    return any(pattern.search(lower) for pattern in _VERB_PATTERNS)


def test_every_workflow_error_is_actionable():
    offenders = [
        (path, lineno, name, message)
        for path, lineno, name, message in _raise_sites()
        if not _is_actionable(message)
    ]
    assert not offenders, (
        "workflow errors without an actionable next step (NFR-7) — add an "
        "exact command/flag or an imperative next action to each:\n"
        + "\n".join(
            f"  {path.relative_to(Path(__file__).resolve().parents[1])}:"
            f"{lineno} {name}: {message!r}"
            for path, lineno, name, message in offenders
        )
    )


def test_audit_actually_scans_sites():
    """Sanity: the audit is not vacuously green — it sees a real taxonomy."""
    sites = list(_raise_sites())
    assert len(sites) >= 10
    names = {name for _, _, name, _ in sites}
    assert {"ConfigError", "GitError", "ProtectedBranchError", "RelayError"} <= names


def test_sanitize_terminal_strips_ansi():
    from relay.errors import sanitize_terminal

    assert sanitize_terminal("\x1b[31mred\x1b[0m") == "red"
    assert "\x1b" not in sanitize_terminal("\x1b]0;title\x07hello")
    assert sanitize_terminal("normal") == "normal"
    assert "\x1b" not in sanitize_terminal("\x1b[2J\x1b[H exploit")
