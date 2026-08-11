"""Unit tests for the dependency-free TOML-subset parser (relay/toml.py)."""
import pytest

from relay import toml


def test_empty_document():
    assert toml.parse("") == {}


def test_only_comments_and_blanks():
    assert toml.parse("# hi\n\n    # more\n") == {}


def test_utf8_bom_is_stripped():
    assert toml.parse('\ufeffname = "relay"') == {"name": "relay"}


def test_basic_string_values():
    assert toml.parse('name = "relay"') == {"name": "relay"}


def test_literal_string_values():
    assert toml.parse("name = 'relay'") == {"name": "relay"}


def test_string_escapes():
    assert toml.parse(r'greeting = "hello\nworld"') == {"greeting": "hello\nworld"}
    assert toml.parse(r'path = "a\\b\tc"') == {"path": "a\\b\tc"}


def test_integer_and_float_values():
    assert toml.parse("timeout = 45\nratio = 1.5") == {"timeout": 45, "ratio": 1.5}


def test_boolean_values():
    assert toml.parse("enabled = true\ndisabled = false") == {
        "enabled": True,
        "disabled": False,
    }


def test_array_of_scalars():
    assert toml.parse('tags = [1, 2, "three", true]') == {
        "tags": [1, 2, "three", True]
    }


def test_empty_array():
    assert toml.parse("tags = []") == {"tags": []}


def test_inline_table():
    assert toml.parse('license = { text = "MIT", year = 2026 }') == {
        "license": {"text": "MIT", "year": 2026}
    }


def test_empty_inline_table():
    assert toml.parse("opts = {}") == {"opts": {}}


def test_array_of_inline_tables():
    assert toml.parse('items = [{ a = 1 }, { a = 2 }]') == {
        "items": [{"a": 1}, {"a": 2}]
    }


def test_nested_inline_table_value():
    assert toml.parse('cfg = { auth = { token = "x" } }') == {
        "cfg": {"auth": {"token": "x"}}
    }


def test_pyproject_style_inline_table_and_arrays():
    text = (
        '[project]\n'
        'name = "demo"\n'
        'license = { text = "MIT" }\n'
        'requires = ["setuptools>=68"]\n'
        'dev = ["pytest>=8", "build>=1.0"]\n'
    )
    parsed = toml.parse(text)
    assert parsed["project"]["license"] == {"text": "MIT"}
    assert parsed["project"]["requires"] == ["setuptools>=68"]
    assert parsed["project"]["dev"] == ["pytest>=8", "build>=1.0"]


def test_comments_ignored():
    assert toml.parse("# full line\nkey = 'v' # inline\n") == {"key": "v"}


def test_comment_inside_string_is_kept():
    assert toml.parse("note = 'a # b'") == {"note": "a # b"}


def test_hash_inside_double_quoted_string_is_kept():
    assert toml.parse('note = "a # b"') == {"note": "a # b"}


def test_comment_after_string_ending_in_backslash():
    """Regression: a value ending in a literal backslash followed by a closing
    quote swallowed the trailing `# comment` because the scanner treated the
    `\\` as escaping the quote. An even run of backslashes must close."""
    assert toml.parse(r'key = "path\\" # comment') == {"key": "path\\"}


def test_escaped_quote_inside_value():
    """Regression: an escaped `\"` was treated as closing the string, so a `=`
    inside the value was mis-split at top level."""
    assert toml.parse(r'key = "say \"hi\" = now"') == {"key": 'say "hi" = now'}


def test_escaped_quote_inside_array_item():
    assert toml.parse(r'tags = ["a\"b", "c"]') == {"tags": ['a"b', "c"]}


def test_escaped_quote_inside_inline_table():
    assert toml.parse(r'x = { t = "a\"b" }') == {"x": {"t": 'a"b'}}


def test_table_syntax():
    text = "[ai]\nprovider = 'ollama'\n[team]\nbranch = 'status/x'\n"
    assert toml.parse(text) == {
        "ai": {"provider": "ollama"},
        "team": {"branch": "status/x"},
    }


def test_nested_tables():
    text = "[ai.gemini]\nmodel = 'gemini-2.5-flash'\n[ai.ollama]\nmodel = 'llama3'\n"
    assert toml.parse(text) == {
        "ai": {"gemini": {"model": "gemini-2.5-flash"}, "ollama": {"model": "llama3"}}
    }


def test_dotted_key_creates_nested_dict():
    assert toml.parse('a.b.c = "deep"') == {"a": {"b": {"c": "deep"}}}


def test_quoted_key():
    assert toml.parse('"weird.key" = "val"') == {"weird.key": "val"}


def test_keys_reset_by_table_header():
    text = "[t]\na = 1\n[t2]\na = 2\n"
    assert toml.parse(text) == {"t": {"a": 1}, "t2": {"a": 2}}


@pytest.mark.parametrize(
    "bad",
    [
        "not a pair",
        "= 'missing key'",
        "key =",
        "key = unquoted",
        "[unclosed",
        "a = [1, 2",
        "[ai]]\nx = 1",
        "[[arr]]\n",
    ],
)
def test_malformed_input_raises_with_line_number(bad):
    with pytest.raises(ValueError):
        toml.parse(bad)


def test_error_reports_line_number():
    with pytest.raises(ValueError) as exc:
        toml.parse("ok = 1\nbad line\n")
    assert "line 2" in str(exc.value)