"""Unit tests for relay/completions.py and the `relay completions` CLI path."""
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.completions import SHELLS, generate


class TestParser:
    def test_completions_parses_shell(self):
        args = build_parser().parse_args(["completions", "zsh"])
        assert args.command == "completions"
        assert args.shell == "zsh"

    def test_completions_shell_optional(self):
        args = build_parser().parse_args(["completions"])
        assert args.command == "completions"
        assert args.shell is None

    def test_completions_rejects_bad_shell(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["completions", "tcsh"])

    def test_flag_named_completions_is_not_a_subcommand(self):
        args = build_parser().parse_args(["--team", "completions"])
        assert args.command is None
        assert args.team == "completions"


class TestGenerate:
    def test_all_shells_generate_something(self):
        for shell in SHELLS:
            out = generate(shell)
            assert out.strip()
            assert "relay" in out

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
    def test_shells_mention_subcommands(self, shell):
        out = generate(shell)
        assert "doctor" in out

    def test_bash_has_complete_directive(self):
        assert "complete -F" in generate("bash")

    def test_fish_has_complete_lines(self):
        assert "complete -c relay" in generate("fish")

    def test_unknown_shell_raises(self):
        with pytest.raises(ValueError):
            generate("tcsh")

    def test_case_insensitive(self):
        assert generate("BASH") == generate("bash")


class TestCliRouting:
    def test_main_prints_bash_completions(self, capsys):
        assert main(["completions", "bash"]) == 0
        out = capsys.readouterr().out
        assert "complete -F" in out

    def test_main_man_prints_roff(self, capsys):
        assert main(["man"]) == 0
        out = capsys.readouterr().out
        assert ".TH RELAY" in out
        assert "SYNOPSIS" in out


class TestCliMan:
    def test_main_routes_man(self, capsys):
        with mock.patch("relay.cli.MAN_PAGE_TEMPLATE", "TH RELAY 1\nx"):
            assert main(["man"]) == 0
        assert capsys.readouterr().out == "TH RELAY 1\nx"