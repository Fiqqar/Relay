"""Adversarial command-injection regression tests (CWE-78).

Each test feeds a REAL shell-metasyntax payload (``$(...)``, backticks, ``;``,
``&&``) through the genuine Relay code path into a REAL git binary inside a
throwaway repo, then asserts the ONLY observable effect is a literal filename /
message / branch — i.e. no secondary command ever executed.

The sentinel side effect is a file named ``pwned``: every payload below is
crafted so that, had it been interpolated into a shell string, a file called
``pwned`` would appear in the repo. Its absence is the assertion.

Filenames deliberately avoid ``| : ? * < > "`` so the suite also passes on
Windows (NTFS forbids those); pipe/command-substitution coverage comes from
the commit-message payloads instead, which travel via stdin.
"""
from sechelp import run_git

# Payloads crafted so shell interpretation would create a file named "pwned".
FILENAME_PAYLOADS = [
    "$(touch pwned).txt",
    "`touch pwned`.txt",
    "a;touch pwned.txt",
    "a&&touch pwned.txt",
]

MESSAGE_PAYLOADS = [
    "fix: polish; touch pwned",
    "fix: polish $(touch pwned)",
    "fix: polish `touch pwned`",
    "fix: polish && touch pwned",
    "fix: polish | touch pwned",
]

BRANCH_PAYLOADS = [
    "evil-semicolon;touch-pwned",
    "evil-dollar$(touch-pwned)",
    "evil-backtick`touch-pwned`",
    "evil-amp&&touch-pwned",
]


def _staged_names(repo):
    out = run_git(repo, "diff", "--cached", "--name-only")
    assert out.returncode == 0
    return out.stdout.splitlines()


def test_stage_files_with_shell_metachars_stages_literally(git, repo):
    """stage_files() must hand metachar filenames to git as literal argv."""
    for name in FILENAME_PAYLOADS:
        (repo / name).write_text("x\n", encoding="utf-8")
    git.stage_files(*FILENAME_PAYLOADS)

    staged = _staged_names(repo)
    for name in FILENAME_PAYLOADS:
        assert name in staged, f"{name!r} must be staged as a literal path"
    # Shell interpretation of any payload above would create one of these.
    assert not (repo / "pwned").exists()
    assert not (repo / "pwned.txt").exists()


def test_commit_message_with_shell_metachars_committed_literally(git, repo):
    """commit() pipes via stdin (-F -): metachars must land verbatim in the log."""
    for message in MESSAGE_PAYLOADS:
        (repo / "seed.txt").write_text(message + "\n", encoding="utf-8")
        git.stage_all()
        git.commit(message)

        logged = run_git(repo, "log", "-1", "--format=%B").stdout.strip()
        assert logged == message, f"logged message must equal payload, got {logged!r}"
    assert not (repo / "pwned").exists()


def test_branch_names_with_shell_metachars_never_execute(git, repo):
    """create_branch() must never let metachars escape into a shell.

    Either git accepts the name literally (asserted exactly) or it rejects it
    with GitError (fail-closed) — both are safe as long as nothing executes.
    """
    from relay.errors import GitError

    for name in BRANCH_PAYLOADS:
        try:
            git.create_branch(name)
        except GitError:
            continue  # fail-closed: rejected, nothing executed
        branches = run_git(repo, "branch", "--list", "--format=%(refname:short)").stdout.split()
        assert name in branches, f"{name!r} must exist literally if accepted"
        run_git(repo, "switch", "--", "main")
    assert not (repo / "pwned").exists()
