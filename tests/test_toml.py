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


# ---- Strictness: silent mis-parses must fail loudly --------------------------


def test_unterminated_basic_string_raises():
    with pytest.raises(ValueError, match="unterminated string"):
        toml.parse('key = "abc')


def test_lone_quote_value_raises():
    with pytest.raises(ValueError, match="unterminated string"):
        toml.parse('key = "')


def test_unterminated_literal_string_raises():
    with pytest.raises(ValueError, match="unterminated string"):
        toml.parse("key = 'abc")


def test_newline_inside_basic_string_raises():
    """Multi-line strings are unsupported, so a raw newline inside a basic
    string must error (the line-by-line scanner would otherwise mis-parse)."""
    with pytest.raises(ValueError, match="unterminated string"):
        toml.parse('key = "a\nb"')


def test_unknown_escape_sequence_raises():
    with pytest.raises(ValueError, match="invalid escape sequence"):
        toml.parse(r'key = "a\qb"')


def test_invalid_unicode_escape_raises():
    with pytest.raises(ValueError, match=r"invalid \\u escape"):
        toml.parse(r'key = "\uZZZZ"')


def test_trailing_backslash_raises():
    with pytest.raises(ValueError, match="backslash"):
        toml.parse(r'key = "abc\"')


def test_unicode_escapes_are_supported():
    assert toml.parse(r'key = "\u00e9 \U0001f600"') == {"key": "é 😀"}


def test_escaped_backslash_before_quote_still_works():
    """An even run of backslashes must still close the string: ``a\\\"``
    (escaped backslash + closing quote) parses, with the trailing comment
    properly stripped."""
    assert toml.parse(r'key = "a\\\\" # comment') == {"key": "a\\\\"}


def test_scalar_redefined_as_table_raises():
    with pytest.raises(ValueError, match="redefine"):
        toml.parse("a = 1\n[a]\n")


def test_dotted_key_over_scalar_raises():
    with pytest.raises(ValueError, match="redefine"):
        toml.parse("a = 5\na.b = 1\n")


def test_duplicate_key_raises():
    with pytest.raises(ValueError, match="duplicate key"):
        toml.parse("a = 1\na = 2\n")


def test_duplicate_key_in_inline_table_raises():
    with pytest.raises(ValueError, match="duplicate key"):
        toml.parse('x = { a = 1, a = 2 }')


def test_repeated_table_header_raises():
    with pytest.raises(ValueError, match="more than once"):
        toml.parse("[a]\nx = 1\n[a]\ny = 2\n")


def test_parent_table_declared_after_child_is_allowed():
    """TOML allows declaring a table after its implicitly-created parent."""
    assert toml.parse("[a.b]\nx = 1\n[a]\ny = 2\n") == {
        "a": {"b": {"x": 1}, "y": 2}
    }


def test_booleans_are_case_sensitive():
    with pytest.raises(ValueError, match="unsupported value"):
        toml.parse("a = True")
    with pytest.raises(ValueError, match="unsupported value"):
        toml.parse("a = FALSE")


def test_exponent_float_without_decimal_point():
    assert toml.parse("a = 1e5") == {"a": 100000.0}
    assert toml.parse("a = -2.5E-3") == {"a": -0.0025}
