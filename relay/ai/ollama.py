"""Ollama provider — local, offline-friendly, zero credentials.

Registered behind the same AIManager interface as Gemini, so switching with
``--provider ollama`` needs no changes to the workflow or fallback logic.
If Ollama isn't running locally, the connection error surfaces as AIError
(``unavailable``) and the Orchestrator falls back to manual input, exactly as
designed.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import ollama_base_url, ollama_model
from ..errors import AIError
from .base import AIManager


class OllamaProvider(AIManager):
    provider_name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: int = 120):
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        self.model = model or ollama_model()
        self.timeout = timeout

    def generate_commit_message(self, diff: str, stat: str, branch: str) -> str:
        prompt = self.build_prompt(diff, stat, branch)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AIError(self.provider_name, "unavailable", f"HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            # Connection refused -> the local Ollama server is not running.
            raise AIError(self.provider_name, "unavailable", str(exc)) from exc

        if data.get("error"):
            raise AIError(self.provider_name, "bad_response", data["error"])
        return data.get("response", "")
