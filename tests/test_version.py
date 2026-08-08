"""Guardrail for the release pipeline: the declared package version must always
match the version Relay reports at runtime (``relay --version``), so a bump in
``pyproject.toml`` can never be shipped without the matching ``__version__``."""
from pathlib import Path

from relay import __version__, toml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_version_is_not_empty():
    assert isinstance(__version__, str)
    assert __version__.strip()
    # PEP 440 shape, e.g. 0.1.0 or 1.2.3-rc1.
    parts = __version__.split(".")
    assert len(parts) == 3
    assert parts[0].isdigit() and parts[1].isdigit()


def test_version_matches_pyproject():
    pyproject = _REPO_ROOT / "pyproject.toml"
    data = toml.parse(pyproject.read_text("utf-8"))
    assert data["project"]["version"] == __version__