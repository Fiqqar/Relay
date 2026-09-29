"""Guard for `.github/ISSUE_TEMPLATE/*.yml` — GitHub's issue-form schema.

GitHub refuses to render a form whose ``validations`` is not a Hash:

    Critical
    There are some problems with this template
    body[3]: validations must be of type Hash

That is exactly what ``validations:`` followed by a bare scalar (``false``)
produces: YAML makes the key a boolean instead of a mapping. It shipped that way
in ``feature_request.yml`` (``body[3]``/``body[4]``), so the shape is asserted
here now.

PyYAML is deliberately *not* used: Relay ships zero runtime dependencies and its
dev extras are ``pytest``/``pytest-cov``/``ruff``/``mypy``/``build`` only, so a
YAML parser would not be installed in CI. These tests lint the raw text with a
small, deliberate scanner instead — it only needs to understand the handful of
shapes an issue form is allowed to use.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"

# `config.yml` is not a form: it holds `blank_issues_enabled` / `contact_links`.
_FORM_TEMPLATES = ("bug_report.yml", "feature_request.yml")

# Input types GitHub accepts in a form body, and the keys its `validations`
# mapping may carry (`required` everywhere, the length caps on `input`).
_BODY_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}
_VALIDATIONS_KEYS = {"required", "max_length", "min_length"}
_TYPES_REQUIRING_OPTIONS = {"dropdown", "checkboxes"}

_ITEM_RE = re.compile(r"^\s*- type:\s*(\S+)\s*$")
_ID_RE = re.compile(r"^\s*id:\s*(\S+)\s*$")

_FORM_PATHS = [_TEMPLATE_DIR / name for name in _FORM_TEMPLATES]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_comment(value: str) -> str:
    """Drop a trailing `# ...` comment from a scalar value."""
    return re.sub(r"\s+#.*$", "", value).strip()


def validation_problems(text: str, name: str = "template.yml") -> list[str]:
    """Report every ``validations`` block that is not a YAML mapping.

    A block is a mapping only when the key is followed by a deeper-indented
    ``key: value`` line. An inline scalar, a bare ``null``, a sequence item, a
    sibling at the same depth, or a *nested scalar* (the shape GitHub reported
    as "must be of type Hash") all make the template fail to render.
    """
    problems: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)validations:(.*)$", line)
        if not match:
            continue
        indent = len(match.group(1))
        inline = _strip_comment(match.group(2))
        if inline:
            problems.append(
                f"{name}:{index + 1}: `validations:` has the inline value "
                f"{inline!r}; it must be a mapping (e.g. `required: true`)"
            )
            continue
        following = next((ln for ln in lines[index + 1:] if ln.strip()), "")
        # A mapping entry is `key: ...` deeper than the key; anything else
        # (nothing, a sibling, a `- item`, or a bare scalar like `false`) makes
        # `validations` a boolean/null/sequence instead of a Hash.
        is_mapping_entry = bool(re.match(r"^\s*[A-Za-z_][\w-]*:(\s|$)", following))
        if not following or _indent(following) <= indent or not is_mapping_entry:
            problems.append(
                f"{name}:{index + 1}: `validations:` is not a mapping "
                "(GitHub: \"validations must be of type Hash\")"
            )
    return problems


def _body_items(text: str) -> list[tuple[str, list[str]]]:
    """Split the form body into ``(type, block_lines)`` pairs, in order."""
    items: list[tuple[str, list[str]]] = []
    current_type: str | None = None
    current: list[str] = []
    for line in text.splitlines():
        match = _ITEM_RE.match(line)
        if match:
            if current_type is not None:
                items.append((current_type, current))
            current_type, current = match.group(1), [line]
        elif current_type is not None:
            current.append(line)
    if current_type is not None:
        items.append((current_type, current))
    return items


def _validation_scalars(text: str) -> list[tuple[int, str]]:
    """``(line number, value)`` for every ``required:`` scalar in the file."""
    found: list[tuple[int, str]] = []
    for index, line in enumerate(text.splitlines()):
        match = re.match(r"^\s*required:\s*(.*)$", line)
        if match:
            found.append((index + 1, _strip_comment(match.group(1))))
    return found


# ---- the templates themselves -------------------------------------------------


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_form_template_is_present(path: Path):
    """A deleted/renamed form must fail loudly instead of silently skipping."""
    assert path.is_file(), f"missing issue form: {path}"
    assert _read(path).strip(), f"empty issue form: {path}"


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_validations_is_always_a_mapping(path: Path):
    """Regression: `validations:` + a bare scalar broke `relay`'s forms."""
    assert validation_problems(_read(path), path.name) == []


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_validations_only_uses_known_keys(path: Path):
    text = _read(path)
    lines = text.splitlines()
    unknown: list[str] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)validations:\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        for offset, nested in enumerate(lines[index + 1:], start=index + 2):
            if not nested.strip():
                continue
            if _indent(nested) <= indent:
                break
            key = nested.strip().split(":", 1)[0]
            if key not in _VALIDATIONS_KEYS:
                unknown.append(f"{path.name}:{offset}: unknown key {key!r}")
    assert unknown == [], f"GitHub rejects unknown validations keys: {unknown}"


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_required_is_an_unquoted_boolean(path: Path):
    bad = [
        f"{path.name}:{line}: required: {value!r} (use true or false)"
        for line, value in _validation_scalars(_read(path))
        if value not in ("true", "false")
    ]
    assert bad == [], f"`required` must be a boolean: {bad}"


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_form_metadata_is_complete(path: Path):
    text = _read(path)
    for key in ("name:", "description:", "body:"):
        assert re.search(rf"^{key}", text, re.MULTILINE), f"{path.name} has no {key}"


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_body_item_types_are_canonical(path: Path):
    unknown = [
        kind
        for kind, _ in _body_items(_read(path))
        if kind not in _BODY_TYPES
    ]
    assert unknown == [], f"{path.name} uses unsupported input types: {unknown}"


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_every_item_has_attributes_and_a_unique_id(path: Path):
    """GitHub keys answers by `id`, so duplicates silently drop a field."""
    seen: dict[str, int] = {}
    for index, (kind, block) in enumerate(_body_items(_read(path)), start=1):
        joined = "\n".join(block)
        assert re.search(r"^\s*attributes:", joined, re.MULTILINE), (
            f"{path.name} body[{index}] ({kind}) has no attributes"
        )
        if kind == "markdown":
            continue
        match = next((_ID_RE.match(ln) for ln in block if _ID_RE.match(ln)), None)
        assert match, f"{path.name} body[{index}] ({kind}) has no id"
        seen[match.group(1)] = seen.get(match.group(1), 0) + 1
    duplicates = [name for name, count in seen.items() if count > 1]
    assert duplicates == [], f"{path.name} reuses ids: {duplicates}"


@pytest.mark.parametrize("path", _FORM_PATHS, ids=lambda p: p.name)
def test_choice_inputs_declare_options(path: Path):
    missing = []
    for index, (kind, block) in enumerate(_body_items(_read(path)), start=1):
        if kind in _TYPES_REQUIRING_OPTIONS:
            joined = "\n".join(block)
            if not re.search(r"^\s*options:", joined, re.MULTILINE):
                missing.append(f"{path.name} body[{index}] ({kind})")
    assert missing == [], f"these inputs need an options list: {missing}"


# ---- the scanner itself (the shape GitHub reported) ---------------------------


def test_scanner_rejects_the_shipped_boolean_form():
    """The exact pre-fix text from feature_request.yml must be flagged."""
    broken = (
        "  - type: textarea\n"
        "    id: alternatives\n"
        "    attributes:\n"
        "      label: Alternatives Considered\n"
        "    validations:\n"
        "      false\n"
    )
    problems = validation_problems(broken, "feature_request.yml")
    assert len(problems) == 1
    assert "feature_request.yml:5" in problems[0]
    assert "not a mapping" in problems[0]


@pytest.mark.parametrize(
    "fragment",
    [
        "    validations: false",          # inline scalar
        "    validations:\n",             # null (nothing nested)
        "    validations:\n      - required: true",   # sequence, not mapping
        "    validations:\n    next: 1",  # sibling at the same depth
    ],
)
def test_scanner_rejects_every_non_mapping_shape(fragment):
    assert validation_problems(fragment + "\n") != []


def test_scanner_accepts_a_proper_mapping():
    good = (
        "    validations:\n"
        "      required: true\n"
        "      max_length: 200\n"
        "    attributes:\n"
        "      label: Fine\n"
    )
    assert validation_problems(good) == []
