"""Unit tests for the CLI entry point (relay/cli.py): flag parsing, mode
resolution, and exit-code mapping."""
import os
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.errors import ConfigError, GitError, UserAbort


class TestParser:
    def test_defaults_to_solo_with_no_flags(self):
        args = build_parser().parse_args([])
        assert args.solo is False
        assert args.team is None

    def test_explicit_solo(self):
        args = build_parser().parse_args(["--solo"])
        assert args.solo is True
        assert args.team is None

    def test_team_with_feature(self):
        args = build_parser().parse_args(["--team", "payments"])
        assert args.team == "payments"

    def test_team_without_feature_uses_empty_string(self):
        args = build_parser().parse_args(["--team"])
        assert args.team == ""

    def test_solo_and_team_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--solo", "--team"])

    def test_timeout_flag_parses_seconds(self):
        args = build_parser().parse_args(["--timeout", "45"])
        assert args.timeout == 45

    def test_timeout_defaults_to_none(self):
        args = build_parser().parse_args([])
        assert args.timeout is None

    def test_staged_flag_parses(self):
        assert build_parser().parse_args(["--staged"]).staged is True
        assert build_parser().parse_args([]).staged is False

    def test_no_verify_flag_parses(self):
        assert build_parser().parse_args(["--no-verify"]).no_verify is True
        assert build_parser().parse_args([]).no_verify is False

    def test_allow_protected_flag_parses(self):
        assert build_parser().parse_args(["--allow-protected"]).allow_protected is True
        assert build_parser().parse_args([]).allow_protected is False


class TestUndoSubcommand:
    def test_undo_parses(self):
        args = build_parser().parse_args(["undo"])
        assert args.command == "undo"

    def test_undo_accepts_verbose(self):
        assert build_parser().parse_args(["undo", "--verbose"]).verbose is True

    def test_main_routes_undo_and_propagates_exit_code(self):
        with mock.patch("relay.cli.run_undo", return_value=0) as run:
            assert main(["undo"]) == 0
        run.assert_called_once_with(verbose=False)

    def test_main_forwards_undo_verbose(self):
        with mock.patch("relay.cli.run_undo", return_value=0) as run:
            main(["undo", "--verbose"])
        run.assert_called_once_with(verbose=True)

    def test_team_feature_named_undo_is_not_a_subcommand(self):
        args = build_parser().parse_args(["--team", "undo"])
        assert args.command is None
        assert args.team == "undo"


class TestPrSubcommand:
    def test_pr_parses_base_and_title(self):
        args = build_parser().parse_args(["pr", "--base", "develop", "--title", "My PR"])
        assert args.command == "pr"
        assert args.base == "develop"
        assert args.title == "My PR"

    def test_pr_defaults_base_to_main(self):
        args = build_parser().parse_args(["pr"])
        assert args.command == "pr"
        assert args.base == "main"
        assert args.title is None

    def test_pr_accepts_verbose(self):
        args = build_parser().parse_args(["pr", "--verbose"])
        assert args.verbose is True

    def test_pr_parses_open_flag(self):
        assert build_parser().parse_args(["pr", "--open"]).open is True
        assert build_parser().parse_args(["pr", "-o"]).open is True
        assert build_parser().parse_args(["pr"]).open is False

    def test_pr_parses_yes_flag(self):
        assert build_parser().parse_args(["pr", "--yes"]).yes is True

    def test_pr_parses_draft_flag(self):
        assert build_parser().parse_args(["pr", "--draft"]).draft is True
        assert build_parser().parse_args(["pr"]).draft is False

    def test_pr_flag_named_team_is_not_a_subcommand(self):
        args = build_parser().parse_args(["--team", "pr"])
        assert args.command is None
        assert args.team == "pr"

    def test_main_routes_pr_and_propagates_exit_code(self):
        with mock.patch("relay.cli.run_pr", return_value=3) as run:
            assert main(["pr"]) == 3
        run.assert_called_once_with(
            base="main", title=None, open_browser=False, draft=False, verbose=False
        )

    def test_main_forwards_pr_flags(self):
        with mock.patch("relay.cli.run_pr", return_value=0) as run:
            main(["pr", "--base", "develop", "--title", "T", "--verbose"])
        run.assert_called_once_with(
            base="develop", title="T", open_browser=False, draft=False, verbose=True
        )

    def test_main_forwards_pr_draft_flag(self):
        with mock.patch("relay.cli.run_pr", return_value=0) as run:
            main(["pr", "--draft"])
        assert run.call_args.kwargs["draft"] is True

    def test_main_open_flag_enables_browser(self):
        with mock.patch("relay.cli.run_pr", return_value=0) as run:
            main(["pr", "--open"])
        assert run.call_args.kwargs["open_browser"] is True

    def test_main_yes_implies_open(self):
        with mock.patch("relay.cli.run_pr", return_value=0) as run:
            main(["pr", "--yes"])
        assert run.call_args.kwargs["open_browser"] is True

    def test_main_env_var_enables_open(self):
        with mock.patch.dict(os.environ, {"RELAY_PR_OPEN": "1"}):
            with mock.patch("relay.cli.run_pr", return_value=0) as run:
                main(["pr"])
        assert run.call_args.kwargs["open_browser"] is True

    def test_main_env_var_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("relay.cli.run_pr", return_value=0) as run:
                main(["pr"])
        assert run.call_args.kwargs["open_browser"] is False

    def test_pr_error_maps_to_exit_1(self):
        with mock.patch("relay.cli.run_pr", side_effect=GitError("boom")):
            assert main(["pr"]) == 1

    def test_pr_unexpected_error_maps_to_exit_1(self):
        with mock.patch("relay.cli.run_pr", side_effect=RuntimeError("bug")):
            assert main(["pr"]) == 1


class TestAmendSubcommand:
    def test_amend_parses_as_subcommand(self):
        args = build_parser().parse_args(["amend"])
        assert args.command == "amend"

    def test_amend_accepts_workflow_flags(self):
        args = build_parser().parse_args(
            ["amend", "--provider", "ollama", "--timeout", "45", "--yes",
             "--staged", "--dry-run", "--verbose"]
        )
        assert args.provider == "ollama"
        assert args.timeout == 45
        assert args.yes is True
        assert args.staged is True
        assert args.dry_run is True
        assert args.verbose is True

    def test_amend_flag_named_team_is_not_a_subcommand(self):
        args = build_parser().parse_args(["--team", "amend"])
        assert args.command is None
        assert args.team == "amend"

    def test_main_routes_amend_to_orchestrator(self):
        with mock.patch("relay.cli.build_provider") as build_provider, mock.patch(
            "relay.cli.Orchestrator"
        ) as orchestrator_cls:
            orchestrator_cls.return_value.run.return_value = 0
            assert main(["amend"]) == 0
        orchestrator_cls.assert_called_once_with(
            mode="amend",
            feature=None,
            provider=build_provider.return_value,
            yes=False,
            no_push=True,
            staged_only=False,
            no_verify=False,
            dry_run=False,
            verbose=False,
        )
        orchestrator_cls.return_value.run.assert_called_once_with()

    def test_main_forwards_amend_flags(self):
        with mock.patch("relay.cli.build_provider"), mock.patch(
            "relay.cli.Orchestrator"
        ) as orchestrator_cls:
            main(["amend", "--yes", "--staged", "--dry-run", "--verbose",
                  "--timeout", "50"])
        kw = orchestrator_cls.call_args.kwargs
        assert kw["mode"] == "amend"
        assert kw["yes"] is True
        assert kw["staged_only"] is True
        assert kw["dry_run"] is True
        assert kw["verbose"] is True
        assert kw["no_push"] is True

    def test_main_amend_forwards_provider_timeout(self):
        with mock.patch("relay.cli.build_provider") as build_provider, mock.patch(
            "relay.cli.Orchestrator"
        ):
            main(["amend", "--provider", "ollama", "--timeout", "30"])
        build_provider.assert_called_once_with("ollama", timeout=30)

    def test_main_amend_propagates_exit_code(self):
        with mock.patch("relay.cli.build_provider"), mock.patch(
            "relay.cli.Orchestrator"
        ) as orchestrator_cls:
            orchestrator_cls.return_value.run.return_value = 7
            assert main(["amend"]) == 7

    def test_main_amend_user_abort_maps_to_exit_130(self):
        with mock.patch("relay.cli.build_provider"), mock.patch(
            "relay.cli.Orchestrator"
        ) as orchestrator_cls:
            orchestrator_cls.return_value.run.side_effect = UserAbort("aborted")
            assert main(["amend"]) == 130


@pytest.fixture
def wired():
    """Patch the CLI's provider factory and Orchestrator, returning the mocks."""
    with mock.patch("relay.cli.build_provider") as build_provider, mock.patch(
        "relay.cli.Orchestrator"
    ) as orchestrator_cls:
        orchestrator_cls.return_value.run.return_value = 0
        yield build_provider, orchestrator_cls


def test_main_solo_wires_orchestrator(wired):
    build_provider, orchestrator_cls = wired
    assert main(["--solo", "--yes", "--no-push"]) == 0
    orchestrator_cls.assert_called_once_with(
        mode="solo",
        feature=None,
        provider=build_provider.return_value,
        yes=True,
        no_push=True,
        staged_only=False,
        no_verify=False,
        dry_run=False,
        verbose=False,
        allow_protected=False,
    )
    orchestrator_cls.return_value.run.assert_called_once_with()


def test_main_team_with_feature(wired):
    build_provider, orchestrator_cls = wired
    main(["--team", "payments"])
    assert orchestrator_cls.call_args.kwargs["mode"] == "team"
    assert orchestrator_cls.call_args.kwargs["feature"] == "payments"


def test_main_forwards_timeout_to_provider(wired):
    build_provider, _ = wired
    main(["--solo", "--timeout", "45"])
    build_provider.assert_called_once_with(None, timeout=45)


def test_main_forwards_staged_flag(wired):
    _, orchestrator_cls = wired
    main(["--solo", "--staged"])
    assert orchestrator_cls.call_args.kwargs["staged_only"] is True
    main(["--solo"])
    assert orchestrator_cls.call_args.kwargs["staged_only"] is False


def test_main_forwards_no_verify_flag(wired):
    _, orchestrator_cls = wired
    main(["--solo", "--no-verify"])
    assert orchestrator_cls.call_args.kwargs["no_verify"] is True
    main(["--solo"])
    assert orchestrator_cls.call_args.kwargs["no_verify"] is False


def test_main_forwards_allow_protected_flag(wired):
    _, orchestrator_cls = wired
    main(["--solo", "--allow-protected"])
    assert orchestrator_cls.call_args.kwargs["allow_protected"] is True
    main(["--solo"])
    assert orchestrator_cls.call_args.kwargs["allow_protected"] is False


def test_main_team_without_feature_passes_none(wired):
    _, orchestrator_cls = wired
    main(["--team"])
    assert orchestrator_cls.call_args.kwargs["mode"] == "team"
    assert orchestrator_cls.call_args.kwargs["feature"] is None


def test_main_propagates_orchestrator_exit_code(wired):
    _, orchestrator_cls = wired
    orchestrator_cls.return_value.run.return_value = 7
    assert main(["--solo"]) == 7


def test_missing_gemini_key_falls_back_to_manual_provider():
    """A missing GEMINI_API_KEY must not abort the solo run: the provider is
    built lazily and degraded to None so the Orchestrator's manual-input
    fallback takes over (H-14)."""
    with mock.patch(
        "relay.cli.build_provider", side_effect=ConfigError("no key")
    ), mock.patch("relay.cli.Orchestrator") as orchestrator_cls:
        orchestrator_cls.return_value.run.return_value = 0
        assert main(["--solo"]) == 0
    assert orchestrator_cls.call_args.kwargs["provider"] is None


def test_user_abort_maps_to_exit_130(wired):
    _, orchestrator_cls = wired
    orchestrator_cls.return_value.run.side_effect = UserAbort("aborted")
    assert main(["--solo"]) == 130


def test_git_error_maps_to_exit_1(wired):
    _, orchestrator_cls = wired
    orchestrator_cls.return_value.run.side_effect = GitError("boom")
    assert main(["--solo"]) == 1


def test_unexpected_exception_maps_to_exit_1(wired):
    _, orchestrator_cls = wired
    orchestrator_cls.return_value.run.side_effect = RuntimeError("bug")
    assert main(["--solo"]) == 1
