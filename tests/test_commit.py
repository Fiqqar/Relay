"""Unit tests for relay/commit.py — the message sanitizer, the Conventional
Commit validator, and the team-mode branch-name builder."""
import pytest

from relay.commit import (
    CONVENTIONAL_TYPES,
    build_branch_name,
    extract_commit_type,
    sanitize_ai_message,
    validate_conventional,
)


class TestSanitizeAIMessage:
    def test_plain_single_line_passthrough(self):
        assert sanitize_ai_message("feat: add login") == "feat: add login"

    def test_surrounding_whitespace_trimmed(self):
        assert sanitize_ai_message("  feat: add login  \n") == "feat: add login"

    def test_markdown_fence_stripped(self):
        assert sanitize_ai_message("```\nfix(ui): align button\n```") == "fix(ui): align button"

    def test_fence_with_language_tag_stripped(self):
        assert sanitize_ai_message("```text\nchore: bump deps\n```") == "chore: bump deps"

    def test_keeps_first_nonempty_line(self):
        # Preamble text means the sanitizer keeps the first line; the VALIDATOR
        # is what rejects that garbage and triggers the manual fallback.
        assert sanitize_ai_message("sure, here you go:\n\ndocs: real message\n") == "sure, here you go:"

    def test_empty_and_whitespace_only_input(self):
        assert sanitize_ai_message("") == ""
        assert sanitize_ai_message("   \n\n\t") == ""


class TestValidateConventional:
    @pytest.mark.parametrize(
        "message",
        [
            "feat: add login",
            "feat(api): add login endpoint",
            "fix(auth)!: drop legacy token",
            "revert: undo the thing",
            "docs(readme): clarify install",
            "test(unit): cover fallback path",
            "FEAT: uppercase type is normalized",
        ],
    )
    def test_valid_messages(self, message):
        valid, reason = validate_conventional(message)
        assert valid, f"{message!r} should be valid (reason: {reason!r})"

    @pytest.mark.parametrize(
        "message",
        [
            "",
            "wip stuff",
            "no type here",
            "feat",
            "feat:",
            "feat: ",
            "chore:  ",
            "bogus: something",       # unknown type
            "fix(api",
            "feat(auth):",
        ],
    )
    def test_invalid_messages(self, message):
        valid, reason = validate_conventional(message)
        assert not valid, f"{message!r} should be invalid"
        assert reason, "a rejection should carry a reason"

    def test_multiline_message_validated_on_first_line_only(self):
        valid, _ = validate_conventional("feat(api): add login\n\nAdds OAuth login.")
        assert valid

    def test_unknown_type_reports_the_offending_type(self):
        valid, reason = validate_conventional("nope: whatever")
        assert not valid
        assert "unknown type" in reason

    def test_all_supported_types_are_covered(self):
        for commit_type in CONVENTIONAL_TYPES:
            valid, _ = validate_conventional(f"{commit_type}: something")
            assert valid, f"type {commit_type!r} should validate"


class TestExtractCommitType:
    @pytest.mark.parametrize(
        "message, expected",
        [
            ("feat: add login", "feat"),
            ("feat(auth): add login", "feat"),
            ("fix: correct validation", "fix"),
            ("docs(readme): clarify install", "docs"),
            ("refactor(api): split handler", "refactor"),
            ("style: format code", "style"),
            ("test(unit): cover fallback", "test"),
            ("chore: bump deps", "chore"),
            ("feat(api)!: breaking change", "feat"),
        ],
    )
    def test_extracts_valid_types(self, message, expected):
        assert extract_commit_type(message) == expected

    @pytest.mark.parametrize(
        "message",
        [
            "",
            "   ",
            "no type here",
            "wip stuff",
            "bogus: not a known type",
            "feat(auth",
            "feat",
            "feat:",
        ],
    )
    def test_returns_none_for_invalid_messages(self, message):
        assert extract_commit_type(message) is None

    def test_multiline_message_uses_first_line(self):
        assert extract_commit_type("feat(api): add login\n\nBody") == "feat"

    def test_all_supported_types_are_extracted(self):
        for commit_type in CONVENTIONAL_TYPES:
            assert extract_commit_type(f"{commit_type}: something") == commit_type


class TestBuildBranchName:
    def test_basic_template_expansion(self):
        assert build_branch_name("status/<feature>", "payments") == "status/payments"

    def test_type_placeholder_uses_commit_type(self):
        assert build_branch_name("<type>/<feature>", "payments", commit_type="fix") == "fix/payments"
        assert build_branch_name("<type>/<feature>", "payments", commit_type="docs") == "docs/payments"

    def test_type_placeholder_defaults_to_feat(self):
        assert build_branch_name("<type>/<feature>", "payments") == "feat/payments"

    def test_type_placeholder_with_feature_slug(self):
        assert (
            build_branch_name("<type>/<feature>", "Prompt Fix Test", commit_type="fix")
            == "fix/prompt-fix-test"
        )

    def test_template_without_type_placeholder_ignores_commit_type(self):
        assert (
            build_branch_name("status/<feature>", "payments", commit_type="feat")
            == "status/payments"
        )

    def test_commit_type_is_sanitized(self):
        assert build_branch_name("<type>/<feature>", "payments", commit_type="Bug Fix") == "bug-fix/payments"

    def test_uppercase_and_spaces_are_slugified(self):
        assert build_branch_name("status/<feature>", "Payments API") == "status/payments-api"

    def test_illegal_characters_replaced(self):
        # '*' and ':' are not word chars -> each becomes a '-', then runs collapse.
        assert build_branch_name("status/<feature>", "pay*ments: v2") == "status/pay-ments-v2"

    def test_dot_path_segments_are_dropped(self):
        # ".." / "." segments could escape the branch namespace; they must vanish.
        assert build_branch_name("status/<feature>", "Feature/../Pwn") == "status/feature/pwn"

    def test_leading_and_trailing_dots_stripped(self):
        assert build_branch_name("status/<feature>", ".secret.") == "status/secret"

    def test_length_capped(self):
        long = "x" * 200
        result = build_branch_name("status/<feature>", long)
        assert len(result.split("/")[-1]) <= 100

    def test_empty_feature_raises(self):
        with pytest.raises(ValueError):
            build_branch_name("status/<feature>", "   ")
