"""Unit tests for `relay doctor` (relay/doctor.py) and its CLI routing."""
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.doctor import Check, run_doctor


class FakeGit:
    """Stand-in for GitManager with controllable results."""

    def __init__(self, is_repo=True, has_changes=False, has_remote=True, branch="main",
                 config=None):
        self._is_repo = is_repo
        self._changes = has_changes
        self._remote = has_remote
        self._branch = branch
        self._config = dict(config or {"user.name": "Ada L.", "user.email": "ada@dev.io"})

    def is_repo(self):
        return self._is_repo

    def has_changes(self):
        return self._changes

    def has_remote(self):
        return self._remote

    def current_branch(self):
        return self._branch

    def config_get(self, key):
        return self._config.get(key, "")


@pytest.fixture
def healthy_env():
    """Environment where every doctor check passes."""
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), mock.patch(
        "relay.doctor._git_version", return_value="2.42.0"
    ), mock.patch("relay.doctor.shutil.which", side_effect=lambda name: {
        "relay": r"C:\tools\Scripts\relay.exe",
        "git": r"C:\tools\git.exe",
    }.get(name)    ), mock.patch(
        "relay.doctor.provider_from_env", return_value="gemini"
    ), mock.patch("relay.doctor.gemini_api_key", return_value="test-key"), mock.patch(
        "relay.doctor.github_token", return_value="test-token"
    ), mock.patch("relay.doctor.gitlab_token", return_value=None):
        yield


def test_healthy_env_returns_zero(healthy_env, capsys):
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "all good" in out
    assert "GEMINI_API_KEY is set" in out


def test_missing_gemini_key_fails(healthy_env, capsys):
    with mock.patch("relay.doctor.gemini_api_key", return_value=None):
        assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "GEMINI_API_KEY is not set" in out


def test_git_identity_set_passes(healthy_env, capsys):
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "Ada L. <ada@dev.io>" in out


def test_missing_git_identity_fails(healthy_env, capsys):
    with mock.patch(
        "relay.doctor.GitManager",
        return_value=FakeGit(config={"user.name": "Ada L."}),
    ):
        assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "user.email" in out
    assert "git config --global user.email" in out


def test_missing_git_fails(healthy_env, capsys):
    def which(name):
        return None if name == "git" else r"C:\tools\Scripts\relay.exe"

    with mock.patch("relay.doctor.shutil.which", side_effect=which):
        assert run_doctor() == 1
    assert "not found on PATH" in capsys.readouterr().out


def test_missing_relay_on_path_warns_but_passes(healthy_env, capsys):
    def which(name):
        return None if name == "relay" else r"C:\tools\git.exe"

    with mock.patch("relay.doctor.shutil.which", side_effect=which):
        assert run_doctor() == 0  # warn is not a failure
    assert "not found" in capsys.readouterr().out


def test_not_a_repo_warns_but_passes(healthy_env, capsys):
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(is_repo=False)):
        assert run_doctor() == 0
    assert "not inside a git repository" in capsys.readouterr().out


def test_ollama_provider_skips_gemini_key(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="ollama"), mock.patch(
        "relay.doctor.ollama_base_url", return_value="http://localhost:11434"
    ), mock.patch("relay.doctor._ollama_reachable", return_value=(True, "reachable at http://localhost:11434")):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "Ollama" in out
    assert "GEMINI_API_KEY" not in out


def test_openai_provider_checks_openai_key(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="openai"), mock.patch(
        "relay.doctor.openai_api_key", return_value="sk-test"
    ):
        assert run_doctor() == 0
    assert "OPENAI_API_KEY is set" in capsys.readouterr().out


def test_openai_provider_missing_key_fails(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="openai"), mock.patch(
        "relay.doctor.openai_api_key", return_value=None
    ):
        assert run_doctor() == 1
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().out


def test_anthropic_provider_checks_anthropic_key(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="anthropic"), mock.patch(
        "relay.doctor.anthropic_api_key", return_value="sk-ant-test"
    ):
        assert run_doctor() == 0
    assert "ANTHROPIC_API_KEY is set" in capsys.readouterr().out


def test_unknown_provider_warns(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="wat"):
        assert run_doctor() == 0  # warn only, not a hard failure
    assert "unknown provider" in capsys.readouterr().out


def test_github_token_set_passes(healthy_env, capsys):
    assert run_doctor() == 0
    assert "GITHUB_TOKEN is set" in capsys.readouterr().out


def test_github_token_missing_warns_but_passes(healthy_env, capsys):
    with mock.patch("relay.doctor.github_token", return_value=None):
        assert run_doctor() == 0  # a missing token is a warn, not a failure
    out = capsys.readouterr().out
    assert "GITHUB_TOKEN / GITLAB_TOKEN is not set" in out
    assert "WARN" in out


def test_gitlab_token_set_passes(healthy_env, capsys):
    with mock.patch("relay.doctor.github_token", return_value=None), mock.patch(
        "relay.doctor.gitlab_token", return_value="glpat-test"
    ):
        assert run_doctor() == 0
    assert "GITLAB_TOKEN is set" in capsys.readouterr().out


def test_provider_override_flag(healthy_env):
    with mock.patch("relay.doctor.provider_from_env", return_value="gemini") as from_env:
        run_doctor(provider="ollama")
        from_env.assert_not_called()  # the explicit flag wins


def test_explicit_provider_wins_over_env(healthy_env):
    with mock.patch("relay.doctor.ollama_base_url", return_value="http://localhost:11434"), mock.patch(
        "relay.doctor._ollama_reachable", return_value=(True, "reachable")
    ):
        assert run_doctor(provider="ollama") == 0


# ---- CLI routing -----------------------------------------------------------

def test_parser_routes_doctor_subcommand():
    assert build_parser().parse_args(["doctor"]).command == "doctor"
    assert build_parser().parse_args([]).command is None


def test_team_feature_named_doctor_is_not_a_subcommand():
    args = build_parser().parse_args(["--team", "doctor"])
    assert args.command is None
    assert args.team == "doctor"


def test_main_doctor_routes_and_propagates_exit_code():
    with mock.patch("relay.cli.run_doctor", return_value=3) as run:
        assert main(["doctor"]) == 3
    run.assert_called_once_with(provider=None, verbose=False)


def test_main_doctor_accepts_provider_and_verbose():
    with mock.patch("relay.cli.run_doctor", return_value=0) as run:
        main(["doctor", "--provider", "ollama", "--verbose"])
    run.assert_called_once_with(provider="ollama", verbose=True)


def test_main_doctor_failure_is_not_fatal(capsys):
    with mock.patch("relay.cli.run_doctor", side_effect=RuntimeError("boom")):
        assert main(["doctor"]) == 1
    assert "error: boom" in capsys.readouterr().out
