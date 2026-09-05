"""Malformed-AI-response regression tests (CWE-20 / CWE-754).

Drives REAL provider parsers (Gemini/OpenAI/Anthropic/Ollama) with adversarial
bodies through a mocked ``urlopen`` — the parsing, size-limit, and contract
code under test is 100% genuine — plus the REAL Orchestrator fallback path
with a scripted fake provider. Asserts every payload ends in exactly one of
two safe outcomes: ``AIError`` (provider layer, triggering fallback upstream)
or manual-input fallback (orchestrator layer). A raw traceback, a hang, or a
committed garbage message all fail the test.

NOTE (honest scope record): the first version of this suite PROBED empty,
truncated, and JSON-``null`` bodies escaping as ``JSONDecodeError``/``TypeError``
(plus Ollama's ``.get``-on-non-dict ``AttributeError``) and a ``text: null``
extraction returning ``None`` that crashed ``sanitize_ai_message`` with
``AttributeError``. Those payloads were NOT asserted then (that would have
encoded the bug); they are asserted below, together with the ``fix(ai)`` that
closed them — ``decode_provider_json`` in ``relay/ai/base.py`` plus non-str
guards at each extraction site and in the Orchestrator.
"""
from unittest import mock
from unittest.mock import Mock

import pytest

from relay.ai.base import MAX_RESPONSE_BYTES, read_limited_response
from relay.errors import AIError, UserAbort
from relay.git_manager import GitManager
from relay.orchestrator import Orchestrator

MANUAL_MESSAGE = "fix: typed manually after rejection"


class ScriptedAI:
    """Fake provider replaying canned ``generate`` outputs (incl. None)."""

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def generate(self, diff, stat, branch):
        return self.outputs.pop(0)


class FakeResponse:
    """Minimal urlopen stand-in serving a fixed body."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _providers():
    from relay.ai.anthropic import AnthropicProvider
    from relay.ai.gemini import GeminiProvider
    from relay.ai.ollama import OllamaProvider
    from relay.ai.openai import OpenAIProvider

    return [
        GeminiProvider(api_key="k", model="m", timeout=5),
        OpenAIProvider(api_key="k", model="m", timeout=5),
        AnthropicProvider(api_key="k", model="m", timeout=5),
        OllamaProvider(model="m", timeout=5),
    ]


def _obtain(ai, **kwargs):
    git = Mock(spec=GitManager)
    git.recent_subjects.return_value = []
    orch = Orchestrator(git=git, mode="solo", yes=False, provider=ai, **kwargs)
    return orch._obtain_message("diff", "stat", "main")


# ---- orchestrator layer: unusable text must fall back, never traceback ------


@pytest.mark.parametrize("garbage", ["", "   ", "just a rant, no format", "```\n```"])
def test_unusable_ai_text_falls_back_to_manual_input(monkeypatch, garbage):
    """Empty/whitespace/garbage AI text -> manual input (one prompt round)."""
    inputs = iter([MANUAL_MESSAGE, ""])
    monkeypatch.setattr("builtins.input", lambda *args: next(inputs))
    message = _obtain(ScriptedAI([garbage]))
    assert message == MANUAL_MESSAGE


def test_user_can_still_abort_from_fallback(monkeypatch):
    """Fallback path preserves abort: empty manual answer raises UserAbort."""
    monkeypatch.setattr("builtins.input", lambda *args: "")
    with pytest.raises(UserAbort):
        _obtain(ScriptedAI(["not a conventional commit"]))


# ---- provider layer: oversize + shape violations become AIError --------------


def test_oversize_body_rejected_without_reading_it_all():
    """MAX_RESPONSE_BYTES+1 -> AIError(bad_response): no giant blob in memory."""
    body = b"x" * (MAX_RESPONSE_BYTES + 1)
    with pytest.raises(AIError) as exc_info:
        read_limited_response(FakeResponse(body), "gemini")
    assert exc_info.value.kind == "bad_response"


def test_body_at_exact_limit_is_accepted():
    """Boundary: exactly MAX_RESPONSE_BYTES passes the gate (no off-by-one)."""
    body = b"x" * MAX_RESPONSE_BYTES
    assert read_limited_response(FakeResponse(body), "gemini") == body


@pytest.mark.parametrize("index", [0, 1, 2])
def test_non_object_json_payload_rejected_as_ai_error(index):
    """A 200 with a JSON array (valid JSON, wrong shape) -> AIError, not crash."""
    providers = _providers()
    provider = providers[index]
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"[1, 2]")):
        with pytest.raises(AIError) as exc_info:
            provider.generate_commit_message("d", "s", "b")
    assert exc_info.value.kind == "bad_response"


# ---- fix(ai) regressions: previously-escaping payloads ----------------------

MALFORMED_BODIES = [
    b"",  # empty: json.loads raises JSONDecodeError
    b'{"candidates":[{"content"',  # truncated mid-object
    b"null",  # valid JSON, wrong shape: `"error" in None` used to TypeError
    b"[1, 2]",  # valid JSON array
]

NULL_TEXT_BODIES = [
    b'{"candidates": [{"content": {"parts": [{"text": null}]}}]}',  # gemini
    b'{"choices": [{"message": {"content": null}}]}',  # openai (+subclasses)
    b'{"content": [{"text": null}]}',  # anthropic
    b'{"response": null}',  # ollama
]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
@pytest.mark.parametrize("body", MALFORMED_BODIES)
def test_malformed_bodies_become_ai_error_not_traceback(index, body):
    """Empty/truncated/null/array bodies -> AIError(bad_response) on ALL providers."""
    provider = _providers()[index]
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(body)):
        with pytest.raises(AIError) as exc_info:
            provider.generate_commit_message("d", "s", "b")
    assert exc_info.value.kind == "bad_response"


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_null_text_extraction_becomes_ai_error(index):
    """A ``text/content/response: null`` extraction must not return None."""
    provider = _providers()[index]
    with mock.patch("urllib.request.urlopen", return_value=FakeResponse(NULL_TEXT_BODIES[index])):
        with pytest.raises(AIError) as exc_info:
            provider.generate_commit_message("d", "s", "b")
    assert exc_info.value.kind == "bad_response"


def test_none_ai_output_falls_back_to_manual_input(monkeypatch):
    """Defense in depth: even a None from generate() -> manual input, no crash."""
    inputs = iter([MANUAL_MESSAGE, ""])
    monkeypatch.setattr("builtins.input", lambda *args: next(inputs))
    message = _obtain(ScriptedAI([None]))
    assert message == MANUAL_MESSAGE
