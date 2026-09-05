from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import install  # noqa: E402


def test_scripts_dir_in_virtualenv(monkeypatch):
    monkeypatch.setattr(sys, "prefix", "/tmp/fake-venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    with mock.patch("sysconfig.get_path", return_value="/tmp/fake-venv/bin") as mock_get_path:
        p = install.scripts_dir()
        assert p == Path("/tmp/fake-venv/bin")
        mock_get_path.assert_called_once_with("scripts")


def test_scripts_dir_outside_virtualenv(monkeypatch):
    monkeypatch.setattr(sys, "prefix", "/usr")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    expected_scheme = "nt_user" if os.name == "nt" else "posix_user"
    with mock.patch("sysconfig.get_path", return_value="fake_bin") as mock_get_path:
        p = install.scripts_dir()
        assert p == Path("fake_bin")
        mock_get_path.assert_called_once_with("scripts", expected_scheme)


def test_install_package_in_venv_skips_user_flag(monkeypatch):
    monkeypatch.setattr(sys, "prefix", "/tmp/fake-venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")

    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        success = install.install_package()
        assert success is True
        # Verify first call did NOT have --user
        assert mock_run.call_count == 1
        call_args = mock_run.call_args[0][0]
        assert "--user" not in call_args
        assert "-e" in call_args
        assert mock_run.call_args.kwargs.get("timeout") == 120


def test_update_path_unix_prefers_zsh(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    zshrc = tmp_path / ".zshrc"
    bashrc = tmp_path / ".bashrc"
    zshrc.write_text("# existing zshrc\n", encoding="utf-8")
    bashrc.write_text("# existing bashrc\n", encoding="utf-8")

    scripts_dir = tmp_path / "bin"
    res = install.update_path_unix(scripts_dir, yes=True)
    assert res is True

    # Written to zshrc, not bashrc
    target_esc = install._escape_sh_double(str(scripts_dir))
    assert target_esc in zshrc.read_text(encoding="utf-8")
    assert target_esc not in bashrc.read_text(encoding="utf-8")


def test_update_path_unix_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    bashrc = tmp_path / ".bashrc"
    scripts_dir = tmp_path / "bin"
    target_esc = install._escape_sh_double(str(scripts_dir))
    bashrc.write_text(f'export PATH="{target_esc}:$PATH"\n', encoding="utf-8")

    res = install.update_path_unix(scripts_dir, yes=True)
    assert res is True
    # Should not duplicate
    content = bashrc.read_text(encoding="utf-8")
    assert content.count(target_esc) == 1


def test_update_path_windows_already_present(monkeypatch):
    scripts_dir = Path("C:/fake/relay/scripts")
    with mock.patch("install._powershell", return_value=r"C:\WINDOWS;C:\fake\relay\scripts"):
        res = install.update_path_windows(scripts_dir, yes=True)
        assert res is True


def test_update_path_windows_success(monkeypatch, capsys):
    scripts_dir = Path("C:/fake/relay/scripts")
    calls = []

    def fake_powershell(script):
        calls.append(script)
        if "SetEnvironmentVariable('Path'" in script:
            return "RELAY_OK"
        return r"C:\Existing"

    with mock.patch("install._powershell", side_effect=fake_powershell):
        res = install.update_path_windows(scripts_dir, yes=True)
        assert res is True
        assert any("SetEnvironmentVariable" in c for c in calls)
    assert "added" in capsys.readouterr().out


def test_update_path_windows_failure_warns(monkeypatch, capsys):
    """L8: a failed update must warn, not report [ok] (the old `== ""`
    check could not tell success with empty output apart from failure)."""
    scripts_dir = Path("C:/fake/relay/scripts")

    def fake_powershell(script):
        if "SetEnvironmentVariable('Path'" in script:
            return None
        return r"C:\Existing"

    with mock.patch("install._powershell", side_effect=fake_powershell):
        res = install.update_path_windows(scripts_dir, yes=True)
        assert res is True
    assert "could not update user PATH" in capsys.readouterr().out


def test_update_path_unix_missing_profiles_creates_default(tmp_path, monkeypatch):
    """L7: a $HOME with no shell profile at all must not crash read_text."""
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    scripts_dir = tmp_path / "bin"
    res = install.update_path_unix(scripts_dir, yes=True)
    assert res is True

    default_profile = tmp_path / ".profile"
    target_esc = install._escape_sh_double(str(scripts_dir))
    assert target_esc in default_profile.read_text(encoding="utf-8")


def test_check_pip_timeout_falls_back_to_ensurepip():
    """L8: a hung `pip --version` must not stall the installer forever."""
    import subprocess

    timed_out = subprocess.TimeoutExpired(cmd="pip", timeout=120)
    ready = mock.Mock(returncode=0, stdout="pip 25.0\n", stderr="")
    with mock.patch("subprocess.run", side_effect=[timed_out, ready]):
        assert install.check_pip() is True


def test_escape_ps_and_sh():
    assert install._escape_ps_single("foo'bar") == "foo''bar"
    assert install._escape_sh_double('foo"bar$baz') == 'foo\\"bar\\$baz'
