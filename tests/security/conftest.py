"""Shared fixtures for the adversarial security regression suite.

Unlike the functional suite (which mocks ``subprocess`` everywhere), these
tests execute REAL git binaries inside throwaway repositories under ``tmp_path``
so shell/option-injection payloads face the actual code path — including the
real ``git`` argument parser on the other end.
"""
import pytest
from sechelp import init_repo

from relay.git_manager import GitManager


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one committed file, ready for adversarial input."""
    init_repo(tmp_path)
    return tmp_path


@pytest.fixture
def git(repo):
    """A real GitManager pointed at the throwaway repo (no mocks)."""
    return GitManager(cwd=str(repo), verbose=False)
