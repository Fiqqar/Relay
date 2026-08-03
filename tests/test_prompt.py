"""Unit tests for relay/prompt.py — the commit confirmation menu.

The whole point of this module is to make the `a` (Accept) vs `A` (Abort)
distinction strict, so the case-sensitive edge cases are covered exhaustively.
"""
import pytest

from relay.prompt import ABORT, ACCEPT, EDIT, RETRY, interpret_choice


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
        "raw", ["A", "q", "c", "abort", "cancel", "ABORT", "Q", "C"]
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
