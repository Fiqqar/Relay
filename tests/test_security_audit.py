"""Static AST security audit tests for NFR-3.

NFR-3: Secrets are environment-only, never read from config files, never logged.
Subprocesses must always use shell=False and argv-as-list.
"""
from __future__ import annotations

from pathlib import Path

from relay.config import _CFG_KEYS, _ENV_ONLY

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_secrets_are_strictly_env_only():
    """All secret credential tokens and AI base URLs must be in _ENV_ONLY.

    A repo-local RELAY_CONFIG must never be able to define credentials or redirect
    credential-bearing requests (ADR-005).
    """
    required_secrets = {
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "OLLAMA_BASE_URL",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "MISTRAL_BASE_URL",
        "GROQ_BASE_URL",
        "XAI_BASE_URL",
    }
    assert required_secrets <= _ENV_ONLY

    # No secret key may appear in _CFG_KEYS (which maps env vars to config file keys)
    for secret in required_secrets:
        assert secret not in _CFG_KEYS, f"Secret {secret} must not be mapped to config file"


def test_subprocess_never_uses_shell_true():
    """ADR-002: All subprocess invocations must use argv lists and shell=False.

    Scans every AST Call node in relay/ to ensure shell=True is never passed.
    """
    import ast

    relay_root = _REPO_ROOT / "relay"
    for py_file in relay_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = ast.unparse(node.func)
                if any(
                    target in func_name
                    for target in (
                        "subprocess.run",
                        "subprocess.Popen",
                        "subprocess.check_call",
                        "subprocess.check_output",
                    )
                ):
                    for keyword in node.keywords:
                        if keyword.arg == "shell":
                            val = ast.unparse(keyword.value)
                            assert val in ("False", "0", "None"), (
                                f"Forbidden shell={val} found in {py_file.name}:{node.lineno}"
                            )


def test_ai_base_url_ssrf_validation():
    """Verify that _is_valid_ai_base_url rejects SSRF targets and non-HTTPS public URLs."""
    from relay.telemetry import _is_valid_ai_base_url

    # Allowed loopback HTTP
    assert _is_valid_ai_base_url("http://localhost:11434")
    assert _is_valid_ai_base_url("http://127.0.0.1:11434")
    assert _is_valid_ai_base_url("http://[::1]:11434")

    # Allowed public HTTPS
    assert _is_valid_ai_base_url("https://api.openai.com/v1")
    assert _is_valid_ai_base_url("https://api.anthropic.com/v1")

    # Rejected cleartext HTTP to public hosts
    assert not _is_valid_ai_base_url("http://api.openai.com/v1")

    # Rejected private / internal / metadata endpoints
    assert not _is_valid_ai_base_url("http://169.254.169.254/latest/meta-data")
    assert not _is_valid_ai_base_url("https://169.254.169.254/latest/meta-data")
    assert not _is_valid_ai_base_url("http://10.0.0.1:8080")
    assert not _is_valid_ai_base_url("https://192.168.1.1:8443")
    assert not _is_valid_ai_base_url("http://172.16.0.1:8080")


def test_telemetry_url_ssrf_validation():
    """Verify that telemetry URLs reject loopback/private/cleartext endpoints."""
    from relay.telemetry import _is_https

    assert _is_https("https://telemetry.example.com/api/v1")
    assert not _is_https("http://telemetry.example.com/api/v1")
    assert not _is_https("https://localhost:8080")
    assert not _is_https("https://127.0.0.1:8080")
    assert not _is_https("https://10.0.0.1:8080")
    assert not _is_https("https://169.254.169.254/api")


