"""Unit tests for relay/prompt.py — the commit confirmation menu.

The whole point of this module is to make the `a` (Accept) vs `A` (Abort)
distinction strict, so the case-sensitive edge cases are covered exhaustively.
"""
import os
from unittest import mock

import pytest

from relay.errors import UserAbort
from relay.prompt import (
    ABORT,
    ACCEPT,
    CONFIRM_PROMPT,
    EDIT,
    RETRY,
    interpret_choice,
    manual_input,
    open_in_editor,
)


class TestInterpretChoice:
    @pytest.mark.parametrize("raw", ["a", "y", "accept", "yes", "ACCEPT", "Y"])
    def test_accept_keys(self, raw):
        assert interpret_choice(raw) == ACCEPT

    @pytest.mark.parametrize("raw", ["e", "edit", "EDIT"])
    def test_edit_keys(self, raw):
        assert interpret_choice(raw) == EDIT

    @pytest.mark.parametrize("raw", ["r", "retry", "RETRY"])
    def test_retry_keys(self, raw):
        assert interpret_choice(raw) == RETRY

    @pytest.mark.parametrize(
        "raw", ["A", "q", "c", "abort", "cancel", "ABORT", "Q", "C", "n", "N", "no", "NO", "No"]
    )
    def test_abort_keys(self, raw):
        assert interpret_choice(raw) == ABORT

    def test_uppercase_a_is_abort_not_accept(self):
        assert interpret_choice("a") == ACCEPT
        assert interpret_choice("A") == ABORT

    def test_enter_aborts(self):
        assert interpret_choice("") == ABORT
        assert interpret_choice("   ") == ABORT

    def test_surrounding_whitespace_is_ignored(self):
        assert interpret_choice("  a  ") == ACCEPT
        assert interpret_choice("  A  ") == ABORT

    def test_unrecognized_input_aborts(self):
        assert interpret_choice("x") == ABORT
        assert interpret_choice("?") == ABORT
        assert interpret_choice("10") == ABORT

    def test_confirm_prompt_shows_yes_no_shortcuts(self):
        assert "(y/e/r/n)" in CONFIRM_PROMPT


class TestManualInput:
    def test_subject_and_body_are_joined_with_blank_line(self):
        inputs = ["feat(api): add endpoint", "Returns paginated results.", ""]
        with mock.patch("builtins.input", side_effect=inputs):
            assert manual_input() == "feat(api): add endpoint\n\nReturns paginated results."

    def test_dot_inserts_paragraph_break(self):
        inputs = ["fix(core): handle empty diff", ".", "Falls back to prompt.", ""]
        with mock.patch("builtins.input", side_effect=inputs):
            assert manual_input() == "fix(core): handle empty diff\n\nFalls back to prompt."

    def test_empty_answer_aborts(self):
        with mock.patch("builtins.input", side_effect=[""]):
            with pytest.raises(UserAbort):
                manual_input()

    def test_empty_answer_falls_back_to_draft(self):
        with mock.patch("builtins.input", side_effect=[""]):
            assert manual_input(draft="docs(readme): fix typo") == "docs(readme): fix typo"

    def test_eof_aborts_without_draft(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            with pytest.raises(UserAbort):
                manual_input()

    def test_eof_falls_back_to_draft(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            assert manual_input(draft="chore(deps): bump") == "chore(deps): bump"


class TestOpenInEditor:
    def test_invokes_editor_and_returns_content(self):
        def fake_editor_run(cmd, check=False):
            path = cmd[-1]
            with open(path, "w", encoding="utf-8") as f:
                f.write("feat(editor): from editor\n\nBody from editor")
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch.dict("os.environ", {"EDITOR": "dummy-editor"}):
                with mock.patch("subprocess.run", side_effect=fake_editor_run):
                    result = open_in_editor("draft message")
        assert result == "feat(editor): from editor\n\nBody from editor"

    def test_returns_none_when_not_a_tty(self):
        with mock.patch("sys.stdin.isatty", return_value=False):
            assert open_in_editor("draft") is None

    def test_returns_none_on_editor_error(self):
        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
                assert open_in_editor("draft") is None

    def test_explicit_git_honors_core_editor(self):
        git = mock.Mock()
        git.config_get.return_value = "code --wait"
        captured_cmds = []

        def fake_run(cmd, check=False):
            captured_cmds.append(cmd)
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch.dict("os.environ", {}, clear=True):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    open_in_editor("draft", git)
                    assert captured_cmds[-1][0] == "code"
                    assert captured_cmds[-1][1] == "--wait"


class TestOpenInEditorEdgeCases:
    def test_git_lookup_failure_falls_back_to_env_editor(self):
        git = mock.Mock()
        git.config_get.side_effect = RuntimeError("git gone")

        def fake_run(cmd, check=False):
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("fix(core): via fallback editor")
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch.dict("os.environ", {"EDITOR": "dummy-editor"}):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    assert open_in_editor("draft", git) == "fix(core): via fallback editor"

    def test_empty_draft_leaves_empty_file_and_returns_none(self):
        seen = {}

        def fake_run(cmd, check=False):
            seen["path"] = cmd[-1]
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch.dict("os.environ", {"EDITOR": "dummy-editor"}):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    assert open_in_editor("") is None
        assert not os.path.exists(seen["path"])

    def test_windows_file_editor_is_invoked_directly(self):
        seen = {}

        def fake_run(cmd, check=False):
            seen["cmd"] = cmd
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("feat(win): direct path")
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch("sys.platform", "win32"):
                with mock.patch.dict(
                    "os.environ", {"GIT_EDITOR": "C:\\tools\\ed.exe"}, clear=True
                ):
                    with mock.patch("os.path.isfile", return_value=True):
                        with mock.patch("subprocess.run", side_effect=fake_run):
                            result = open_in_editor("draft")
        assert result == "feat(win): direct path"
        assert seen["cmd"] == ["C:\\tools\\ed.exe", seen["cmd"][-1]]

    def test_posix_shell_like_editor_is_split(self):
        seen = {}

        def fake_run(cmd, check=False):
            seen["cmd"] = cmd
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch("sys.platform", "linux"):
                with mock.patch.dict(
                    "os.environ", {"EDITOR": "code --wait"}, clear=True
                ):
                    with mock.patch("subprocess.run", side_effect=fake_run):
                        # Editor left the file untouched, so the draft is returned.
                        assert open_in_editor("draft") == "draft"
        assert seen["cmd"][:2] == ["code", "--wait"]
        assert len(seen["cmd"]) == 3

    def test_editor_spawn_failure_returns_none(self):
        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch.dict("os.environ", {"EDITOR": "dummy-editor"}):
                with mock.patch(
                    "subprocess.run", side_effect=FileNotFoundError("no editor")
                ):
                    assert open_in_editor("draft") is None

    def test_cleanup_failure_still_returns_content(self):
        written = {}

        def fake_run(cmd, check=False):
            written["path"] = cmd[-1]
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("feat(x): kept despite cleanup failure")
            return mock.Mock(returncode=0)

        with mock.patch("sys.stdin.isatty", return_value=True):
            with mock.patch.dict("os.environ", {"EDITOR": "dummy-editor"}):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    with mock.patch("os.unlink", side_effect=OSError("locked")):
                        result = open_in_editor("draft")
        assert result == "feat(x): kept despite cleanup failure"
        os.unlink(written["path"])
