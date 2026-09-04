"""Unit tests for relay/config.py — env-driven settings and the safety caps
(30s HTTP timeout default, 120s hard cap, 120-line diff budget)."""
import textwrap

import pytest

from relay import config


@pytest.fixture(autouse=True)
def clear_relay_env(monkeypatch):
    """Make every test start from a clean Relay environment."""
    config._RAW_CACHE.clear()  # the parsed-file cache is keyed by path+mtime+size
    config._LOCAL_CACHE.clear()
    for key in (
        "RELAY_AI_TIMEOUT",
        "RELAY_MAX_DIFF_LINES",
        "RELAY_AI_PROVIDER",
        "RELAY_BRANCH_TEMPLATE",
        "RELAY_PR_OPEN",
        "RELAY_CONFIG",
        "RELAY_LOCAL_CONFIG",
        "RELAY_PROTECTED_BRANCHES",
        "RELAY_TRUSTED_GITLAB_HOSTS",
        "XDG_CONFIG_HOME",
        "APPDATA",
        "GEMINI_MODEL",
        "OLLAMA_MODEL",
        "OLLAMA_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "MISTRAL_MODEL",
        "MISTRAL_BASE_URL",
        "GROQ_MODEL",
        "GROQ_BASE_URL",
        "XAI_MODEL",
        "XAI_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def _write_toml(monkeypatch, tmp_path, body: str) -> None:
    """Point RELAY_CONFIG at a fresh TOML file and write it."""
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setenv("RELAY_CONFIG", str(p))


def test_python_310_fallback_parser_supplies_values(monkeypatch, tmp_path):
    """Simulate Python 3.10 (no stdlib tomllib): the bundled relay/toml.py must
    power the config file end-to-end, exactly as tomllib does on 3.11+."""
    from relay import toml

    monkeypatch.setattr(config, "_load_toml", toml.load)
    monkeypatch.setattr(config, "_TOML_DECODE_ERROR", ValueError)
    _write_toml(
        monkeypatch,
        tmp_path,
        """
        [relay]
        provider = "ollama"
        branch_template = "release/<feature>"
        ai_timeout = 55
        max_diff_lines = 250
        """,
    )
    assert config.provider_from_env() == "ollama"
    assert config.branch_template() == "release/<feature>"
    assert config.ai_timeout() == 55
    assert config.max_diff_lines() == 250


def test_default_timeout_is_30_seconds():
    assert config.ai_timeout() == 30


def test_timeout_is_capped_at_120_seconds(monkeypatch):
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "999")
    assert config.ai_timeout() == 120


def test_reasonable_override_passes_through(monkeypatch):
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "45")
    assert config.ai_timeout() == 45


def test_timeout_has_a_positive_floor(monkeypatch):
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "0")
    assert config.ai_timeout() == 1


def test_invalid_timeout_falls_back_to_default(monkeypatch, capsys):
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "banana")
    assert config.ai_timeout() == 30
    assert "RELAY_AI_TIMEOUT" in capsys.readouterr().err


def test_explicit_override_beats_env(monkeypatch):
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "5")
    assert config.ai_timeout(override=60) == 60


def test_override_is_still_clamped():
    assert config.ai_timeout(override=99999) == 120
    assert config.ai_timeout(override=0) == 1


def test_max_diff_lines_default_and_override(monkeypatch):
    assert config.max_diff_lines() == 120
    monkeypatch.setenv("RELAY_MAX_DIFF_LINES", "150")
    assert config.max_diff_lines() == 150


def test_file_timeout_is_still_clamped(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ai_timeout = 99999
    """)
    assert config.ai_timeout() == 120


def test_openai_settings_defaults_then_env(monkeypatch):
    assert config.openai_model() == config.DEFAULT_OPENAI_MODEL
    assert config.openai_base_url() == config.DEFAULT_OPENAI_BASE_URL
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8080/v1")
    assert config.openai_model() == "gpt-4o"
    assert config.openai_base_url() == "http://localhost:8080/v1"


def test_anthropic_settings_defaults_then_env(monkeypatch):
    assert config.anthropic_model() == config.DEFAULT_ANTHROPIC_MODEL
    assert config.anthropic_base_url() == config.DEFAULT_ANTHROPIC_BASE_URL
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.local/v1")
    assert config.anthropic_model() == "claude-opus-4"
    assert config.anthropic_base_url() == "https://gateway.local/v1"


def test_mistral_settings_defaults_then_env(monkeypatch):
    assert config.mistral_model() == config.DEFAULT_MISTRAL_MODEL
    assert config.mistral_base_url() == config.DEFAULT_MISTRAL_BASE_URL
    monkeypatch.setenv("MISTRAL_MODEL", "mistral-large-latest")
    monkeypatch.setenv("MISTRAL_BASE_URL", "https://gateway.local/v1")
    assert config.mistral_model() == "mistral-large-latest"
    assert config.mistral_base_url() == "https://gateway.local/v1"


def test_groq_settings_defaults_then_env(monkeypatch):
    assert config.groq_model() == config.DEFAULT_GROQ_MODEL
    assert config.groq_base_url() == config.DEFAULT_GROQ_BASE_URL
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setenv("GROQ_BASE_URL", "https://gateway.local/v1")
    assert config.groq_model() == "llama-3.1-8b-instant"
    assert config.groq_base_url() == "https://gateway.local/v1"


def test_xai_settings_defaults_then_env(monkeypatch):
    assert config.xai_model() == config.DEFAULT_XAI_MODEL
    assert config.xai_base_url() == config.DEFAULT_XAI_BASE_URL
    monkeypatch.setenv("XAI_MODEL", "grok-2-latest")
    monkeypatch.setenv("XAI_BASE_URL", "https://gateway.local/v1")
    assert config.xai_model() == "grok-2-latest"
    assert config.xai_base_url() == "https://gateway.local/v1"


def test_api_keys_are_env_only(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        openai_api_key = "leaked"
        anthropic_api_key = "leaked"
        mistral_api_key = "leaked"
        groq_api_key = "leaked"
        xai_api_key = "leaked"
    """)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert config.openai_api_key() is None
    assert config.anthropic_api_key() is None
    assert config.mistral_api_key() is None
    assert config.groq_api_key() is None
    assert config.xai_api_key() is None


def test_base_urls_are_env_only(monkeypatch, tmp_path):
    """Credential-bearing base URLs must never be read from an untrusted config file."""
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ollama_base_url = "http://evil.example"
        openai_base_url = "http://evil.example"
        anthropic_base_url = "http://evil.example"
        mistral_base_url = "http://evil.example"
        groq_base_url = "http://evil.example"
        xai_base_url = "http://evil.example"
    """)
    for key in (
        "OLLAMA_BASE_URL",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "MISTRAL_BASE_URL",
        "GROQ_BASE_URL",
        "XAI_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    assert config.ollama_base_url() == config.DEFAULT_OLLAMA_BASE_URL
    assert config.openai_base_url() == config.DEFAULT_OPENAI_BASE_URL
    assert config.anthropic_base_url() == config.DEFAULT_ANTHROPIC_BASE_URL
    assert config.mistral_base_url() == config.DEFAULT_MISTRAL_BASE_URL
    assert config.groq_base_url() == config.DEFAULT_GROQ_BASE_URL
    assert config.xai_base_url() == config.DEFAULT_XAI_BASE_URL


def test_invalid_max_diff_lines_falls_back_to_default(monkeypatch, capsys):
    monkeypatch.setenv("RELAY_MAX_DIFF_LINES", "huge")
    assert config.max_diff_lines() == 120
    assert "RELAY_MAX_DIFF_LINES" in capsys.readouterr().err


def test_max_diff_lines_has_a_positive_floor(monkeypatch):
    """A cap of 0 (or negative) would send the AI an empty/absurd prompt;
    clamp to at least 1 line (M-02)."""
    monkeypatch.setenv("RELAY_MAX_DIFF_LINES", "0")
    assert config.max_diff_lines() == 1
    monkeypatch.setenv("RELAY_MAX_DIFF_LINES", "-5")
    assert config.max_diff_lines() == 1


def test_max_diff_lines_wrong_typed_config_value_falls_back(monkeypatch, tmp_path):
    """Regression: a non-int TOML entry (bool / list) used to raise TypeError
    (uncaught, since only ValueError was caught) and crashed instead of falling
    back to the default — mirroring ai_timeout()'s tolerant parse."""
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        max_diff_lines = [1, 2]
    """)
    assert config.max_diff_lines() == 120

    _write_toml(monkeypatch, tmp_path, """
        [relay]
        max_diff_lines = true
    """)
    assert config.max_diff_lines() == 120


# ---- Protected-branch rules (default-branch safety) --------------------------


def test_protected_branches_defaults_to_main_and_master():
    assert config.protected_branches() == ["main", "master"]


def test_protected_branches_read_from_env(monkeypatch):
    monkeypatch.setenv("RELAY_PROTECTED_BRANCHES", "main, develop")
    assert config.protected_branches() == ["main", "develop"]


def test_protected_branches_env_beats_file(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [team.protected]
        branches = ["release"]
    """)
    monkeypatch.setenv("RELAY_PROTECTED_BRANCHES", "main")
    assert config.protected_branches() == ["main"]


def test_protected_branches_read_from_toml(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [team.protected]
        branches = ["main", "develop"]
    """)
    assert config.protected_branches() == ["main", "develop"]


def test_protected_branches_empty_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RELAY_PROTECTED_BRANCHES", "   ")
    assert config.protected_branches() == ["main", "master"]


def test_protected_branches_absent_file_falls_back_to_default(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        provider = "ollama"
    """)
    assert config.protected_branches() == ["main", "master"]


def test_protected_branches_empty_file_list_falls_back_to_default(monkeypatch, tmp_path):
    """A config file that explicitly lists zero branches means 'no override',
    so the built-in default (main, master) still applies."""
    _write_toml(monkeypatch, tmp_path, """
        [team.protected]
        branches = []
    """)
    assert config.protected_branches() == ["main", "master"]


def test_forge_tokens_are_env_only(monkeypatch, tmp_path):
    """NFR: forge tokens are never read from the config file; a config file
    that declares them must have no effect on the env-only getters."""
    from relay.bitbucket import bitbucket_token
    from relay.github import github_token
    from relay.gitlab import gitlab_token

    _write_toml(monkeypatch, tmp_path, """
        [relay]
        github_token = "leaked"
        gitlab_token = "leaked"
        bitbucket_token = "leaked"
    """)
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "CI_JOB_TOKEN", "BITBUCKET_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert github_token() is None
    assert gitlab_token() is None
    assert bitbucket_token() is None


# ---- GitLab host trust boundary (credential-exfiltration hardening) ----------


def test_trusted_gitlab_hosts_defaults_to_gitlab_com():
    assert config.trusted_gitlab_hosts() == ["gitlab.com"]


def test_trusted_gitlab_hosts_env_is_additive(monkeypatch):
    """gitlab.com stays trusted; the env var only adds hosts, so a mis-set
    value can never accidentally break the canonical host."""
    monkeypatch.setenv(
        "RELAY_TRUSTED_GITLAB_HOSTS", "gitlab.example.com, git.company.io"
    )
    assert config.trusted_gitlab_hosts() == [
        "gitlab.com",
        "gitlab.example.com",
        "git.company.io",
    ]


def test_trusted_gitlab_hosts_env_lowercases_and_dedupes(monkeypatch):
    monkeypatch.setenv(
        "RELAY_TRUSTED_GITLAB_HOSTS", "GitLab.Example.COM gitlab.example.com gitlab.com"
    )
    assert config.trusted_gitlab_hosts() == ["gitlab.com", "gitlab.example.com"]


def test_trusted_gitlab_hosts_config_file_is_ignored(monkeypatch, tmp_path):
    """Config-file `trusted_gitlab_hosts` is ignored (env-only) so an untrusted
    repo-local config cannot expand credential destinations."""
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        trusted_gitlab_hosts = ["gitlab.internal.example", "gitlab.example.com"]
    """)
    assert config.trusted_gitlab_hosts() == ["gitlab.com"]


def test_trusted_gitlab_hosts_env_beats_file(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        trusted_gitlab_hosts = ["gitlab.internal.example"]
    """)
    monkeypatch.setenv("RELAY_TRUSTED_GITLAB_HOSTS", "gitlab.example.com")
    assert config.trusted_gitlab_hosts() == ["gitlab.com", "gitlab.example.com"]


def test_trusted_gitlab_hosts_empty_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RELAY_TRUSTED_GITLAB_HOSTS", "   ")
    assert config.trusted_gitlab_hosts() == ["gitlab.com"]


def test_trusted_gitlab_hosts_absent_file_falls_back_to_default(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        provider = "ollama"
    """)
    assert config.trusted_gitlab_hosts() == ["gitlab.com"]


def test_trusted_gitlab_hosts_empty_file_list_is_ignored(monkeypatch, tmp_path):
    """An explicit empty list means 'no extra hosts', not 'trust nothing'."""
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        trusted_gitlab_hosts = []
    """)
    assert config.trusted_gitlab_hosts() == ["gitlab.com"]


def test_ai_default_supplies_provider_from_file(monkeypatch, tmp_path):
    """The [ai] table is a dedicated knob for the default provider."""
    _write_toml(monkeypatch, tmp_path, """
        [ai]
        default = "ollama"
    """)
    assert config.provider_from_env() == "ollama"


def test_relay_provider_beats_ai_default(monkeypatch, tmp_path):
    """The existing [relay] provider key stays the higher-precedence file knob."""
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        provider = "gemini"

        [ai]
        default = "ollama"
    """)
    assert config.provider_from_env() == "gemini"


def test_env_beats_ai_default(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [ai]
        default = "ollama"
    """)
    monkeypatch.setenv("RELAY_AI_PROVIDER", "openai")
    assert config.provider_from_env() == "openai"


def test_ai_default_absent_falls_back_to_builtin(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [team.protected]
        branches = ["main"]
    """)
    assert config.provider_from_env() == config.DEFAULT_PROVIDER


def test_ai_default_supported_by_internal_toml_parser(monkeypatch, tmp_path):
    """The bundled Python 3.10 TOML fallback must handle the [ai] table too."""
    from relay import toml

    monkeypatch.setattr(config, "_load_toml", toml.load)
    monkeypatch.setattr(config, "_TOML_DECODE_ERROR", ValueError)
    _write_toml(monkeypatch, tmp_path, """
        [ai]
        default = "ollama"
    """)
    assert config.provider_from_env() == "ollama"


# ---- F6: TOML config file (flags > env > file > defaults) --------------------


def test_no_config_file_uses_defaults(monkeypatch, tmp_path):
    assert config.branch_template() == config.DEFAULT_BRANCH_TEMPLATE
    assert config.gemini_model() == config.DEFAULT_GEMINI_MODEL


def test_file_supplies_values_when_env_unset(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        provider = "ollama"
        branch_template = "release/<feature>"
        gemini_model = "gemini-other"
        ai_timeout = 55
        max_diff_lines = 250
        pr_open = true
    """)
    assert config.provider_from_env() == "ollama"
    assert config.branch_template() == "release/<feature>"
    assert config.gemini_model() == "gemini-other"
    assert config.ai_timeout() == 55
    assert config.max_diff_lines() == 250
    assert config.pr_open_browser() is True


def test_env_beats_file(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ai_timeout = 55
    """)
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "10")
    assert config.ai_timeout() == 10


def test_secret_keys_never_read_from_file(monkeypatch, tmp_path):
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        gemini_api_key = "leaked"
    """)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.gemini_api_key() is None


def test_missing_file_still_uses_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_CONFIG", str(tmp_path / "nope.toml"))
    assert config.ai_timeout() == 30


def test_invalid_toml_warns_and_falls_back_to_defaults(monkeypatch, tmp_path, capsys):
    """L-15: a malformed config file must be visible, not silently dropped."""
    monkeypatch.setenv("RELAY_CONFIG", str(tmp_path / "bad.toml"))
    p = tmp_path / "bad.toml"
    p.write_text("not [valid", encoding="utf-8")
    assert config.ai_timeout() == 30
    err = capsys.readouterr().err
    assert "malformed config file" in err
    assert str(p) in err


def test_invalid_toml_warning_printed_once_per_state(monkeypatch, tmp_path, capsys):
    """The malformed-file warning must not repeat for every getter."""
    monkeypatch.setenv("RELAY_CONFIG", str(tmp_path / "bad.toml"))
    p = tmp_path / "bad.toml"
    p.write_text("not [valid", encoding="utf-8")
    config.ai_timeout()
    config.max_diff_lines()
    config.branch_template()
    config.protected_branches()
    err = capsys.readouterr().err
    assert err.count("malformed config file") == 1


# ---- H-08: the parsed config file is cached until it changes ------------------


def test_config_file_is_read_once_per_state(monkeypatch, tmp_path):
    """Multiple getters must not re-open the file when it hasn't changed."""
    import builtins

    from relay import config as cfg

    _write_toml(monkeypatch, tmp_path, """
        [relay]
        provider = "ollama"
        ai_timeout = 55
        branch_template = "release/<feature>"
    """)
    opened = []
    real_open = builtins.open

    def counting_open(file, *args, **kwargs):
        opened.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    cfg._RAW_CACHE.clear()

    assert cfg.provider_from_env() == "ollama"
    assert cfg.ai_timeout() == 55
    assert cfg.branch_template() == "release/<feature>"

    assert len(opened) == 1


def test_config_file_cache_invalidates_on_change(monkeypatch, tmp_path):
    """Rewriting the file (different mtime/size) must re-parse it."""
    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ai_timeout = 55
    """)
    assert config.ai_timeout() == 55

    _write_toml(monkeypatch, tmp_path, """
        [relay]
        ai_timeout = 77
        max_diff_lines = 200
    """)
    assert config.ai_timeout() == 77
    assert config.max_diff_lines() == 200


def test_repo_local_config_precedence(monkeypatch, tmp_path):
    """Repo-local .relay.toml overrides user config.toml, but env vars win over both."""
    user_cfg = tmp_path / "user_config.toml"
    user_cfg.write_text(textwrap.dedent("""
        [relay]
        provider = "gemini"
        ai_timeout = 40
        branch_template = "user/<feature>"
    """), encoding="utf-8")
    monkeypatch.setenv("RELAY_CONFIG", str(user_cfg))

    local_cfg = tmp_path / ".relay.toml"
    local_cfg.write_text(textwrap.dedent("""
        [relay]
        provider = "openai"
        ai_timeout = 50
    """), encoding="utf-8")
    monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(local_cfg))

    assert config.provider_from_env() == "openai"
    assert config.ai_timeout() == 50
    assert config.branch_template() == "user/<feature>"  # falls through to user config

    # Env var overrides repo-local config
    monkeypatch.setenv("RELAY_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("RELAY_AI_TIMEOUT", "60")
    assert config.provider_from_env() == "anthropic"
    assert config.ai_timeout() == 60


def test_repo_local_config_security_allowlist_blocks_hooks_and_endpoints(monkeypatch, tmp_path, capsys):
    """Security boundary: .relay.toml must never allow hooks, base URLs, or secrets."""
    local_cfg = tmp_path / ".relay.toml"
    local_cfg.write_text(textwrap.dedent("""
        [hooks.pre_commit]
        command = ["malicious", "command"]

        [relay]
        openai_base_url = "https://evil-phishing.com/v1"
        pre_commit_hook = "evil"
        provider = "openai"

        [ai]
        openai_model = "gpt-4o"
    """), encoding="utf-8")
    monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(local_cfg))

    # Hooks must remain None
    assert config.hook_pre_commit() is None
    # Base URL must remain safe default
    assert config.openai_base_url() == config.DEFAULT_OPENAI_BASE_URL
    # Safe keys are honored
    assert config.provider_from_env() == "openai"
    assert config.openai_model() == "gpt-4o"

    err = capsys.readouterr().err
    assert "security-restricted" in err


def test_repo_local_config_ignore_paths_and_protected_branches(monkeypatch, tmp_path):
    """Repo-local ignore paths and protected branches are loaded safely."""
    local_cfg = tmp_path / ".relay.toml"
    local_cfg.write_text(textwrap.dedent("""
        [relay.ignore]
        paths = ["*.min.js", "dist/*"]

        [team.protected]
        branches = ["production", "release"]
    """), encoding="utf-8")
    monkeypatch.setenv("RELAY_LOCAL_CONFIG", str(local_cfg))

    assert config.ignore_paths() == ["*.min.js", "dist/*"]
    assert config.protected_branches() == ["production", "release"]

