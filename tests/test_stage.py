"""Unit tests for `relay stage` (relay/stage.py) selection parsing and routing."""
from unittest import mock

import pytest

from relay.cli import build_parser, main
from relay.errors import GitError
from relay.stage import _parse_selection, run_stage


class FakeGit:
    def __init__(self, files=("app.py", "notes.md", "scratch.txt"), badges=None):
        self.files = list(files)
        self.badges = (
            badges
            if badges is not None
            else {"app.py": "M", "notes.md": "M", "scratch.txt": "?"}
        )
        self.staged = []
        self.add_interactive_calls = 0
        self.interactive_returncode = 0
        self._is_repo = True

    def is_repo(self):
        return self._is_repo

    def unstaged_changes(self):
        return self.files

    def unstaged_badges(self):
        return dict(self.badges)

    def stage_files(self, *paths):
        self.staged.extend(paths)

    def add_interactive(self):
        self.add_interactive_calls += 1
        return self.interactive_returncode


@pytest.fixture
def git():
    return FakeGit()


# ---- selection parsing ------------------------------------------------------

class TestParseSelection:
    def test_all_selects_everything(self):
        assert _parse_selection("all", 3) == {1, 2, 3}

    def test_none_and_empty_cancel(self):
        assert _parse_selection("none", 3) is None
        assert _parse_selection("", 3) is None

    def test_single_and_commas(self):
        assert _parse_selection("2", 3) == {2}
        assert _parse_selection("1,3", 3) == {1, 3}

    def test_range_inclusive(self):
        assert _parse_selection("2-4", 5) == {2, 3, 4}

    def test_out_of_range_raises(self):
        with pytest.raises(GitError, match="out of range"):
            _parse_selection("9", 3)

    def test_bad_range_raises(self):
        with pytest.raises(GitError, match="out of 1.."):
            _parse_selection("2-9", 3)

    def test_garbage_raises(self):
        with pytest.raises(GitError):
            _parse_selection("banana", 3)

    def test_non_numeric_range_raises(self):
        with pytest.raises(GitError, match="invalid range"):
            _parse_selection("a-b", 3)
        with pytest.raises(GitError, match="invalid range"):
            _parse_selection("2-", 3)


# ---- run_stage ----------------------------------------------------------------

def test_stage_requires_a_repo(git):
    git._is_repo = False
    with pytest.raises(GitError, match="not a git repository"):
        run_stage(git=git)


def test_stage_lists_files_and_stages_selection(git, capsys):
    with mock.patch("relay.stage._input", return_value="2,3"):
        assert run_stage(git=git) == 0
    assert git.staged == ["notes.md", "scratch.txt"]


def test_stage_all(git):
    with mock.patch("relay.stage._input", return_value="all"):
        assert run_stage(git=git) == 0
    assert git.staged == ["app.py", "notes.md", "scratch.txt"]


def test_stage_cancel_changes_nothing(git, capsys):
    with mock.patch("relay.stage._input", return_value="none"):
        assert run_stage(git=git) == 0
    assert git.staged == []
    assert "canceled" in capsys.readouterr().out


def test_stage_patch_mode_dispatches(git):
    git.add_interactive_calls = 0
    with mock.patch.object(git, "add_interactive", return_value=0) as interactive:
        assert run_stage(git=git, patch=True) == 0
    interactive.assert_called_once_with()


def test_stage_patch_mode_propagates_nonzero_exit_code(git):
    git.interactive_returncode = 1
    assert run_stage(git=git, patch=True) == 1


def test_stage_nothing_to_do(git, capsys):
    git.files = []
    with mock.patch("relay.stage._input") as inp:
        assert run_stage(git=git) == 0
    inp.assert_not_called()


# ---- CLI routing --------------------------------------------------------------

def test_parser_stage_defaults():
    args = build_parser().parse_args(["stage"])
    assert args.command == "stage"
    assert args.patch is False


def test_parser_stage_patch_flag():
    args = build_parser().parse_args(["stage", "--patch"])
    assert args.patch is True


def test_main_routes_stage():
    with mock.patch("relay.cli.run_stage", return_value=0) as run:
        assert main(["stage"]) == 0
    run.assert_called_once_with(patch=False, verbose=False, allow_sensitive=False)


def test_main_forwards_patch_flag():
    with mock.patch("relay.cli.run_stage", return_value=0) as run:
        main(["stage", "--patch"])
    assert run.call_args.kwargs["patch"] is True


def test_main_stage_error_maps_to_exit_1():
    with mock.patch("relay.cli.run_stage", side_effect=GitError("boom")):
        assert main(["stage"]) == 1


# ---- coverage: stage.py edge branches ---------------------------------------

def test_parse_selection_empty_chunks_and_no_selection():
    from relay.stage import _parse_selection

    assert _parse_selection("1, , 2", total=3) == {1, 2}
    with pytest.raises(GitError, match="no files selected"):
        _parse_selection(" ,  , ", total=3)


def test_stage_input_wrapper():
    from relay.stage import _input

    with mock.patch("builtins.input", return_value="hello"):
        assert _input("prompt: ") == "hello"


# ---- status badges ---------------------------------------------------------------


def test_stage_shows_status_badges(git, capsys):
    with mock.patch("relay.stage._input", return_value="none"):
        assert run_stage(git=git) == 0
    out = capsys.readouterr().out
    assert "[M] app.py" in out
    assert "[M] notes.md" in out
    assert "[?] scratch.txt" in out


def test_stage_badges_fall_back_when_git_cannot_provide_them(git, capsys):
    git.unstaged_badges = None  # not callable -> neutral badge for every row
    with mock.patch("relay.stage._input", return_value="none"):
        assert run_stage(git=git) == 0
    assert "[?] app.py" in capsys.readouterr().out


def test_stage_badges_survive_a_lookup_failure(git, capsys):
    with mock.patch.object(git, "unstaged_badges", side_effect=RuntimeError("boom")):
        with mock.patch("relay.stage._input", return_value="none"):
            assert run_stage(git=git) == 0
    assert "[?] app.py" in capsys.readouterr().out


def test_stage_badges_survive_a_non_dict_result(git, capsys):
    with mock.patch.object(git, "unstaged_badges", return_value=["nope"]):
        with mock.patch("relay.stage._input", return_value="none"):
            assert run_stage(git=git) == 0
    assert "[?] app.py" in capsys.readouterr().out


# ---- sensitive-file guard ---------------------------------------------------------


def test_stage_sensitive_selection_asks_and_aborts_on_no(git, capsys):
    git.files = [".env", "app.py"]
    with mock.patch("relay.stage._input", side_effect=["1", "n"]):
        assert run_stage(git=git) == 0
    assert git.staged == []
    out = capsys.readouterr().out
    assert "look sensitive" in out
    assert ".env" in out
    assert "sensitive file(s) not staged" in out


def test_stage_sensitive_selection_proceeds_on_yes(git):
    git.files = [".env", "app.py"]
    with mock.patch("relay.stage._input", side_effect=["1", "yes"]):
        assert run_stage(git=git) == 0
    assert git.staged == [".env"]


def test_stage_allow_sensitive_skips_the_prompt(git):
    git.files = [".env"]
    with mock.patch("relay.stage._input", return_value="all") as inp:
        assert run_stage(git=git, allow_sensitive=True) == 0
    assert git.staged == [".env"]
    assert inp.call_count == 1  # only the selection prompt


def test_stage_non_sensitive_selection_never_prompts(git):
    with mock.patch("relay.stage._input", return_value="all") as inp:
        assert run_stage(git=git) == 0
    assert inp.call_count == 1


def test_stage_sensitive_check_ignores_example_files(git):
    git.files = ["docs/.env.example"]
    with mock.patch("relay.stage._input", return_value="all") as inp:
        assert run_stage(git=git) == 0
    assert git.staged == ["docs/.env.example"]
    assert inp.call_count == 1


# ---- CLI wiring for --allow-sensitive ---------------------------------------------


def test_main_forwards_allow_sensitive_to_stage():
    with mock.patch("relay.cli.run_stage", return_value=0) as run:
        main(["stage", "--allow-sensitive"])
    assert run.call_args.kwargs["allow_sensitive"] is True


def test_main_forwards_allow_sensitive_given_before_subcommand():
    with mock.patch("relay.cli.run_stage", return_value=0) as run:
        main(["--allow-sensitive", "stage"])
    assert run.call_args.kwargs["allow_sensitive"] is True

