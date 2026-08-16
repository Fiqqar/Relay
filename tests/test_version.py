"""Guardrail for the release pipeline: the declared package version must always
match the version Relay reports at runtime (``relay --version``), and the
packaged distribution channels (Homebrew / Scoop) must track it too — so a
bump in ``pyproject.toml`` can never be shipped without the matching
``__version__`` or without the manifests pointing at that version's assets
(``RELEASE.md`` step 1b).
"""
import json
import re
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


def test_scoop_manifest_tracks_version():
    """The Scoop manifest must point at the current release's wheel, and its
    installer must reference the wheel by ``$version`` (never a literal), so
    ``scoop update`` / autoupdate keeps working on the next release without a
    manual edit ("no manual version bump anywhere")."""
    manifest = json.loads((_REPO_ROOT / "bucket" / "relay.json").read_text("utf-8"))
    assert manifest["version"] == __version__
    wheel = f"relay_cli-{__version__}-py3-none-any.whl"
    assert manifest["url"].endswith(f"v{__version__}/{wheel}")
    assert manifest["hash"].startswith("sha256:")
    assert manifest["autoupdate"]["url"] == (
        "https://github.com/Fiqqar/Relay/releases/download/"
        "v$version/relay_cli-$version-py3-none-any.whl"
    )
    installer = "\n".join(manifest["installer"]["script"])
    assert "$version" in installer
    assert __version__ not in installer


def test_homebrew_formula_tracks_version():
    """The Homebrew formula must point at the current release's sdist."""
    formula = (_REPO_ROOT / "Formula" / "relay.rb").read_text("utf-8")
    assert f"v{__version__}/relay_cli-{__version__}.tar.gz" in formula
    assert re.search(r'sha256 "[0-9a-f]{64}"', formula)
