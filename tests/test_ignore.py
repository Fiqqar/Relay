"""Tests for AI diff ignore paths — [relay.ignore] + RELAY_IGNORE_PATHS."""
import textwrap
from unittest import mock

import pytest

from relay import config
from relay.ai.base import filter_ignored_diff, filter_ignored_stat


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    config._RAW_CACHE.clear()
    for k in ("RELAY_IGNORE_PATHS", "RELAY_CONFIG", "XDG_CONFIG_HOME", "APPDATA"):
        monkeypatch.delenv(k, raising=False)


def _write(monkeypatch, tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setenv("RELAY_CONFIG", str(p))


# ---- config: ignore_paths -------------------------------------------------

def test_ignore_paths_defaults_to_empty():
    assert config.ignore_paths() == []


def test_ignore_paths_env_comma_split(monkeypatch):
    monkeypatch.setenv("RELAY_IGNORE_PATHS", "package-lock.json, dist/*, *.min.js")
    assert config.ignore_paths() == ["package-lock.json", "dist/*", "*.min.js"]


def test_ignore_paths_env_strips_and_drops_empty(monkeypatch):
    monkeypatch.setenv("RELAY_IGNORE_PATHS", " a.py , , b.py ")
    assert config.ignore_paths() == ["a.py", "b.py"]


def test_ignore_paths_env_beats_file(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [relay.ignore]
        paths = ["from-file.txt"]
    """)
    monkeypatch.setenv("RELAY_IGNORE_PATHS", "from-env.txt")
    assert config.ignore_paths() == ["from-env.txt"]


def test_ignore_paths_read_from_file(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [relay.ignore]
        paths = ["dist/*", "*.lock"]
    """)
    assert config.ignore_paths() == ["dist/*", "*.lock"]


def test_ignore_paths_empty_file_falls_back(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [relay.ignore]
        paths = []
    """)
    assert config.ignore_paths() == []


def test_ignore_paths_empty_env_falls_back(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [relay.ignore]
        paths = ["keep.txt"]
    """)
    monkeypatch.setenv("RELAY_IGNORE_PATHS", "   ")
    assert config.ignore_paths() == ["keep.txt"]


def test_ignore_paths_file_with_spaces_stripped(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, """
        [relay.ignore]
        paths = ["  dist/*  ", "  a.py"]
    """)
    assert config.ignore_paths() == ["dist/*", "a.py"]


# ---- filter helpers --------------------------------------------------------

SAMPLE_DIFF_TWO_FILES = """diff --git a/app.py b/app.py
index abc..def 100644
--- a/app.py
+++ b/app.py
@@ -0,0 +1 @@
+print("hello")
diff --git a/package-lock.json b/package-lock.json
index 123..456 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -0,0 +1 @@
+{"lock": true}
diff --git a/dist/bundle.js b/dist/bundle.js
index 111..222 100644
--- a/dist/bundle.js
+++ b/dist/bundle.js
@@ -0,0 +1 @@
+bundle content
"""

SAMPLE_STAT = """ app.py | 1 +
 package-lock.json | 1 +
 dist/bundle.js | 1 +
 3 files changed, 3 insertions(+)
"""


def test_filter_diff_no_patterns_returns_original():
    assert filter_ignored_diff(SAMPLE_DIFF_TWO_FILES, []) == SAMPLE_DIFF_TWO_FILES
    assert filter_ignored_stat(SAMPLE_STAT, []) == SAMPLE_STAT


def test_filter_diff_empty_diff_returns_empty():
    assert filter_ignored_diff("", ["*.py"]) == ""
    assert filter_ignored_stat("", ["*.py"]) == ""


def test_filter_diff_removes_single_pattern():
    out = filter_ignored_diff(SAMPLE_DIFF_TWO_FILES, ["package-lock.json"])
    assert "package-lock.json" not in out
    assert "app.py" in out
    assert "dist/bundle.js" in out


def test_filter_diff_glob_basename():
    # *.lock does not match package-lock.json; *.json should
    out2 = filter_ignored_diff(SAMPLE_DIFF_TWO_FILES, ["*.json"])
    assert "package-lock.json" not in out2
    assert "app.py" in out2


def test_filter_diff_dist_wildcard():
    out = filter_ignored_diff(SAMPLE_DIFF_TWO_FILES, ["dist/*"])
    assert "dist/bundle.js" not in out
    assert "app.py" in out
    assert "package-lock.json" in out


def test_filter_diff_multiple_patterns():
    out = filter_ignored_diff(SAMPLE_DIFF_TWO_FILES, ["package-lock.json", "dist/*"])
    assert "package-lock.json" not in out
    assert "dist/bundle.js" not in out
    assert "app.py" in out


def test_filter_stat_removes_matching():
    out = filter_ignored_stat(SAMPLE_STAT, ["package-lock.json"])
    assert "package-lock.json" not in out
    assert "app.py" in out


def test_filter_stat_dist_pattern():
    out = filter_ignored_stat(SAMPLE_STAT, ["dist/*"])
    assert "dist/bundle.js" not in out
    assert "app.py" in out


def test_filter_stat_all_ignored_removes_file_lines():
    out = filter_ignored_stat(SAMPLE_STAT, ["*.py", "*.json", "dist/*"])
    assert "app.py" not in out
    assert "package-lock.json" not in out
    assert "dist/bundle.js" not in out


# ---- orchestrator integration ---------------------------------------------

class StubAI:
    def __init__(self):
        self.calls = []

    def generate(self, diff, stat, branch):
        self.calls.append((diff, stat, branch))
        return "feat: stub"


def _make_git(diff=SAMPLE_DIFF_TWO_FILES, stat=SAMPLE_STAT):
    g = mock.Mock()
    g.is_repo.return_value = True
    g.has_changes.return_value = True
    g.has_remote.return_value = True
    g.staged_diff.return_value = diff
    g.staged_stat.return_value = stat
    g.head_diff.return_value = diff
    g.head_stat.return_value = stat
    g.current_branch.return_value = "main"
    g.staged_diff_binary_only.return_value = False
    g.head_diff_binary_only.return_value = False
    g.write_tree.return_value = "abc"
    return g


def test_orchestrator_filters_ignore_before_ai(monkeypatch):
    from relay.orchestrator import Orchestrator

    monkeypatch.setenv("RELAY_IGNORE_PATHS", "package-lock.json")
    ai = StubAI()
    git = _make_git()
    orch = Orchestrator(git=git, provider=ai, yes=True, no_push=True)
    orch.run()
    assert ai.calls
    diff_sent = ai.calls[0][0]
    assert "package-lock.json" not in diff_sent
    assert "app.py" in diff_sent
    git.commit.assert_called_once()


def test_orchestrator_all_ignored_falls_back_to_manual(monkeypatch):
    from relay.orchestrator import Orchestrator

    monkeypatch.setenv("RELAY_IGNORE_PATHS", "app.py,package-lock.json,dist/*")
    ai = StubAI()
    git = _make_git()
    # All files ignored -> AI diff empty -> manual fallback (mock input)
    with mock.patch("builtins.input", side_effect=["feat: manual after ignore", ""]):
        orch = Orchestrator(git=git, provider=ai, yes=False, no_push=True)
        orch.run()
    assert ai.calls == []  # AI should not be called when filtered diff empty
    git.commit.assert_called_once_with("feat: manual after ignore", no_verify=False)


def test_orchestrator_no_ignore_passes_full_diff(monkeypatch):
    from relay.orchestrator import Orchestrator

    ai = StubAI()
    git = _make_git()
    orch = Orchestrator(git=git, provider=ai, yes=True, no_push=True)
    orch.run()
    diff_sent = ai.calls[0][0]
    assert "app.py" in diff_sent
    assert "package-lock.json" in diff_sent
