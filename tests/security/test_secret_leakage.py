"""Credential-confinement regression tests (CWE-200 / CWE-918).

Two REAL localhost HTTP servers stand in for the world:
- ``origin``: poses as the AI provider endpoint. Records the request headers
  (proving the secret was genuinely in flight) and answers 302 to ``evil``.
- ``evil``: the redirect target. Records every hit + every header it sees.

The suite then drives the REAL provider classes (Gemini/OpenAI/Anthropic)
at ``origin`` and asserts the secret headers NEVER arrive at ``evil`` —
i.e. Relay's global redirect-rejecting opener (``relay._NoRedirectHandler``)
holds under fire, not just in a unit test of the handler itself.

A second test drives a REAL 400-error round trip and greps all captured
stdout/stderr to prove the key value never appears in user-facing output.

Everything stays on 127.0.0.1 with ephemeral ports: hermetic, no external
network, no real provider, no real credentials (sentinel values only).
"""
import http.server
import threading

import pytest

import relay  # noqa: F401  (import installs the redirect-rejecting opener)
from relay.errors import AIError, sanitize_terminal

SENTINEL_KEY = "sk-test-SENTINEL-9f8e7d6c5b4a"


def _make_server(handler_cls):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture(scope="module")
def redirect_pair():
    """Module-scoped (origin -> 302 -> evil) server pair with hit/header logs."""
    state = {"origin_headers": [], "evil_hits": [], "evil_headers": []}

    class OriginHandler(http.server.BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            state["origin_headers"].append(dict(self.headers))
            evil_port = state["evil_port"]
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{evil_port}/collect")
            self.end_headers()

        do_POST = _handle
        do_GET = _handle

        def log_message(self, *args):  # keep test output clean
            pass

    class EvilHandler(http.server.BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            state["evil_hits"].append(self.path)
            state["evil_headers"].append(dict(self.headers))
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = _handle
        do_GET = _handle

        def log_message(self, *args):
            pass

    origin = _make_server(OriginHandler)
    evil = _make_server(EvilHandler)
    state["evil_port"] = evil.server_address[1]
    yield state, origin.server_address[1]
    origin.shutdown()
    evil.shutdown()


def _clear(state):
    state["origin_headers"].clear()
    state["evil_hits"].clear()
    state["evil_headers"].clear()


def _providers_at(origin_port, monkeypatch):
    """(provider instance, header name carrying the secret) for each vendor."""
    import relay.ai.gemini as gemini_mod
    from relay.ai.anthropic import AnthropicProvider
    from relay.ai.gemini import GeminiProvider
    from relay.ai.openai import OpenAIProvider

    origin = f"http://127.0.0.1:{origin_port}"
    monkeypatch.setattr(gemini_mod, "_ENDPOINT", origin + "/v1beta/models/{model}:generateContent")
    return [
        (GeminiProvider(api_key=SENTINEL_KEY, model="m", timeout=5), "X-Goog-Api-Key"),
        (OpenAIProvider(api_key=SENTINEL_KEY, model="m", base_url=origin, timeout=5), "Authorization"),
        (
            AnthropicProvider(api_key=SENTINEL_KEY, model="m", base_url=origin, timeout=5),
            "x-api-key",
        ),
    ]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_secret_headers_never_reach_redirect_target(redirect_pair, index, monkeypatch):
    """302 to an attacker host: the request must die, credentials stay put."""
    state, origin_port = redirect_pair
    _clear(state)
    provider, header = _providers_at(origin_port, monkeypatch)[index]
    with pytest.raises(AIError):
        provider.generate_commit_message("diff", "stat", "main")

    # The secret really was in flight (else the test would prove nothing)...
    assert state["origin_headers"], "origin must have seen the request"
    seen = [v for h in state["origin_headers"] for k, v in h.items() if k.lower() == header.lower()]
    assert seen and all(SENTINEL_KEY in v for v in seen)
    # ...but the redirect target saw nothing at all.
    assert state["evil_hits"] == [], f"evil host was contacted: {state['evil_hits']}"
    assert state["evil_headers"] == []


def test_api_key_never_printed_on_provider_error(capsys):
    """A REAL 400 round trip: the key travels in headers, never in output."""

    class BadKeyHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            body = b'{"error": {"message": "bad request"}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = _make_server(BadKeyHandler)
    try:
        from relay.ai.openai import OpenAIProvider

        provider = OpenAIProvider(
            api_key=SENTINEL_KEY,
            model="m",
            base_url=f"http://127.0.0.1:{server.server_address[1]}",
            timeout=5,
        )
        with pytest.raises(AIError) as exc_info:
            provider.generate_commit_message("diff", "stat", "main")
        # Replay exactly what the Orchestrator prints on this path.
        print(f"[relay] AI unavailable ({sanitize_terminal(str(exc_info.value))}); falling back.")
    finally:
        server.shutdown()

    out, err = capsys.readouterr()
    assert SENTINEL_KEY not in out, "API key leaked into stdout"
    assert SENTINEL_KEY not in err, "API key leaked into stderr"
