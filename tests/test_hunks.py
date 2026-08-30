"""Tests for hunk-level AI messages."""
from unittest import mock

from relay.ai.base import split_diff_by_file
from relay.cli import build_parser

SAMPLE_TWO_FILES = """diff --git a/a.py b/a.py
index 111..222 100644
--- a/a.py
+++ b/a.py
@@ -0,0 +1 @@
+print("a")
diff --git a/b.py b/b.py
index 333..444 100644
--- a/b.py
+++ b/b.py
@@ -0,0 +1 @@
+print("b")
"""

SAMPLE_ONE_FILE = """diff --git a/a.py b/a.py
index 111..222 100644
--- a/a.py
+++ b/a.py
@@ -0,0 +1 @@
+print("a")
"""


def test_split_diff_by_file_two():
    blocks = split_diff_by_file(SAMPLE_TWO_FILES)
    assert len(blocks) == 2
    assert blocks[0][0] == "a.py"
    assert "print(\"a\")" in blocks[0][1]
    assert blocks[1][0] == "b.py"


def test_split_diff_by_file_one():
    blocks = split_diff_by_file(SAMPLE_ONE_FILE)
    assert len(blocks) == 1
    assert blocks[0][0] == "a.py"


def test_split_empty_returns_empty():
    assert split_diff_by_file("") == []
    assert split_diff_by_file("no header") == [("", "no header")]


def test_cli_hunks_flag():
    assert build_parser().parse_args(["--hunks"]).hunks is True
    assert build_parser().parse_args([]).hunks is False
    assert build_parser().parse_args(["--solo", "--hunks"]).hunks is True


# ---- orchestrator hunks --------------------------------------------------

class StubAI:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, diff, stat, branch):
        self.calls.append((diff, stat, branch))
        if not self.responses:
            raise AssertionError("no more responses")
        val = self.responses.pop(0)
        if isinstance(val, Exception):
            raise val
        return val


def _make_git(diff=SAMPLE_TWO_FILES):
    g = mock.Mock()
    g.is_repo.return_value = True
    g.has_changes.return_value = True
    g.has_remote.return_value = True
    g.staged_diff.return_value = diff
    g.staged_stat.return_value = " a.py | 1 +\n b.py | 1 +\n"
    g.head_diff.return_value = diff
    g.head_stat.return_value = " a.py | 1 +\n"
    g.current_branch.return_value = "main"
    g.staged_diff_binary_only.return_value = False
    g.head_diff_binary_only.return_value = False
    g.write_tree.return_value = "abc"
    return g


def test_hunks_multi_file_combines_messages():
    from relay.orchestrator import Orchestrator

    ai = StubAI(["feat(a): add a", "fix(b): fix b"])
    git = _make_git(SAMPLE_TWO_FILES)
    orch = Orchestrator(git=git, provider=ai, yes=True, no_push=True, hunks=True)
    orch.run()
    # Two AI calls, one per file
    assert len(ai.calls) == 2
    assert "a.py" in ai.calls[0][0] or "a.py" in ai.calls[0][1]
    assert "b.py" in ai.calls[1][0] or "b.py" in ai.calls[1][1]
    # Final commit should be combined: subject from first + bullet for second
    msg = git.commit.call_args[0][0]
    assert msg.startswith("feat(a): add a")
    assert "fix(b): fix b" in msg
    assert "b.py" in msg


def test_hunks_single_file_falls_back_to_single():
    from relay.orchestrator import Orchestrator

    ai = StubAI(["feat(a): add single"])
    git = _make_git(SAMPLE_ONE_FILE)
    orch = Orchestrator(git=git, provider=ai, yes=True, no_push=True, hunks=True)
    orch.run()
    assert len(ai.calls) == 1
    assert git.commit.call_args[0][0] == "feat(a): add single"


def test_hunks_fallback_on_invalid_message():
    from relay.orchestrator import Orchestrator

    # First hunk invalid -> should fallback to manual
    ai = StubAI(["bad message", "feat(b): ok"])
    git = _make_git(SAMPLE_TWO_FILES)
    with mock.patch("builtins.input", side_effect=["feat: manual fallback", ""]):
        orch = Orchestrator(git=git, provider=ai, yes=False, no_push=True, hunks=True)
        orch.run()
    assert git.commit.call_args[0][0] == "feat: manual fallback"


def test_hunks_fallback_on_ai_error():
    from relay.errors import AIError
    from relay.orchestrator import Orchestrator

    ai = StubAI([AIError("gemini", "unavailable", "down")])
    git = _make_git(SAMPLE_TWO_FILES)
    with mock.patch("builtins.input", side_effect=["feat: manual after error", ""]):
        orch = Orchestrator(git=git, provider=ai, yes=False, no_push=True, hunks=True)
        orch.run()
    assert git.commit.call_args[0][0] == "feat: manual after error"


def test_hunks_no_provider_goes_manual():
    from relay.orchestrator import Orchestrator

    git = _make_git(SAMPLE_TWO_FILES)
    with mock.patch("builtins.input", side_effect=["feat: manual no ai", ""]):
        orch = Orchestrator(git=git, provider=None, yes=False, no_push=True, hunks=True)
        orch.run()
    assert git.commit.call_args[0][0] == "feat: manual no ai"


def test_hunks_confirmation_accept():
    from relay.orchestrator import Orchestrator

    ai = StubAI(["feat(a): add a", "feat(b): add b"])
    git = _make_git(SAMPLE_TWO_FILES)
    with mock.patch("builtins.input", return_value="a"):
        orch = Orchestrator(git=git, provider=ai, yes=False, no_push=True, hunks=True)
        orch.run()
    assert git.commit.called


def test_hunks_confirmation_edit():
    from relay.orchestrator import Orchestrator

    ai = StubAI(["feat(a): add a", "feat(b): add b"])
    git = _make_git(SAMPLE_TWO_FILES)
    with mock.patch("builtins.input", side_effect=["e", "feat: edited", ""]):
        orch = Orchestrator(git=git, provider=ai, yes=False, no_push=True, hunks=True)
        orch.run()
    assert git.commit.call_args[0][0] == "feat: edited"


def test_cli_passes_hunks_to_orchestrator():
    from relay.cli import main

    with mock.patch("relay.cli.build_provider"), mock.patch("relay.cli.Orchestrator") as OC:
        OC.return_value.run.return_value = 0
        main(["--solo", "--hunks", "--yes", "--no-push"])
        assert OC.call_args.kwargs["hunks"] is True
        main(["--solo", "--yes", "--no-push"])
        assert OC.call_args.kwargs["hunks"] is False
