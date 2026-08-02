"""Central error taxonomy.

Every exception in the app inherits from RelayError so the CLI layer has a
single place to turn failures into actionable messages and process exit codes.
"""


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
