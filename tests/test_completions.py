"""Unit tests for relay/completions.py and the `relay completions` CLI path."""
import argparse
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.completions import (
    GLOBAL_FLAGS,
    SHELLS,
    SUBCOMMAND_FLAGS,
    SUBCOMMANDS,
    generate,
)


def _parser_subcommand_flags() -> dict[str, set[str]]:
    """Option strings argparse registers per subcommand (minus -h/--help)."""
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {
                name: {opt for a in sub._actions for opt in a.option_strings}
                - {"-h", "--help"}
                for name, sub in action.choices.items()
            }
    raise AssertionError("no subparsers found in the parser")


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

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
    def test_every_subcommand_appears_in_every_shell(self, shell):
        """Regression: fish completion was hand-written and dropped stage, man
        and telemetry while bash/zsh/powershell derived the list dynamically.
        Every shell must advertise every subcommand from the source of truth."""
        out = generate(shell)
        for subcommand in SUBCOMMANDS:
            assert subcommand in out, f"{shell} completion is missing '{subcommand}'"

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
    def test_every_global_flag_appears_in_every_shell(self, shell):
        out = generate(shell)
        for flag in GLOBAL_FLAGS:
            raw = flag.lstrip("-")
            if shell == "fish":
                assert f"-l {raw}" in out, f"{shell} completion is missing '-l {raw}'"
            else:
                assert f"--{raw}" in out, f"{shell} completion is missing '--{raw}'"

    def test_bash_has_complete_directive(self):
        assert "complete -F" in generate("bash")

    def test_fish_has_complete_lines(self):
        assert "complete -c relay" in generate("fish")

    def test_unknown_shell_raises(self):
        with pytest.raises(ValueError):
            generate("tcsh")


class TestSubcommandFlags:
    def test_table_matches_the_parser_exactly(self):
        """Drift in either direction is a bug: a flag users can type that no
        shell completes, or a completion the installed CLI would reject."""
        expected = {name: set(flags) for name, flags in SUBCOMMAND_FLAGS.items()}
        actual = {name: flags for name, flags in _parser_subcommand_flags().items() if flags}
        assert actual == expected

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_every_subcommand_flag_is_advertised(self, shell):
        out = generate(shell)
        for sub, flags in SUBCOMMAND_FLAGS.items():
            for flag in flags:
                if shell != "fish":
                    needle = flag
                else:
                    needle = f"-s {flag[1:]}" if not flag.startswith("--") else f"-l {flag[2:]}"
                assert needle in out, f"{shell} is missing '{needle}' for '{sub}'"

    def test_bash_pr_branch_offers_the_body_flags(self):
        out = generate("bash")
        for flag in ("--body", "--body-file", "--edit", "--draft"):
            assert flag in out

    def test_zsh_offers_doctor_json(self):
        assert "--json" in generate("zsh")

    def test_global_flags_grew_with_the_release(self):
        for flag in ("-m", "--message", "-s", "--signoff", "--validate-manual",
                     "--allow-sensitive"):
            assert flag in GLOBAL_FLAGS, flag


class TestManPageDocumentsTheCli:
    @staticmethod
    def _roff(flag: str) -> str:
        """roff form of a flag: leading hyphens escaped, inner ones literal."""
        stripped = flag.lstrip("-")
        return "\\-" * (len(flag) - len(stripped)) + stripped

    def test_man_documents_every_global_flag(self):
        from relay.man import MAN_PAGE_TEMPLATE

        for flag in GLOBAL_FLAGS:
            roff = self._roff(flag)
            assert roff in MAN_PAGE_TEMPLATE, f"man page is missing {flag} ({roff})"

    def test_man_documents_subcommand_flags(self):
        from relay.man import MAN_PAGE_TEMPLATE

        for flag in (r"\-\-json", r"\-\-probe", r"\-\-body-file", r"\-\-edit",
                     r"\-\-count", r"\-\-no-verify", r"\-\-patch", r"\-\-message"):
            assert flag in MAN_PAGE_TEMPLATE, f"man page is missing {flag}"

    def test_man_synopsis_mentions_every_subcommand(self):
        from relay.man import MAN_PAGE_TEMPLATE

        for subcommand in SUBCOMMANDS:
            assert subcommand in MAN_PAGE_TEMPLATE

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

    def test_man_output_has_no_form_feed_characters(self, capsys):
        # Regression: relay/man.py used an f-string whose \\fI/\\fR/\\fB escapes
        # were parsed as Python form-feed ("\f") characters, corrupting every
        # man page with U+000C control bytes. The template is a raw string, so
        # the output here must contain zero form feeds.
        assert main(["man"]) == 0
        assert "\x0c" not in capsys.readouterr().out


class TestCliMan:
    def test_main_routes_man(self, capsys):
        with mock.patch("relay.cli.MAN_PAGE_TEMPLATE", "TH RELAY 1\nx"):
            assert main(["man"]) == 0
        assert capsys.readouterr().out == "TH RELAY 1\nx"
