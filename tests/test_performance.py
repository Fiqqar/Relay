"""Performance benchmarks and timing harness for NFR-1.

NFR-1 target: sub-500 ms CLI overhead excluding LLM network latency.
These tests verify that parser initialization, config resolution, and preflight
execution execute well within the performance budget (typically < 50 ms).
"""
import time
from unittest import mock

from relay.cli import build_parser
from relay.config import (
    anthropic_model,
    branch_template,
    gemini_model,
    max_diff_lines,
    ollama_model,
    openai_model,
    protected_branches,
    provider_from_env,
    repos,
    trusted_gitlab_hosts,
)
from relay.orchestrator import Orchestrator


def test_cli_parser_init_latency():
    """Parser construction must be instantaneous (< 20 ms)."""
    start = time.perf_counter()
    for _ in range(50):
        parser = build_parser()
        assert parser.prog == "relay"
    elapsed = (time.perf_counter() - start) / 50
    assert elapsed < 0.02, f"Parser init took {elapsed*1000:.2f} ms (budget 20 ms)"


def test_config_resolution_latency():
    """Resolving all configuration settings must complete in < 20 ms."""
    start = time.perf_counter()
    for _ in range(50):
        _ = provider_from_env()
        _ = gemini_model()
        _ = ollama_model()
        _ = openai_model()
        _ = anthropic_model()
        _ = branch_template()
        _ = max_diff_lines()
        _ = protected_branches()
        _ = trusted_gitlab_hosts()
        _ = repos()
    elapsed = (time.perf_counter() - start) / 50
    assert elapsed < 0.02, f"Config resolution took {elapsed*1000:.2f} ms (budget 20 ms)"


def test_preflight_check_latency_hermetic():
    """Preflight check on mock git must execute in < 50 ms."""
    git = mock.Mock()
    git.is_repo.return_value = True
    git.has_changes.return_value = True
    git.has_remote.return_value = True

    orch = Orchestrator(git=git, dry_run=True, yes=True)

    start = time.perf_counter()
    for _ in range(50):
        code = orch._preflight()
        assert code is None
    elapsed = (time.perf_counter() - start) / 50
    assert elapsed < 0.05, f"Preflight took {elapsed*1000:.2f} ms (budget 50 ms)"
