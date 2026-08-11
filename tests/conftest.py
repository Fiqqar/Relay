"""Shared fixtures and helpers for the Relay test suite.

These fixtures are deliberately small and dependency-free (only pytest + the
stdlib), mirroring the zero-dependency philosophy of the tool itself.
"""
import subprocess

import pytest


@pytest.fixture
def make_proc():
    """Factory for a fake ``subprocess.CompletedProcess``.

    Lets tests simulate git's stdout/stderr/exit code without ever invoking a
    real ``git`` binary.
    """

    def _make(returncode: int = 0, stdout: str = "", stderr: str = ""):
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return _make


@pytest.fixture
def sample_diff() -> str:
    """A plausible ``git diff --cached`` output used in AI provider tests."""
    return (
        "diff --git a/app.py b/app.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,1 +1,5 @@\n"
        " import os\n"
        "+from datetime import datetime\n"
        "+\n"
        "+def now():\n"
        "+    return datetime.now()\n"
    )


@pytest.fixture
def sample_stat() -> str:
    """A plausible ``git diff --cached --stat`` summary."""
    return " app.py | 4 ++++\n 1 file changed, 4 insertions(+)\n"
