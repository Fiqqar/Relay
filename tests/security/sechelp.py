"""Small helpers shared by the security regression modules (importable by name)."""
import subprocess


def run_git(cwd, *args):
    """Run git with an argv list (never a shell string), like Relay itself."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def init_repo(path):
    """Turn ``path`` into a throwaway repo with one committed file."""
    assert run_git(path, "init", "-b", "main").returncode == 0
    assert run_git(path, "config", "user.email", "sec-test@example.com").returncode == 0
    assert run_git(path, "config", "user.name", "Sec Test").returncode == 0
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    assert run_git(path, "add", "seed.txt").returncode == 0
    assert run_git(path, "commit", "-m", "chore: seed").returncode == 0
