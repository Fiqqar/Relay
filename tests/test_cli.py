"""Unit tests for the CLI entry point (relay/cli.py): flag parsing, mode
resolution, and exit-code mapping."""
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
        dry_run=False,
        verbose=False,
    )
    orchestrator_cls.return_value.run.assert_called_once_with()


def test_main_team_with_feature(wired):
    build_provider, orchestrator_cls = wired
    main(["--team", "payments"])
    assert orchestrator_cls.call_args.kwargs["mode"] == "team"
    assert orchestrator_cls.call_args.kwargs["feature"] == "payments"


def test_main_team_without_feature_passes_none(wired):
    _, orchestrator_cls = wired
    main(["--team"])
    assert orchestrator_cls.call_args.kwargs["mode"] == "team"
    assert orchestrator_cls.call_args.kwargs["feature"] is None


def test_main_propagates_orchestrator_exit_code(wired):
    _, orchestrator_cls = wired
    orchestrator_cls.return_value.run.return_value = 7
    assert main(["--solo"]) == 7


def test_missing_gemini_key_maps_to_exit_1():
    with mock.patch("relay.cli.build_provider", side_effect=ConfigError("no key")):
        assert main(["--solo"]) == 1


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
