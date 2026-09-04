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

from ..config import ai_timeout, ollama_base_url, ollama_model
from ..errors import AIError, ConfigError
from ..telemetry import _is_valid_ai_base_url
from .base import AIManager, read_limited_response


class OllamaProvider(AIManager):
    provider_name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        if not _is_valid_ai_base_url(self.base_url):
            raise ConfigError(
                f"invalid AI base URL {self.base_url!r} (use https:// for public hosts, http:// only for localhost; see `relay --help`)"
            )
        self.model = model or ollama_model()
        # Same timeout policy as Gemini: a realistic window by default with a
        # safety clamp, so a slow local model still falls back to manual input.
        self.timeout = ai_timeout(timeout)

    def generate_commit_message(
        self,
        diff: str,
        stat: str,
        branch: str,
        recent_commits: list[str] | None = None,
        rejected_message: str | None = None,
    ) -> str:
        prompt = self.build_prompt(
            diff,
            stat,
            branch,
            recent_commits=recent_commits,
            rejected_message=rejected_message,
        )
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
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                data = json.loads(
                    read_limited_response(response, self.provider_name).decode("utf-8")
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                kind = "rate_limited"
            elif exc.code >= 500:
                kind = "unavailable"
            else:
                kind = "api_error"
            raise AIError(self.provider_name, kind, f"HTTP {exc.code}: {exc.reason}") from exc
        except TimeoutError as exc:
            # Timeout hit -> "unavailable" so the Orchestrator falls back to
            # manual input rather than waiting on a hung model.
            raise AIError(self.provider_name, "unavailable", f"timeout after {self.timeout}s") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise AIError(self.provider_name, "unavailable", f"timeout after {self.timeout}s") from exc
            # Connection refused -> the local Ollama server is not running.
            raise AIError(self.provider_name, "unavailable", f"network error: {exc}") from exc
        except ConnectionError as exc:
            raise AIError(self.provider_name, "unavailable", f"connection error: {exc}") from exc

        if data.get("error"):
            raise AIError(self.provider_name, "bad_response", data["error"])
        return data.get("response", "")
