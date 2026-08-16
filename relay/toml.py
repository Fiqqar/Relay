"""A tiny, dependency-free TOML-subset parser.

Relay keeps a zero-runtime-dependency promise on Python 3.10+, where the
stdlib ``tomllib`` (3.11+) is not guaranteed. Rather than introducing a parser
dependency, we parse the small, well-defined TOML subset that the Relay config
file actually needs:

    [section.subsection]
    key = "value"
    key = 'literal'
    key = 42
    key = true / false
    key = [1, 2, "three"]
    key = { text = "MIT", weight = 2 }   # inline table

plus full-line ``#`` comments, quoted keys, dotted keys, and inline tables.
``[[array of tables]]`` and multi-line strings are intentionally unsupported —
the config layer never produces them, so an explicit error beats a silent
misparse. The parser is strict about everything it *does* accept: unterminated
strings, unknown escapes, duplicate keys, and scalar/table redefinitions all
raise instead of silently mis-parsing or dropping data.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "\\": "\\"}


def load(fh) -> dict:
    """Parse a TOML file object, mirroring ``tomllib.load``.

    Accepts a binary or text stream. Used as the Python 3.10 fallback when the
    stdlib ``tomllib`` (3.11+) is unavailable, so the config file works on every
    supported Python version without adding a runtime dependency.
    """
    text = fh.read()
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return parse(text)


def parse(text: str) -> dict:
    """Parse TOML-subset text into nested dicts. Raises ValueError on bad input."""
    root: dict = {}
    current = root
    declared_tables: set[tuple[str, ...]] = set()

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if lineno == 1 and line.startswith("\ufeff"):
            line = line[1:].strip()
        if not line:
            continue
        try:
            if line.startswith("[["):
                raise ValueError("array-of-tables ([[...]]) is not supported")
            if line.startswith("["):
                if not line.endswith("]"):
                    raise ValueError(f"unclosed table header: {line!r}")
                path = tuple(_split_dotted(line[1:-1]))
                if path in declared_tables:
                    raise ValueError(
                        f"table {'.'.join(path)!r} is declared more than once"
                    )
                declared_tables.add(path)
                current = _table_at(root, path)
                continue
            key_raw, value_raw = _split_kv(line)
            keys = tuple(_split_dotted(key_raw))
            value = _parse_value(value_raw)
            _set_node(current, keys, value)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
    return root


def _even_backslashes_before(text: Sequence[str], i: int) -> bool:
    """True when the run of backslashes ending just before index ``i`` is even.

    A quote closes its string only when preceded by an even number of
    backslashes: ``\"`` escapes the quote, ``\\\"`` (odd run) does not. All
    string-aware scanners use this so comments, key/value splits and item
    splits agree with ``_parse_string``'s escape handling.
    """
    count = 0
    j = i - 1
    while j >= 0 and text[j] == "\\":
        count += 1
        j -= 1
    return count % 2 == 0


def _strip_comment(line: str) -> str:
    """Remove a trailing ``#`` comment, respecting quoted strings."""
    in_str = False
    quote = ""
    for i, ch in enumerate(line):
        if ch in ("'", '"'):
            if not in_str:
                in_str, quote = True, ch
            elif ch == quote and _even_backslashes_before(line, i):
                in_str = False
        elif ch == "#" and not in_str:
            return line[:i]
    return line


def _split_dotted(text: str) -> list[str]:
    """Split a dotted key/table path like ``ai.gemini`` or ``"a.b"``."""
    parts: list[str] = []
    buf: list[str] = []
    in_str = False
    quote = ""
    for ch in text.strip():
        if ch in ("'", '"'):
            if not in_str:
                in_str, quote = True, ch
            elif ch == quote:
                in_str = False
        elif ch == "." and not in_str:
            parts.append(_clean_key("".join(buf)))
            buf = []
            continue
        buf.append(ch)
    parts.append(_clean_key("".join(buf)))
    if in_str:
        raise ValueError(f"unterminated quoted key: {text!r}")
    return parts


def _clean_key(raw: str):
    candidate = raw.strip()
    if not candidate:
        raise ValueError("empty key segment")
    if candidate[0] in ("'", '"'):
        if len(candidate) < 2 or candidate[-1] != candidate[0]:
            raise ValueError(f"unterminated quoted key: {candidate!r}")
        return _parse_string(candidate)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        raise ValueError(f"invalid bare key: {candidate!r}")
    return candidate


def _split_kv(line: str) -> tuple[str, str]:
    """Split a ``key = value`` line at the first top-level ``=``."""
    in_str = False
    quote = ""
    for i, ch in enumerate(line):
        if ch in ("'", '"'):
            if not in_str:
                in_str, quote = True, ch
            elif ch == quote and _even_backslashes_before(line, i):
                in_str = False
        elif ch == "=" and not in_str:
            return line[:i].strip(), line[i + 1 :].strip()
    raise ValueError(f"expected 'key = value', got: {line!r}")


def _parse_value(raw: str):
    value = raw.strip()
    # TOML booleans are exactly ``true``/``false``; ``True``/``FALSE`` are
    # invalid and must not be silently accepted as a lenient convenience.
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("["):
        return _parse_array(value)
    if value.startswith("{"):
        return _parse_table(value)
    if value.startswith(("'", '"')):
        return _parse_string(value)
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if re.fullmatch(r"[+-]?\d+\.\d+([eE][+-]?\d+)?", value):
        return float(value)
    # ``1e5`` is a valid TOML float (exponent without a decimal point).
    if re.fullmatch(r"[+-]?\d+[eE][+-]?\d+", value):
        return float(value)
    raise ValueError(f"unsupported value: {value!r}")


def _parse_table(raw: str) -> dict:
    """Parse an inline table like ``{ text = "MIT", weight = 2 }``."""
    if len(raw) < 2 or not raw.endswith("}"):
        raise ValueError(f"invalid inline table: {raw!r}")
    body = raw[1:-1].strip()
    if not body:
        return {}
    result: dict = {}
    for part in _split_items(body):
        if not part:
            continue
        key_raw, value_raw = _split_kv(part)
        _set_node(result, tuple(_split_dotted(key_raw)), _parse_value(value_raw))
    return result


def _split_items(raw: str) -> list[str]:
    """Split a TOML list (``[...]``/``{...}``) body on top-level commas."""
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str = False
    quote = ""
    for ch in raw:
        if ch in ("'", '"'):
            if not in_str:
                in_str, quote = True, ch
            elif ch == quote and _even_backslashes_before(buf, len(buf)):
                in_str = False
            buf.append(ch)
        elif not in_str:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth < 0:
                    raise ValueError(f"unbalanced delimiters: {raw!r}")
            if ch == "," and depth == 0:
                items.append("".join(buf).strip())
                buf = []
                continue
            buf.append(ch)
        else:
            buf.append(ch)
    if in_str or depth != 0:
        raise ValueError(f"unbalanced delimiters: {raw!r}")
    items.append("".join(buf).strip())
    return items


def _parse_string(raw: str) -> str:
    """Parse a basic (``"``) or literal (``'``) single-line string.

    Strict by design: unterminated strings, trailing backslashes, and unknown
    escape sequences raise instead of silently mis-parsing (the old code
    turned an unterminated ``"abc`` into ``abc`` and kept an invalid ``\\q``
    as a literal backslash).
    """
    if len(raw) < 2 or raw[0] not in ("'", '"') or raw[-1] != raw[0]:
        raise ValueError(f"unterminated string: {raw!r}")
    quote = raw[0]
    body = raw[1:-1]
    if quote == "'":
        return body
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body):
                raise ValueError("string ends with an unescaped backslash")
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "u":
                digits = body[i + 2 : i + 6]
                if len(digits) == 4 and re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    out.append(chr(int(digits, 16)))
                    i += 6
                    continue
                raise ValueError(f"invalid \\u escape: {body[i : i + 6]!r}")
            if nxt == "U":
                digits = body[i + 2 : i + 10]
                if len(digits) == 8 and re.fullmatch(r"[0-9a-fA-F]{8}", digits):
                    out.append(chr(int(digits, 16)))
                    i += 10
                    continue
                raise ValueError(f"invalid \\U escape: {body[i : i + 10]!r}")
            raise ValueError(f"invalid escape sequence: \\{nxt}")
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_array(raw: str) -> list:
    if len(raw) < 2 or not raw.endswith("]"):
        raise ValueError(f"invalid array: {raw!r}")
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [_parse_value(item) for item in _split_items(inner) if item]


def _table_at(root: dict, path: tuple[str, ...]) -> dict:
    """Reach (or create) the table at ``path``; raise on a conflicting value.

    Only *explicitly* declared headers are tracked by the caller, so an
    implicitly created parent (``[a.b]`` implies ``a``) can still be declared
    later — TOML allows that. But redefining a scalar as a table (``a = 1``
    then ``[a]``) is a data-loss bug and must fail loudly.
    """
    node = root
    for part in path:
        child = node.get(part)
        if isinstance(child, dict):
            node = child
        elif child is None:
            new: dict = {}
            node[part] = new
            node = new
        else:
            raise ValueError(f"cannot redefine key {part!r} as a table")
    return node


def _set_node(table: dict, keys: tuple[str, ...], value) -> None:
    """Assign ``value`` at ``keys`` (dotted keys are relative to ``table``).

    Raises on duplicate keys and on redefining an existing value as a table.
    The old behavior silently overwrote both — a scalar replaced by a table
    (or vice versa) dropped real data without any error.
    """
    for key in keys[:-1]:
        child = table.get(key)
        if isinstance(child, dict):
            table = child
        elif child is None:
            new: dict = {}
            table[key] = new
            table = new
        else:
            raise ValueError(f"cannot redefine key {key!r} as a table")
    last = keys[-1]
    if last in table:
        raise ValueError(f"duplicate key: {last!r}")
    table[last] = value
