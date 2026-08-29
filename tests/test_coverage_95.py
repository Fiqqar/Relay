"""Coverage boost to reach 95% branch and 90% per-file minimum.

Covers missing branches in doctor, git_manager, pr, telemetry, ollama and
other low-coverage files identified in the 92% → 95% audit.
"""
import json
import urllib.error
import urllib.request
from unittest import mock

import pytest

from relay import telemetry
from relay.ai.ollama import OllamaProvider
from relay.doctor import _ollama_reachable, run_doctor
from relay.git_manager import GitManager
from relay.pr import _existing_url, _host_web_base, _pr_web_url, _safe_open_browser
from tests.test_doctor import FakeGit

# ---- doctor: _ollama_reachable exception path (81-82) -----------------------

def test_ollama_reachable_parse_exception(monkeypatch):
    # Force urlparse to raise ValueError to hit the except branch
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


# ---- doctor: mistral / groq / xai / unknown provider (183-211) --------------

def _healthy_doctor_mock(provider, key_return):
    # helper to run doctor with a given provider and key
    key_map = {
        "mistral": "relay.doctor.mistral_api_key",
        "groq": "relay.doctor.groq_api_key",
        "xai": "relay.doctor.xai_api_key",
    }
    p = mock.patch("relay.doctor.provider_from_env", return_value=provider)
    k = mock.patch(key_map[provider], return_value=key_return)
    return p, k


def test_doctor_mistral_key_set(healthy_mistral_env=None):
    # Use the healthy_env pattern but override provider
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


def test_doctor_unknown_provider_warns():
    with mock.patch("relay.doctor.GitManager", return_value=FakeGit()), \
         mock.patch("relay.doctor._git_version", return_value="2.42.0"), \
         mock.patch("relay.doctor.shutil.which", return_value="/usr/bin/git"), \
         mock.patch("relay.doctor.provider_from_env", return_value="unknown_xyz"), \
         mock.patch("relay.doctor.github_token", return_value="tok"), \
         mock.patch("relay.doctor.gitlab_token", return_value=None), \
         mock.patch("relay.doctor.bitbucket_token", return_value=None), \
         mock.patch("relay.doctor.protected_branches", return_value=["main"]):
        assert run_doctor() == 0


# ---- git_manager: empty-repo head_diff / head_stat / binary --------------

class FakeRun:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


def test_head_diff_empty_repo_fallback():
    git = GitManager()
    # HEAD fails, then staged+unstaged succeed
    def fake_run(*args, **kw):
        if args == ("diff", "HEAD", "--unified=0"):
            return FakeRun("", returncode=128)
        if args == ("diff", "--cached", "--unified=0"):
            return FakeRun("cached diff\n")
        if args == ("diff", "--unified=0"):
            return FakeRun("unstaged diff\n")
        return FakeRun("")
    with mock.patch.object(git, "_run", side_effect=fake_run):
        assert git.head_diff() == "cached diff\nunstaged diff"


def test_head_diff_empty_repo_both_empty():
    git = GitManager()
    def fake_run(*args, **kw):
        if args == ("diff", "HEAD", "--unified=0"):
            return FakeRun("", returncode=128)
        return FakeRun("")
    with mock.patch.object(git, "_run", side_effect=fake_run):
        assert git.head_diff() == ""


def test_head_stat_empty_repo():
    git = GitManager()
    def fake_run(*args, **kw):
        if args == ("diff", "HEAD", "--stat"):
            return FakeRun("", returncode=128)
        if args == ("diff", "--cached", "--stat"):
            return FakeRun(" 1 file | 1 +\n")
        if args == ("diff", "--stat"):
            return FakeRun(" 1 file | 1 +\n")
        return FakeRun("")
    with mock.patch.object(git, "_run", side_effect=fake_run):
        assert "1 file" in git.head_stat()


def test_head_diff_binary_empty_repo():
    git = GitManager()
    def fake_run(*args, **kw):
        if args == ("diff", "HEAD", "--numstat"):
            return FakeRun("", returncode=128)
        if args == ("diff", "--cached", "--numstat"):
            return FakeRun("-\t-\timg.png\n")
        if args == ("diff", "--numstat"):
            return FakeRun("10\t0\tfile.py\n")
        return FakeRun("")
    with mock.patch.object(git, "_run", side_effect=fake_run):
        # mixed binary + text => not binary-only
        assert git.head_diff_binary_only() is False


def test_head_diff_binary_all_binary_empty_repo():
    git = GitManager()
    def fake_run(*args, **kw):
        if args == ("diff", "HEAD", "--numstat"):
            return FakeRun("", returncode=128)
        if args == ("diff", "--cached", "--numstat"):
            return FakeRun("-\t-\timg.png\n")
        if args == ("diff", "--numstat"):
            return FakeRun("-\t-\tb.png\n")
        return FakeRun("")
    with mock.patch.object(git, "_run", side_effect=fake_run):
        assert git.head_diff_binary_only() is True


def test_head_diff_binary_empty_no_lines():
    git = GitManager()
    def fake_run(*args, **kw):
        if args == ("diff", "HEAD", "--numstat"):
            return FakeRun("", returncode=0)
        return FakeRun("\n")
    with mock.patch.object(git, "_run", side_effect=fake_run):
        assert git.head_diff_binary_only() is False


def test_unstaged_changes_short_line():
    git = GitManager()
    # line shorter than 3 should be skipped (276)
    with mock.patch.object(git, "_run", return_value=FakeRun("ab\n?? file.py\n")):
        files = git.unstaged_changes()
        assert "file.py" in files
        assert len(files) == 1


# ---- telemetry -------------------------------------------------------------

def test_is_local_or_private_host_localhost():
    assert telemetry._is_local_or_private_host("localhost") is True
    assert telemetry._is_local_or_private_host("foo.localhost") is True
    assert telemetry._is_local_or_private_host("example.com") is False


def test_is_local_private_ip():
    assert telemetry._is_local_or_private_host("127.0.0.1") is True
    assert telemetry._is_local_or_private_host("10.0.0.1") is True
    assert telemetry._is_local_or_private_host("192.168.1.1") is True
    assert telemetry._is_local_or_private_host("8.8.8.8") is False


def test_is_https_rejects_private():
    assert telemetry._is_https("http://example.com") is False
    assert telemetry._is_https("https://127.0.0.1/collect") is False
    assert telemetry._is_https("https://example.com/collect") is True
    assert telemetry._is_https("https://localhost/collect") is False
    assert telemetry._is_https("not-a-url") is False
    assert telemetry._is_https("https://") is False


def test_is_valid_ai_base_url():
    assert telemetry._is_valid_ai_base_url("https://api.openai.com/v1") is True
    assert telemetry._is_valid_ai_base_url("http://localhost:11434") is True
    assert telemetry._is_valid_ai_base_url("http://127.0.0.1:11434") is True
    assert telemetry._is_valid_ai_base_url("http://10.0.0.1/v1") is False
    assert telemetry._is_valid_ai_base_url("http://example.com/v1") is False
    assert telemetry._is_valid_ai_base_url("https://10.0.0.1/v1") is False
    assert telemetry._is_valid_ai_base_url("ftp://example.com") is False
    assert telemetry._is_valid_ai_base_url("https://") is False
    assert telemetry._is_valid_ai_base_url("https://example.com") is True
    # exact localhost allowed over http, but not https://foo.localhost case
    assert telemetry._is_valid_ai_base_url("http://[::1]:11434") is True


def test_safe_redirect_handler_rejects_private():
    h = telemetry._SafeRedirectHandler()
    assert h.redirect_request(None, None, 302, "", {}, "https://127.0.0.1/") is None
    assert h.redirect_request(None, None, 302, "", {}, "http://example.com") is None


def test_send_payload_no_url(monkeypatch):
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "")
    telemetry._send_payload({"event": "test"})  # should not raise


def test_send_payload_invalid_url(monkeypatch):
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "http://example.com")
    telemetry._send_payload({"event": "test"})  # not https, no send


def test_report_without_url(monkeypatch):
    monkeypatch.setenv("RELAY_TELEMETRY", "1")
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "")
    telemetry.report(mode="solo", provider="gemini", ok=True)


def test_report_with_private_url(monkeypatch, capsys):
    monkeypatch.setenv("RELAY_TELEMETRY", "1")
    monkeypatch.setenv("RELAY_TELEMETRY_URL", "https://127.0.0.1/collect")
    telemetry.report(mode="solo", provider="gemini", ok=True)
    # should warn
    assert "warning" in capsys.readouterr().err.lower()


# ---- pr: missing branches --------------------------------------------------

def test_safe_open_browser_rejects():
    assert _safe_open_browser("") is False
    assert _safe_open_browser("file:///etc/passwd") is False
    assert _safe_open_browser("ftp://example.com") is False


def test_host_web_base():
    assert _host_web_base("github.com", "o", "r") == "https://github.com/o/r/pulls"
    assert _host_web_base("bitbucket.org", "o", "r") == "https://bitbucket.org/o/r/pull-requests"
    assert _host_web_base("gitlab.example.com", "o", "r") == "https://gitlab.example.com/o/r/-/merge_requests"


def test_pr_web_url():
    assert _pr_web_url("github.com", "o", "r", 42) == "https://github.com/o/r/pull/42"
    assert _pr_web_url("bitbucket.org", "o", "r", 5) == "https://bitbucket.org/o/r/pull-requests/5"
    assert _pr_web_url("gitlab.com", "o", "r", 7) == "https://gitlab.com/o/r/-/merge_requests/7"


def test_existing_url_none():
    assert _existing_url("github.com", "o", "r", None) == "https://github.com/o/r/pulls"


def test_existing_url_with_links():
    existing = {"links": {"html": {"href": "https://bitbucket.org/o/r/pull-requests/9"}}}
    assert _existing_url("bitbucket.org", "o", "r", existing) == "https://bitbucket.org/o/r/pull-requests/9"
    existing2 = {"html_url": "https://github.com/o/r/pull/1"}
    assert _existing_url("github.com", "o", "r", existing2) == "https://github.com/o/r/pull/1"
    existing3 = {"number": 10}
    assert _existing_url("github.com", "o", "r", existing3) == "https://github.com/o/r/pull/10"
    existing4 = {"iid": 3}
    assert _existing_url("gitlab.com", "o", "r", existing4) == "https://gitlab.com/o/r/-/merge_requests/3"


def test_safe_open_browser_allows_https():
    with mock.patch("relay.pr.webbrowser.open", return_value=True) as wb:
        assert _safe_open_browser("https://github.com/o/r/pull/1") is True
        wb.assert_called_once()


# ---- ollama: missing branches ----------------------------------------------

def test_ollama_invalid_base_url():
    with pytest.raises(Exception) as exc:
        OllamaProvider(base_url="http://10.0.0.1:11434")
    assert "invalid AI base URL" in str(exc.value)


def test_ollama_http_error():
    provider = OllamaProvider(base_url="http://localhost:11434", model="m", timeout=5)
    err = urllib.error.HTTPError("http://localhost:11434/api/generate", 500, "boom", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(Exception) as exc:
            provider.generate_commit_message("diff", "stat", "main")
        # Ollama maps HTTPError to AIError with kind unavailable, message contains HTTP 500
        assert "500" in str(exc.value) or "unavailable" in str(exc.value).lower()
        assert exc.value.kind == "unavailable"


def test_ollama_urlerror_timeout():
    provider = OllamaProvider(base_url="http://localhost:11434", model="m", timeout=5)
    url_err = urllib.error.URLError(TimeoutError("timed out"))
    with mock.patch("urllib.request.urlopen", side_effect=url_err):
        with pytest.raises(Exception) as exc:
            provider.generate_commit_message("diff", "stat", "main")
        assert "timeout" in str(exc.value).lower()


def test_ollama_bad_response_error_field():
    provider = OllamaProvider(base_url="http://localhost:11434", model="m", timeout=5)
    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = json.dumps({"error": "model not found"}).encode()
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: False
    with mock.patch("urllib.request.urlopen", return_value=fake_resp):
        with pytest.raises(Exception) as exc:
            provider.generate_commit_message("diff", "stat", "main")
        assert "bad_response" in str(exc.value).lower() or "model not found" in str(exc.value)


def test_ollama_connection_error():
    provider = OllamaProvider(base_url="http://localhost:11434", model="m", timeout=5)
    with mock.patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
        with pytest.raises(Exception) as exc:
            provider.generate_commit_message("diff", "stat", "main")
        assert "unavailable" in str(exc.value).lower() or "connection" in str(exc.value).lower()
