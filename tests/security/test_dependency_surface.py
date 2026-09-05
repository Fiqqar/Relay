"""Dependency-surface invariant tests: the zero-runtime-dependency promise,
enforced as code instead of folklore.

- ``pyproject.toml`` must keep ``dependencies = []`` (parsed with Relay's OWN
  TOML subset parser — the same one ``test_version.py`` relies on, so this
  also exercises the "single-line array" rule from WORKING_RULES).
- No module under ``relay/`` (and ``install.py``) may import anything that is
  neither stdlib (``sys.stdlib_module_names``, Python 3.10+) nor the ``relay``
  package itself / a relative import. A new third-party import fails here
  before it ever reaches review.
- No dynamic imports (``__import__`` / ``importlib``) that could smuggle a
  dependency past the static scan.
"""
import ast
import sys
from pathlib import Path

from relay.toml import parse as parse_toml

REPO_ROOT = Path(__file__).resolve().parents[2]
RELAY_ROOT = REPO_ROOT / "relay"


def test_pyproject_runtime_dependencies_stay_empty():
    """The zero-runtime-dependency promise, asserted programmatically."""
    data = parse_toml((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == [], (
        "runtime dependencies must stay empty (stdlib only); "
        "discuss first per WORKING_RULES rule 3"
    )


def _all_source_files():
    files = sorted(RELAY_ROOT.rglob("*.py"))
    files.append(REPO_ROOT / "install.py")
    return files


def _imported_top_levels(tree):
    """Yield (lineno, top-level module, is_relative) for every import node."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0], False
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield node.lineno, "<relative>", True
            elif node.module:
                yield node.lineno, node.module.split(".")[0], False


def test_no_non_stdlib_imports():
    """Every absolute import must be stdlib or the ``relay`` package itself."""
    stdlib = set(sys.stdlib_module_names)
    violations = []
    for path in _all_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, top, relative in _imported_top_levels(tree):
            if relative or top in ("relay",):
                continue
            if top not in stdlib:
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {top}")
    assert violations == [], f"non-stdlib imports slipped in: {violations}"


def test_no_dynamic_imports():
    """``__import__`` / ``importlib`` would bypass the static scan above."""
    violations = []
    for path in _all_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            func = None
            if isinstance(node, ast.Call):
                func = ast.unparse(node.func)
            if func in ("__import__", "importlib.import_module", "import_module"):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {func}")
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("importlib"):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: importlib")
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "importlib" for a in node.names):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: importlib")
    assert violations == [], f"dynamic imports slipped in: {violations}"
