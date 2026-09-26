"""Unit tests for `relay doctor` (relay/doctor.py) and its CLI routing."""
import json
import subprocess
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.doctor import (
    _git_version,
    _ollama_reachable,
    _probe_forge,
    _probe_forge_endpoint,
    _probe_provider,
    run_doctor,
)


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
    ), mock.patch("relay.doctor.gitlab_token", return_value=None), mock.patch(
        "relay.doctor.bitbucket_token", return_value=None
    ), mock.patch(
        "relay.doctor.protected_branches", return_value=["main", "master"]
    ), mock.patch(
        "relay.doctor.config_file_path", return_value=None
    ), mock.patch(
        "relay.doctor.local_config_file_path", return_value=None
    ), mock.patch(
        "relay.doctor.hook_pre_commit", return_value=None
    ), mock.patch(
        "relay.doctor.hook_post_push", return_value=None
    ):
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


def test_report_strips_ansi_from_git_config(healthy_env, capsys):
    """L5: user.name/user.email come from repo config (attacker-controllable
    via a malicious clone) and must not reach the terminal raw."""
    evil = {"user.name": "\x1b[2J\x1b[H.evil", "user.email": "e@x.io"}
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(config=evil)):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert ".evil <e@x.io>" in out


def test_missing_git_identity_fails(healthy_env, capsys):
    with mock.patch(
        "relay.doctor.GitManager",
        return_value=FakeGit(config={"user.name": "Ada L."}),
    ):
        assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "user.email" in out
    assert "git config --global user.email" in out


def test_uncommitted_changes_reported(healthy_env, capsys):
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(has_changes=True)):
        assert run_doctor() == 0  # a dirty tree is a report, not a failure
    assert "uncommitted changes: yes" in capsys.readouterr().out


class TestGitVersion:
    def test_parses_git_version_output(self):
        proc = subprocess.CompletedProcess(
            [], 0, "git version 2.46.0.windows.1\n", ""
        )
        with mock.patch("relay.doctor.subprocess.run", return_value=proc):
            assert _git_version() == "2.46.0.windows.1"

    def test_returns_empty_on_os_error(self):
        with mock.patch("relay.doctor.subprocess.run", side_effect=OSError("no git")):
            assert _git_version() == ""

    def test_uses_utf8_replace_decoding(self):
        """Non-UTF-8 locale bytes must not break the git version probe."""
        proc = subprocess.CompletedProcess(
            [], 0, "git version 2.46.0.windows.1 — em—dash\n", ""
        )
        with mock.patch(
            "relay.doctor.subprocess.run", return_value=proc
        ) as mock_run:
            assert _git_version() == "2.46.0.windows.1 — em—dash"
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"


class TestOllamaReachable:
    def test_reachable_with_explicit_port(self):
        with mock.patch("relay.doctor.socket.create_connection") as conn:
            ok, detail = _ollama_reachable("http://localhost:11434")
        conn.assert_called_once_with(("localhost", 11434), timeout=1)
        assert ok is True
        assert "reachable" in detail

    def test_defaults_to_port_80(self):
        with mock.patch("relay.doctor.socket.create_connection") as conn:
            ok, detail = _ollama_reachable("http://ollama-box")
        conn.assert_called_once_with(("ollama-box", 80), timeout=1)
        assert ok is True

    def test_not_reachable_on_os_error(self):
        with mock.patch(
            "relay.doctor.socket.create_connection", side_effect=OSError("refused")
        ):
            ok, detail = _ollama_reachable("http://localhost:11434")
        assert ok is False
        assert "not reachable" in detail

    def test_unparseable_url(self):
        ok, detail = _ollama_reachable("not-a-url")
        assert ok is False
        assert "cannot parse URL" in detail


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


def test_anthropic_provider_missing_key_fails(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="anthropic"), mock.patch(
        "relay.doctor.anthropic_api_key", return_value=None
    ):
        assert run_doctor() == 1
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out


def test_ollama_custom_base_url_reported_in_detail(healthy_env, capsys):
    with mock.patch("relay.doctor.provider_from_env", return_value="ollama"), mock.patch(
        "relay.doctor.ollama_base_url", return_value="http://mybox:8080"
    ), mock.patch("relay.doctor._ollama_reachable", return_value=(False, "not reachable")):
        run_doctor()
    assert "Ollama (http://mybox:8080)" in capsys.readouterr().out


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
    assert "GITHUB_TOKEN / GITLAB_TOKEN / BITBUCKET_TOKEN is not set" in out
    assert "WARN" in out


def test_gitlab_token_set_passes(healthy_env, capsys):
    with mock.patch("relay.doctor.github_token", return_value=None), mock.patch(
        "relay.doctor.gitlab_token", return_value="glpat-test"
    ):
        assert run_doctor() == 0
    assert "GITLAB_TOKEN is set" in capsys.readouterr().out


def test_bitbucket_token_set_passes(healthy_env, capsys):
    with mock.patch("relay.doctor.github_token", return_value=None), mock.patch(
        "relay.doctor.gitlab_token", return_value=None
    ), mock.patch("relay.doctor.bitbucket_token", return_value="user:app_password"):
        assert run_doctor() == 0
    assert "BITBUCKET_TOKEN is set" in capsys.readouterr().out


def test_provider_override_flag(healthy_env):
    with mock.patch("relay.doctor.provider_from_env", return_value="gemini") as from_env, mock.patch(
        "relay.doctor.ollama_base_url", return_value="http://localhost:11434"
    ), mock.patch(
        "relay.doctor._ollama_reachable", return_value=(True, "reachable")
    ):
        run_doctor(provider="ollama")
        from_env.assert_not_called()  # the explicit flag wins


def test_explicit_provider_wins_over_env(healthy_env):
    with mock.patch("relay.doctor.ollama_base_url", return_value="http://localhost:11434"), mock.patch(
        "relay.doctor._ollama_reachable", return_value=(True, "reachable")
    ):
        assert run_doctor(provider="ollama") == 0


# ---- Protected-branch reporting ---------------------------------------------


def test_doctor_reports_protected_branches(healthy_env, capsys):
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(branch="feature/x")):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "Protected branches" in out
    assert "main, master" in out


def test_doctor_warns_when_on_a_protected_branch(healthy_env, capsys):
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(branch="main")):
        assert run_doctor() == 0  # a warn, not a failure
    out = capsys.readouterr().out
    assert "currently on protected branch 'main'" in out
    assert "WARN" in out


def test_doctor_warns_case_insensitively_on_protected_branch(healthy_env, capsys):
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(branch="Main")):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "currently on protected branch 'Main'" in out
    assert "WARN" in out


def test_doctor_no_warning_when_off_protected_branch(healthy_env, capsys):
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(branch="feat/x")):
        run_doctor()
    out = capsys.readouterr().out
    assert "currently on protected branch" not in out


# ---- config-file audit & hook checks ---------------------------------------


def test_doctor_reports_absent_config_as_defaults(healthy_env, capsys):
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "User config" in out
    assert "using defaults" in out
    assert "no .relay.toml" in out
    assert "none configured" in out  # hooks


def test_doctor_reports_valid_config_path(healthy_env, capsys, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[relay]\nprovider = "ollama"\n', encoding="utf-8")
    with mock.patch("relay.doctor.config_file_path", return_value=cfg):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert str(cfg) in out
    assert "parse error" not in out


def test_doctor_warns_on_malformed_user_config(healthy_env, capsys, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[relay\nprovider = \n", encoding="utf-8")
    with mock.patch("relay.doctor.config_file_path", return_value=cfg):
        assert run_doctor() == 0  # a malformed file warns; it is not fatal
    out = capsys.readouterr().out
    assert "parse error" in out
    assert "WARN" in out


def test_doctor_warns_on_malformed_repo_config(healthy_env, capsys, tmp_path):
    cfg = tmp_path / ".relay.toml"
    cfg.write_text("not = = toml\n", encoding="utf-8")
    with mock.patch("relay.doctor.local_config_file_path", return_value=cfg):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "Repo config" in out
    assert "parse error" in out


def test_doctor_fails_when_config_cannot_be_read(healthy_env, capsys, tmp_path):
    """A directory resolves as a config path but cannot be read as a file."""
    with mock.patch("relay.doctor.config_file_path", return_value=tmp_path):
        assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "unreadable" in out
    assert "FAIL" in out


def test_doctor_reports_missing_config_file_as_defaults(healthy_env, capsys, tmp_path):
    """A configured path that no longer exists degrades to the defaults."""
    with mock.patch("relay.doctor.config_file_path", return_value=tmp_path / "gone.toml"):
        assert run_doctor() == 0
    assert "using defaults" in capsys.readouterr().out


def test_doctor_hook_on_path_passes(healthy_env, capsys):
    with mock.patch("relay.doctor.hook_pre_commit", return_value=["pre-commit"]), mock.patch(
        "relay.doctor.shutil.which", return_value="/usr/bin/pre-commit"
    ):
        assert run_doctor() == 0
    assert "pre_commit: pre-commit" in capsys.readouterr().out


def test_doctor_hook_as_existing_file_passes(healthy_env, capsys, tmp_path):
    script = tmp_path / "hook.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    with mock.patch("relay.doctor.hook_post_push", return_value=[str(script)]):
        assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "post_push" in out
    assert str(script) in out


def test_doctor_missing_hook_executable_warns(healthy_env, capsys):
    with mock.patch(
        "relay.doctor.hook_pre_commit", return_value=["no-such-hook-binary-xyz"]
    ):
        assert run_doctor() == 0  # a broken hook warns; it is not fatal
    out = capsys.readouterr().out
    assert "executable not found" in out
    assert "no-such-hook-binary-xyz" in out
    assert "WARN" in out


def test_doctor_hook_path_error_warns_instead_of_raising(healthy_env, capsys):
    """A hook path that makes Path.is_file() raise still degrades to a warn."""
    def which(name):
        return None if name == "weird" else r"C:\tools\git.exe"

    with mock.patch("relay.doctor.hook_pre_commit", return_value=["weird"]), mock.patch(
        "relay.doctor.shutil.which", side_effect=which
    ), mock.patch("relay.doctor.Path.is_file", side_effect=OSError("bad path")):
        assert run_doctor() == 0
    assert "executable not found" in capsys.readouterr().out


# ---- --json report ---------------------------------------------------------


def test_doctor_json_report_is_valid_and_has_expected_keys(healthy_env, capsys):
    code = run_doctor(json_output=True)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["relay"]
    assert payload["provider"] == "gemini"
    assert payload["exit_code"] == code == 0
    statuses = {c["name"]: c["status"] for c in payload["checks"]}
    assert statuses["AI credentials"] == "ok"
    assert statuses["User config"] == "ok"
    assert payload["summary"]["fail"] == 0
    assert set(payload["summary"]) == {"ok", "warn", "fail"}


def test_doctor_json_report_exit_code_matches_failures(healthy_env, capsys):
    with mock.patch("relay.doctor.gemini_api_key", return_value=None):
        code = run_doctor(json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["exit_code"] == 1
    assert payload["summary"]["fail"] >= 1


def test_doctor_json_report_has_no_human_header(healthy_env, capsys):
    run_doctor(json_output=True)
    out = capsys.readouterr().out
    assert out.lstrip().startswith("{")
    assert "[relay doctor]" not in out


def test_doctor_json_report_is_terminal_safe(healthy_env, capsys):
    evil = {"user.name": "\x1b[2J.evil", "user.email": "e@x.io"}
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit(config=evil)):
        run_doctor(json_output=True)
    out = capsys.readouterr().out
    assert "\x1b" not in out
    json.loads(out)  # sanitizing must not break the JSON contract


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


def test_main_doctor_json_flag_routes_to_run_doctor():
    with mock.patch("relay.cli.run_doctor", return_value=0) as run:
        assert main(["doctor", "--json"]) == 0
    run.assert_called_once_with(provider=None, verbose=False, json_output=True)


def test_main_doctor_accepts_provider_and_verbose():
    with mock.patch("relay.cli.run_doctor", return_value=0) as run:
        main(["doctor", "--provider", "ollama", "--verbose"])
    run.assert_called_once_with(provider="ollama", verbose=True)


def test_main_doctor_failure_is_not_fatal(capsys):
    with mock.patch("relay.cli.run_doctor", side_effect=RuntimeError("boom")):
        assert main(["doctor"]) == 1
    assert "error: boom" in capsys.readouterr().out


# ---- coverage: missing branches (moved from test_coverage_95) ----------------

def test_ollama_reachable_parse_exception():
    with mock.patch("relay.doctor.urllib.parse.urlparse", side_effect=ValueError("bad")):
        ok, detail = _ollama_reachable("http://localhost:11434")
        assert ok is False
        assert "cannot parse URL" in detail


def test_ollama_reachable_empty_host():
    ok, detail = _ollama_reachable("http://")
    assert ok is False
    assert "cannot parse URL" in detail


def test_ollama_reachable_https_default_port():
    with mock.patch("relay.doctor.socket.create_connection") as conn:
        ok, _ = _ollama_reachable("https://myhost/path")
        assert ok is True
        conn.assert_called_once_with(("myhost", 443), timeout=1)


def test_doctor_mistral_key_set():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="mistral"), \
         mock.patch("relay.doctor.mistral_api_key", return_value="test-key"), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 0


def test_doctor_mistral_missing_key():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="mistral"), \
         mock.patch("relay.doctor.mistral_api_key", return_value=None), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 1


def test_doctor_groq_key_set():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="groq"), \
         mock.patch("relay.doctor.groq_api_key", return_value="k"), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 0


def test_doctor_groq_missing():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="groq"), \
         mock.patch("relay.doctor.groq_api_key", return_value=None), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 1


def test_doctor_xai_key_set():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="xai"), \
         mock.patch("relay.doctor.xai_api_key", return_value="k"), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 0


def test_doctor_xai_missing():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="xai"), \
         mock.patch("relay.doctor.xai_api_key", return_value=None), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 1


def test_doctor_unknown_provider_warns_extra():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="unknown_xyz"), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 0


def test_doctor_probe_success(healthy_env, capsys):
    mock_resp = mock.MagicMock()
    mock_resp.read.return_value = b'{"login": "testuser"}'
    mock_resp.__enter__.return_value = mock_resp
    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        code = run_doctor(probe=True)
    assert code == 0
    out = capsys.readouterr().out
    assert "AI probe" in out
    assert "Forge probe" in out
    assert "authenticated" in out
    assert "@testuser" in out


def test_doctor_probe_ai_failure(healthy_env, capsys):
    import urllib.error
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        "https://api.test", 401, "Unauthorized", {}, None
    )):
        code = run_doctor(probe=True)
    assert code == 1
    out = capsys.readouterr().out
    assert "AI probe" in out
    assert "FAIL" in out
    assert "401" in out


def test_doctor_probe_skipped_when_key_missing(healthy_env, capsys):
    with mock.patch("relay.doctor.gemini_api_key", return_value=None), \
         mock.patch("relay.doctor.github_token", return_value=None):
        code = run_doctor(probe=True)
    # AI credentials check fails, probe skips
    assert code == 1
    out = capsys.readouterr().out
    assert "AI probe" in out
    assert "SKIP" in out


def test_doctor_probe_various_providers(healthy_env, capsys):
    mock_resp = mock.MagicMock()
    mock_resp.read.return_value = b"{}"
    mock_resp.__enter__.return_value = mock_resp

    for prov in ("openai", "anthropic", "ollama", "mistral", "groq", "xai"):
        with mock.patch("urllib.request.urlopen", return_value=mock_resp), \
             mock.patch(
                 f"relay.doctor.{prov}_api_key" if prov != "ollama" else "relay.doctor.ollama_base_url",
                 return_value="http://localhost:11434" if prov == "ollama" else "dummy_key",
             ), \
             mock.patch("relay.doctor._ollama_reachable", return_value=(True, "reachable")), \
             mock.patch("relay.doctor.github_token", return_value=None):
            run_doctor(provider=prov, probe=True)


def test_doctor_probe_forges_gitlab_and_bitbucket(healthy_env, capsys):
    mock_resp = mock.MagicMock()
    mock_resp.read.return_value = b'{"username": "forge_user"}'
    mock_resp.__enter__.return_value = mock_resp

    with mock.patch("urllib.request.urlopen", return_value=mock_resp), \
         mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value="gl_tok"):
        code = run_doctor(probe=True)
        assert code == 0
        assert "GitLab @forge_user" in capsys.readouterr().out

    with mock.patch("urllib.request.urlopen", return_value=mock_resp), \
         mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value="bb_tok"):
        code = run_doctor(probe=True)
        assert code == 0
        assert "Bitbucket @forge_user" in capsys.readouterr().out


def test_doctor_probe_rejects_oversized_forge_body(healthy_env, capsys):
    """L6: probe bodies are capped like every other HTTP read (10 KiB)."""
    from relay.doctor import _MAX_PROBE_BODY_BYTES

    mock_resp = mock.MagicMock()
    mock_resp.read.return_value = b"x" * (_MAX_PROBE_BODY_BYTES + 100)
    mock_resp.__enter__.return_value = mock_resp
    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        run_doctor(probe=True)
    out = capsys.readouterr().out
    assert "Forge probe" in out
    assert "too large" in out


# ---- keyed-provider credential table (dispatch-table refactor) --------------


def test_keyed_provider_table_covers_all_keyed_providers():
    """Single source of truth for keyed providers: label + key fn + env name."""
    import relay.doctor as doctor_mod
    from relay.doctor import _KEYED_PROVIDERS

    assert set(_KEYED_PROVIDERS) == {
        "gemini",
        "openai",
        "anthropic",
        "mistral",
        "groq",
        "xai",
    }
    for prov, (label, key_attr, env) in _KEYED_PROVIDERS.items():
        assert label, prov
        assert callable(getattr(doctor_mod, key_attr)), prov
        assert env == f"{prov.upper()}_API_KEY", prov


@pytest.mark.parametrize(
    "prov,env",
    [
        ("gemini", "GEMINI_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("xai", "XAI_API_KEY"),
    ],
)
def test_keyed_providers_share_set_missing_message_convention(
    healthy_env, capsys, prov, env
):
    """Table refactor must preserve the exact '<ENV> is set / is not set' UX."""
    with mock.patch(
        "relay.doctor.provider_from_env", return_value=prov
    ), mock.patch(f"relay.doctor.{prov}_api_key", return_value="k"):
        assert run_doctor() == 0
    assert f"{env} is set" in capsys.readouterr().out

    with mock.patch(
        "relay.doctor.provider_from_env", return_value=prov
    ), mock.patch(f"relay.doctor.{prov}_api_key", return_value=None):
        assert run_doctor() == 1
    assert f"{env} is not set" in capsys.readouterr().out


# ---- probe miss-branch coverage -------------------------------------------


def _ok_probe_response(body: bytes = b"{}"):
    """A context-manager HTTP response stub for probe tests (no network)."""
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return resp


def test_probe_gemini_aq_key_uses_bearer_auth():
    """Gemini keys starting with 'AQ.' authenticate via a Bearer header."""
    with mock.patch("relay.doctor.gemini_api_key", return_value="AQ.test-token"), \
         mock.patch("urllib.request.urlopen", return_value=_ok_probe_response()) as urlopen:
        check = _probe_provider("gemini")
    assert check.status == "ok"
    headers = {k.lower(): v for k, v in urlopen.call_args.args[0].header_items()}
    assert headers.get("authorization") == "Bearer AQ.test-token"


def test_probe_groq_missing_key_skips():
    """OpenAI-compatible providers skip the probe when their key is missing."""
    with mock.patch("relay.doctor.groq_api_key", return_value=None):
        check = _probe_provider("groq")
    assert check.status == "skip"
    assert "GROQ_API_KEY is not set" in check.detail


def test_probe_anthropic_missing_key_skips():
    """The Anthropic probe skips when its key is missing."""
    with mock.patch("relay.doctor.anthropic_api_key", return_value=None):
        check = _probe_provider("anthropic")
    assert check.status == "skip"
    assert "ANTHROPIC_API_KEY is not set" in check.detail


def test_probe_unknown_provider_skips():
    """Unknown provider names skip the probe instead of probing anything."""
    check = _probe_provider("watson")
    assert check.status == "skip"
    assert "unknown provider 'watson'" in check.detail


def test_probe_ai_connection_failure_fails():
    """Non-HTTP probe errors degrade to FAIL, never raise out of the probe."""
    with mock.patch("relay.doctor.gemini_api_key", return_value="test-key"), \
         mock.patch("urllib.request.urlopen", side_effect=OSError("dns boom")):
        check = _probe_provider("gemini")
    assert check.status == "fail"
    assert "connection failed" in check.detail


def test_probe_forge_github_connection_failure():
    """The GitHub probe maps transport errors to FAIL."""
    with mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("urllib.request.urlopen", side_effect=OSError("reset")):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "GitHub connection failed" in check.detail


def test_probe_forge_gitlab_oversized_body_fails():
    """The GitLab probe rejects bodies over the probe cap."""
    from relay.doctor import _MAX_PROBE_BODY_BYTES

    big = _ok_probe_response(b"x" * (_MAX_PROBE_BODY_BYTES + 1))
    with mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value="gl_tok"), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("urllib.request.urlopen", return_value=big):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "GitLab response too large" in check.detail


def test_probe_forge_gitlab_http_error_fails():
    """The GitLab probe maps HTTP errors to FAIL."""
    import urllib.error

    err = urllib.error.HTTPError("https://gitlab.test", 403, "Forbidden", {}, None)
    with mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value="gl_tok"), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("urllib.request.urlopen", side_effect=err):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "GitLab HTTP 403" in check.detail


def test_probe_forge_gitlab_connection_failure():
    """The GitLab probe maps transport errors to FAIL."""
    with mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value="gl_tok"), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "GitLab connection failed" in check.detail


def test_probe_forge_bitbucket_oversized_body_fails():
    """The Bitbucket probe rejects bodies over the probe cap."""
    from relay.doctor import _MAX_PROBE_BODY_BYTES

    big = _ok_probe_response(b"x" * (_MAX_PROBE_BODY_BYTES + 1))
    with mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value="bb_tok"), \
         mock.patch("urllib.request.urlopen", return_value=big):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "Bitbucket response too large" in check.detail


def test_probe_forge_bitbucket_http_error_fails():
    """The Bitbucket probe maps HTTP errors to FAIL."""
    import urllib.error

    err = urllib.error.HTTPError(
        "https://bitbucket.test", 401, "Unauthorized", {}, None
    )
    with mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value="bb_tok"), \
         mock.patch("urllib.request.urlopen", side_effect=err):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "Bitbucket HTTP 401" in check.detail


def test_probe_forge_bitbucket_connection_failure():
    """The Bitbucket probe maps transport errors to FAIL."""
    with mock.patch("relay.doctor.github_token", return_value=None), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value="bb_tok"), \
         mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        check = _probe_forge()
    assert check is not None
    assert check.status == "fail"
    assert "Bitbucket connection failed" in check.detail


# ---- _probe_forge_endpoint: shared forge-probe reader --------------------------


def test_probe_forge_endpoint_skips_without_token():
    """No token means no probe for that forge."""
    check = _probe_forge_endpoint(
        label="GitHub",
        token=None,
        url="https://api.github.com/user",
        headers={},
        user_field="login",
    )
    assert check is None


def test_probe_forge_endpoint_reports_user():
    """A reachable endpoint reports the forge user."""
    resp = _ok_probe_response(b'{"login": "octo"}')
    with mock.patch("urllib.request.urlopen", return_value=resp):
        check = _probe_forge_endpoint(
            label="GitHub",
            token="tok",
            url="https://api.github.com/user",
            headers={},
            user_field="login",
        )
    assert check is not None
    assert check.status == "ok"
    assert "GitHub @octo" in check.detail


