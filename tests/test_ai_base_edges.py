"""Edge-case tests for relay/ai/base.py — error-detail formats, path matching,
diff filtering/splitting fallbacks, unicode truncation, and prompt sections.

Each test targets a branch the suite previously never executed.
"""
import io
import urllib.error
from unittest import mock

from relay.ai.base import (
    AIManager,
    _path_matches,
    extract_http_error_detail,
    filter_ignored_diff,
    split_diff_by_file,
    truncate_diff,
)


def _http_error(body: bytes, code: int = 500, reason: str = "Error"):
    return urllib.error.HTTPError(
        "http://api.test", code, reason, {}, io.BytesIO(body)
    )


def test_error_dict_without_message_falls_back_to_top_level():
    exc = _http_error(b'{"error": {"code": 500}, "message": "top level"}')
    assert extract_http_error_detail(exc) == "top level"


def test_ollama_detail_format():
    exc = _http_error(b'{"detail": "model overloaded"}')
    assert extract_http_error_detail(exc) == "model overloaded"


def test_dict_without_known_keys_returns_raw_text():
    exc = _http_error(b'{"unknown": 1}')
    assert extract_http_error_detail(exc) == '{"unknown": 1}'


def test_non_object_json_returns_raw_text():
    exc = _http_error(b'[1, 2]')
    assert extract_http_error_detail(exc) == "[1, 2]"


def test_unreadable_error_body_falls_back_to_reason():
    fp = mock.Mock()
    fp.read.side_effect = OSError("gone")
    exc = urllib.error.HTTPError("http://api.test", 500, "Boom", {}, fp)
    assert extract_http_error_detail(exc) == "Boom"


def test_path_matches_purepath_trailing_pattern():
    # fnmatch needs a full-string match, but PurePath.match also accepts a
    # trailing relative pattern.
    assert _path_matches("a/b/c.py", ["b/c.py"]) is True


def test_path_matches_weird_path_never_raises():
    assert _path_matches("a\0b", ["*.py"]) is False


def test_path_matches_dot_pattern_never_raises():
    # "." survives the empty-pattern skip but PurePath.match rejects it;
    # the matcher must swallow that and report no match.
    assert _path_matches("a.py", ["."]) is False


def test_filter_ignored_diff_without_header_is_passthrough():
    diff = "just some text\nno git header here\n"
    assert filter_ignored_diff(diff, ["*.py"]) == diff


def test_filter_ignored_diff_keeps_unparseable_header():
    diff = "diff --git weird-header\n+line\n"
    assert filter_ignored_diff(diff, ["*.py"]) == diff


def test_split_diff_by_file_keeps_unparseable_header():
    assert split_diff_by_file("diff --git weird\n+line\n") == [
        ("", "diff --git weird\n+line\n")
    ]


def test_truncate_diff_small_unicode_is_passthrough():
    diff = "caf\u00e9 \u2603\n"
    assert truncate_diff(diff, max_lines=100) == (diff, False)


def test_build_prompt_omits_recent_section_when_all_blank():
    prompt = AIManager.build_prompt("D", "S", "main", recent_commits=["", "   "])
    assert "Recent commit" not in prompt
