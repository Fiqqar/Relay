"""Git option-injection regression tests (CWE-88).

Covers EVERY ``-``-prefix guard and ``--`` separator in ``git_manager.py``:
config_get, remote_url, remote_has_branch, recent_subjects, log_between,
diff_range, stat_range, stage_files, unstage, create_branch, checkout,
delete_branch, push, fetch, rev_parse, is_ancestor, reset_soft — plus the
stdin commit path that keeps a leading-dash message from becoming a flag.

Two assertion styles, both against a REAL repo + REAL git:
- guard-style (returns ""/False/[]/raises before touching git): assert the
  neutral value AND that zero git invocations were recorded;
- separator-style (goes through to git): assert the recorded argv contains
  ``--`` before the payload, and that git either handles it literally or
  fails closed with GitError (never interprets it as an option).
"""
import pytest
from sechelp import run_git

from relay.errors import GitError
from relay.git_manager import GitManager

EVIL_BRANCH = "--upload-pack=touch pwned"
EVIL_FILE = "--exec=touch pwned"
EVIL_FLAG = "--help"


class RecordingGitManager(GitManager):
    """GitManager that records every argv it would execute, then really runs it."""

    def __init__(self, cwd):
        super().__init__(cwd=cwd, verbose=False)
        self.calls = []

    def _run(self, *args, **kwargs):
        self.calls.append(list(args))
        return super()._run(*args, **kwargs)


@pytest.fixture
def rgit(repo):
    return RecordingGitManager(cwd=str(repo))


def _separator_before(argv, payload):
    """True when ``--`` appears in argv strictly before the payload element."""
    assert payload in argv, f"payload {payload!r} must reach git, got {argv}"
    assert "--" in argv, f"separator -- missing in {argv}"
    assert argv.index("--") < argv.index(payload), f"-- must precede payload in {argv}"


# ---- guard-style: neutral value, zero git invocations -----------------------


def test_config_get_rejects_dash_key(rgit):
    assert rgit.config_get(EVIL_FLAG) == ""
    assert rgit.calls == []


def test_remote_url_rejects_dash_name(rgit):
    assert rgit.remote_url(EVIL_FLAG) == ""
    assert rgit.calls == []


def test_remote_has_branch_rejects_dash_remote(rgit):
    assert rgit.remote_has_branch("main", remote=EVIL_FLAG) is False
    assert rgit.calls == []


def test_log_between_rejects_dash_refs(rgit):
    assert rgit.log_between(EVIL_FLAG, "HEAD") == ""
    assert rgit.log_between("HEAD", EVIL_FLAG) == ""
    assert rgit.calls == []


def test_diff_range_rejects_dash_refs(rgit):
    assert rgit.diff_range(EVIL_FLAG, "HEAD") == ""
    assert rgit.diff_range("HEAD", EVIL_FLAG) == ""
    assert rgit.calls == []


def test_stat_range_rejects_dash_refs(rgit):
    assert rgit.stat_range(EVIL_FLAG, "HEAD") == ""
    assert rgit.stat_range("HEAD", EVIL_FLAG) == ""
    assert rgit.calls == []


def test_rev_parse_rejects_dash_ref(rgit):
    assert rgit.rev_parse(EVIL_FLAG) == ""
    assert rgit.calls == []


def test_fetch_rejects_dash_remote(rgit):
    with pytest.raises(GitError):
        rgit.fetch(EVIL_FLAG)
    assert rgit.fetch(EVIL_FLAG, check=False) is None
    # check=False path returns before any git invocation; the raising path
    # also validates before executing.
    assert rgit.calls == []


def test_reset_soft_rejects_dash_target(rgit, repo):
    before = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(GitError):
        rgit.reset_soft("--hard")
    assert rgit.calls == []
    after = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert before == after, "HEAD must be untouched by the rejected payload"


def test_recent_subjects_rejects_nonpositive_count(rgit):
    assert rgit.recent_subjects(count=0) == []
    assert rgit.recent_subjects(count=-5) == []


# ---- separator-style: payload reaches git only after `--` -------------------


def test_remote_has_branch_passes_branch_after_separator(rgit):
    assert rgit.remote_has_branch(EVIL_BRANCH) is False  # no remote; must not raise
    _separator_before(rgit.calls[-1], EVIL_BRANCH)


def test_stage_and_unstage_pass_paths_after_separator(rgit, repo):
    # The file really exists, so git accepts it — the mitigation is that it is
    # treated as a literal path (staged/unstaged by exact name), not as a flag.
    (repo / EVIL_FILE).write_text("x\n", encoding="utf-8")
    rgit.stage_files(EVIL_FILE)
    _separator_before(rgit.calls[-1], EVIL_FILE)
    staged = run_git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    assert EVIL_FILE in staged
    rgit.unstage(EVIL_FILE)
    _separator_before(rgit.calls[-1], EVIL_FILE)
    staged = run_git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    assert EVIL_FILE not in staged
    assert not (repo / "pwned").exists()


def test_branch_operations_pass_name_after_separator(rgit, repo):
    before = run_git(repo, "branch", "--list", "--format=%(refname:short)").stdout.split()
    with pytest.raises(GitError):
        rgit.create_branch(EVIL_BRANCH)
    _separator_before(rgit.calls[-1], EVIL_BRANCH)
    with pytest.raises(GitError):
        rgit.checkout(EVIL_FLAG)
    _separator_before(rgit.calls[-1], EVIL_FLAG)
    run_git(repo, "branch", "victim")
    with pytest.raises(GitError):
        rgit.delete_branch("--victim")  # literal name, not a flag
    _separator_before(rgit.calls[-1], "--victim")
    after = run_git(repo, "branch", "--list", "--format=%(refname:short)").stdout.split()
    assert set(after) == set(before) | {"victim"}
    assert "victim" in after, "the real branch must survive the attack"


def test_push_passes_branch_after_separator(rgit):
    with pytest.raises(GitError):
        rgit.push(EVIL_BRANCH)  # no remote configured -> fail-closed
    _separator_before(rgit.calls[-1], EVIL_BRANCH)


def test_fetch_passes_ref_after_separator(rgit):
    with pytest.raises(GitError):
        rgit.fetch("origin", EVIL_BRANCH)  # no remote -> fail-closed
    _separator_before(rgit.calls[-1], EVIL_BRANCH)


def test_is_ancestor_passes_refs_after_separator(rgit):
    assert rgit.is_ancestor("--ancestor", "--descendant") is False
    _separator_before(rgit.calls[-1], "--ancestor")


def test_commit_message_with_leading_dashes_committed_literally(git, repo):
    """The stdin (-F -) path: a leading-dash message can never become a flag."""
    message = "--amend\n\nbody that must stay literal"
    (repo / "seed.txt").write_text("change\n", encoding="utf-8")
    git.stage_all()
    git.commit(message)
    logged = run_git(repo, "log", "-1", "--format=%B").stdout.strip()
    assert logged == message
