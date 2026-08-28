"""Central error taxonomy.

Every exception in the app inherits from RelayError so the CLI layer has a
single place to turn failures into actionable messages and process exit codes.
"""
import re as _re


class RelayError(Exception):
    """Base class for all Relay errors. The message is user-facing."""


class ConfigError(RelayError):
    """Bad configuration: missing API key, unknown provider, invalid template."""


class GitError(RelayError):
    """A git command failed. Carries the underlying stderr for debugging."""

    def __init__(self, message: str, command: str = "", stderr: str = ""):
        super().__init__(message)
        self.command = command
        self.stderr = stderr


class AIError(RelayError):
    """An AI provider failed. `kind` lets the fallback logic decide how to react.

    Kinds: unavailable | timeout | rate_limited | bad_response | api_error | unexpected
    """

    def __init__(self, provider: str, kind: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.kind = kind


class UserAbort(RelayError):
    """The user chose to abort (Ctrl-C or the abort prompt). Maps to exit 130."""


class ProtectedBranchError(RelayError):
    """The workflow was refused because it targets a protected branch
    (default-branch safety). Maps to exit 1 like any other workflow error."""


# ANSI escape stripping for terminal output (log injection hardening)
_ANSI_RE = _re.compile(r"\x1b(?:\].*?\x07|[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def sanitize_terminal(text: str) -> str:
    """Strip ANSI/control sequences from external text before printing."""
    # Also strip other control chars that could affect terminal
    text = _ANSI_RE.sub("", text)
    # Remove remaining C0 control chars except newline/tab
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
