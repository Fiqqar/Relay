# Relay — System Architecture

> Design principles: **pure-stdlib Python, zero AI lock-in, never block the workflow, always leave the repo in a known state.**

---

## 1. Overview

Relay is a client-side CLI. It orchestrates three kinds of external systems: the **local Git repository**, an **LLM provider** (Gemini, Ollama, OpenAI, Anthropic, Mistral, Groq, or xAI), and the developer's **terminal** (for confirmation and fallback input). The core design goal is separation of concerns: Git mutation logic, AI communication, and user interaction are isolated behind interfaces so each is independently testable and replaceable

Relay is **zero-dependency by design**: everything uses the Python standard library (`argparse`, `subprocess`, `urllib`). Installing it is a single `pip install -e .`, and it works on fully offline machines.

## 2. High-Level Component Diagram

```
+-----------------------------------------------------------------------------------+
|                                   relay  (CLI)                                     |
|                                                                                   |
|  +------------+     +-------------+     +------------------+     +------------+   |
|  | CLI Parser | --> |  Preflight  | --> |   Orchestrator   | --> |  Workflow  |   |
|  | (argparse) |     |  (checks)   |     |  (state machine) |     |   steps    |   |
|  +------------+     +-------------+     +--------+---------+     +------------+   |
|                                                        |                          |
|            +-------------------------------------------+                          |
|            |                   |                   |                             |
|            v                   v                   v                             |
|   +-------------+     +--------------+      +--------------+                     |
|   | GitManager  |     |  AIService   |      |   PromptUI   |                     |
|   | (subprocess)|     | (AIManager)  |      |  (input())   |                     |
|   +-------------+     |  +---------+ |      +--------------+                     |
|            ^          |  | Gemini+6| |                                          |
|            |          |  +---------+ |                                          |
|            +----------+  |see §3.7 | |                                          |
|                         |  +---------+ |    +--------------------+               |
|                         +--------------+    | Message Builder /   |               |
|                         +--------------+    | Commit Validator    |               |
|                         |  Config      |    +--------------------+               |
|                         | (env vars)   |    +--------------------+               |
|                         +--------------+    | Errors (taxonomy)   |               |
|                                              +--------------------+               |
+-----------------------------------------------------------------------------------+
          |                            |                          |
          v                            v                          v
   +------------+              +--------------+           +---------------+
   |  local git |              |  LLM Provider |           |   terminal    |
   |  repository|              |  HTTP (urllib)|           |  stdin/stdout |
   +------------+              +--------------+           +---------------+
```

## 3. Component Breakdown

### 3.1 CLI Parser — `relay/cli.py`
- Library: **argparse** (stdlib).
- Responsibility: parse flags (`--solo`, `--team [FEATURE]`, `--provider`, `--yes`, `--no-push`, `--dry-run`, `--verbose`, `--version`); resolve the mode; construct the AI provider; wire the Orchestrator; map exceptions to exit codes (`0` success, `1` error, `130` user abort).
- Keeps zero business logic — it only translates CLI input into an `Orchestrator` call.

### 3.2 Config Manager — `relay/config.py`
- Responsibility: resolve configuration from **environment variables** plus an optional **TOML config file**: `RELAY_AI_PROVIDER`, per-provider `*_MODEL` / `*_BASE_URL`, `RELAY_BRANCH_TEMPLATE`, `RELAY_AI_TIMEOUT`, `RELAY_MAX_DIFF_LINES`, `RELAY_PR_OPEN` (full key matrix in `README.md#ai-providers-and-configuration`).
- Precedence: **flags > env vars > config file > defaults**. The file lives at `$XDG_CONFIG_HOME/relay/config.toml` (or `%APPDATA%\relay\config.toml` on Windows), overridable via `RELAY_CONFIG`; a `[relay]` table holds the non-secret keys. Secrets (`GEMINI_API_KEY`, `GITHUB_TOKEN`/`GH_TOKEN`) are env-variable-only (NFR-3).
- A missing API key degrades to manual input (lazy provider build, ADR-004); only an unknown provider name raises `ConfigError` before any git mutation. A missing or malformed config file is ignored.
- All reads flow through `_resolve(env_key, cfg_key, default)`, so call sites never change when a key's source is added or moved.

### 3.3 Preflight — `Orchestrator._preflight` (`relay/orchestrator.py`)
- Responsibility: fail fast, before any mutation:
  1. CWD is inside a Git work tree (`git rev-parse --is-inside-work-tree`).
  2. There are staged or unstaged changes (`git status --porcelain`) — if the tree is clean it exits `0` with a message.
  3. No merge, rebase, cherry-pick, or revert is in progress and there are no unmerged paths — otherwise exit `1` with a message.
  4. A remote is configured (`git remote`) — warning-only for solo mode, since the push itself will surface a real failure.
- Returns an early exit code or `None`; each check emits one clear, actionable message.

### 3.4 Orchestrator — `relay/orchestrator.py`
- Responsibility: drives the **state machine** (see [FLOW.md](FLOW.md)) for solo/team modes. Coordinates GitManager, AIService, and the confirmation/fallback prompts. Owns the fallback transition (`GENERATE → AI_FAIL → MANUAL_INPUT`).
- Deliberately **does not know** which provider backs the AIService — it only calls `ai.generate()`, and its AI provider is injected for testability.

### 3.5 Git Manager — `relay/git_manager.py`
- Responsibility: a thin, typed wrapper over the `git` CLI via `subprocess.run`. Preferred over a pure-Python git library because it reuses the user's credential helpers, SSH agent, and hooks exactly as normal `git` does.
- All commands run as **argv lists (`shell=False`)** so filenames with spaces or special characters can never be injected into a shell. `--verbose` prints each command before running it.
- Commands exposed: `status`, `add .`, `diff --cached`, `diff --cached --stat`, `branch --show-current`, `switch -c`, `commit -F -` (message piped via stdin, avoiding shell-quoting bugs), `push [-u] origin <branch>` — plus `write-tree` (TOCTOU guard), `ls-remote` (remote branch check), and commit-range helpers for squash/PR.
- Every failure raises `GitError` carrying the underlying git stderr.

### 3.6 Diff Collector — `Orchestrator.run` (via GitManager)
- Responsibility: gather `git diff --cached` (the prompt input) plus a short `--stat` summary and the current branch name.
- Applies **token budget line truncation** (`RELAY_MAX_DIFF_LINES`, default 120 lines) and **byte cap** (512 KiB) via `truncate_diff()` (`relay/ai/base.py`) before sending the diff to the provider. The `--stat` summary is preserved in full.

### 3.7 AIService — `relay/ai/`
The extension point. Every provider implements one interface:

```python
# relay/ai/base.py
class AIManager(ABC):
    provider_name = "base"

    @staticmethod
    def build_prompt(diff: str, stat: str, branch: str) -> str:
        """Shared prompt: repo context (branch + diffstat) + diff + SYSTEM_PROMPT."""

    @abstractmethod
    def generate_commit_message(self, diff: str, stat: str, branch: str) -> str:
        """Return the raw AI text; raise AIError on any failure."""

    def generate(self, diff: str, stat: str, branch: str) -> str:
        """Wraps the concrete call so ANY unexpected exception becomes a typed AIError."""
```

- **GeminiProvider** (`relay/ai/gemini.py`) — calls the Google Generative Language REST API with stdlib `urllib` (API key via the `X-Goog-Api-Key` header, never in the URL or logs). Raises `ConfigError` if `GEMINI_API_KEY` is missing.
- **OllamaProvider** (`relay/ai/ollama.py`) — calls the local `POST /api/generate` endpoint with `stream: false`. Zero credentials; connection-refused maps to an `AIError{unavailable}`.
- **OpenAI-compatible providers** — `OpenAIProvider` (`relay/ai/openai.py`) targets `POST {base}/chat/completions`; `AnthropicProvider` (`relay/ai/anthropic.py`) targets `POST {base}/messages`; `MistralProvider`, `GroqProvider`, and `XAIProvider` subclass the OpenAI provider and differ only in their credentials, base URL, and default model:

| Provider | Key env var | Base URL (default) | Default model | API shape |
| --- | --- | --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | `gpt-4o-mini` | OpenAI `/chat/completions` |
| `anthropic` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` | `claude-3-5-haiku-latest` | Anthropic `/messages` |
| `mistral` | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1` | `mistral-small-latest` | OpenAI `/chat/completions` |
| `groq` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | OpenAI `/chat/completions` |
| `xai` | `XAI_API_KEY` | `https://api.x.ai/v1` | `grok-beta` | OpenAI `/chat/completions` |

Each model/base URL is overridable via `<PROVIDER>_MODEL` / `<PROVIDER>_BASE_URL`; the
full provider list lives in `_PROVIDERS` (`relay/ai/__init__.py`). A new provider is a
drop-in: subclass `OpenAIProvider`, register it, add a config getter + doctor branch.
- Shared behavior: HTTP timeouts and typed errors:

```python
# relay/errors.py
class AIError(RelayError):
    kind  # unavailable | timeout | rate_limited | bad_response | api_error | unexpected
    provider
```

### 3.8 Message Builder / Validator — `relay/commit.py`
- `sanitize_ai_message` — trims raw LLM output, strips markdown code fences, keeps the first non-empty line.
- `validate_conventional` — validates the subject line against the Conventional Commits grammar (`type(scope): subject`, type ∈ `feat|fix|refactor|docs|style|test|chore|perf|build|ci|revert`).
- If validation fails, the Orchestrator treats it as an AI failure → **manual fallback** (a bad AI message is never silently committed or mangled).
- `build_branch_name` — expands `<type>/<feature>` into a valid git ref (lowercase, whitespace → `-`, strips `~^:?*[\`, drops `.`/`..` path segments, caps at 100 chars).

### 3.9 PromptUI — `relay/prompt.py`
- Library: plain `input()` plus stdlib `subprocess`/`tempfile` for the editor flow — deliberately dependency-free.
- Responsibility: the confirmation gate (`[Accept] [Edit] [Retry] [Abort]`) for AI messages, the editor draft flow (`open_in_editor`), and the manual-message fallback prompt (`manual_input`). The Orchestrator calls these through thin seams, so prompting is unit-testable without a workflow run.
- Non-TTY (piped) environments: `input()` raises `EOFError`, which the CLI layer converts to exit `1` — the run never hangs.

### 3.10 Output / Logging — inline
- Milestones and errors print to stdout/stderr with a `[relay]` prefix. `--verbose` prints each git command. The diff contents are never logged (NFR-3).

## 4. Data Flow (Solo mode example)

```
user ──relay --solo--> CLI Parser ──> Config (env) ──> build AI provider ──> Preflight
                                                                              │ ok
                                                                              v
                                   Orchestrator: STAGE ──> git add .
                                          │
                                          v
                                   COLLECT_DIFF ──> git diff --cached (+stat)
                                          │
                                          v
                                   GENERATE ──> AIService(Gemini|Ollama) ──> HTTP ──> LLM
                                          │                                            │
                                   MessageBuilder <────────────────────────────────────┘
                                          │ valid
                                          v
                                   CONFIRM ──> input() (Accept/Edit/Retry/Abort)
                                          │
                                          v
                                   COMMIT ──> git commit -F <message>
                                          │
                                          v
                                   PUSH ──> git push origin <branch> ──> DONE (exit 0)
```

## 5. Configuration Schema

Full reference lives in the [README](../README.md#configuration). Key points:

- **Environment variables** plus an optional `[relay]` TOML config file. Precedence: flags > env > file > defaults.
- **Secrets** — `GEMINI_API_KEY` must come from the environment; it is never logged, printed in `--verbose`, or included in error strings, and is never read from the config file.

## 6. Error Handling & Exit Codes

| Scenario | Behavior | Exit code |
| --- | --- | --- |
| Success | — | `0` |
| Preflight / workflow / git failure | friendly message + actionable hint (git stderr shown with `--verbose`) | `1` |
| User aborts at a prompt (Ctrl-C / abort choice) | no state changes after the abort point | `130` |
| Commit OK, push failed | reports state + exact retry command (`git push [‑u] origin <branch>`) | `1` |
| Provider configured without a key | lazy build degrades to manual input (ADR-004); nothing fails before staging | `0` (on success) |
| Non-TTY run with AI failure | manual prompt cannot be answered; run ends cleanly, nothing committed | `1` |

Errors flow through a small taxonomy in `relay/errors.py`: `RelayError` (base) → `ConfigError`, `GitError` (with underlying git stderr), `AIError` (with `kind`), `UserAbort`. The CLI layer catches these and maps them to exit codes.

## 7. Security

1. **Keys** — env var only; never logged, never shown in `--verbose`, never included in error strings.
2. **Repo safety** — Relay never force-pushes; history is rewritten only by the explicit local `amend` / `squash` / `undo` commands (never auto-pushed); the working tree is touched via `git add` (`.`, selected files, or `-p`), branch checkout, and the team-mode orphan-branch cleanup on commit failure.
3. **Shell safety** — every git command runs with `shell=False` and a literal argv list, so user-controlled strings (branch names, messages) cannot be injected.
4. **Supply chain** — zero third-party runtime dependencies; the attack surface is the Python stdlib plus the user's own `git`.

## 8. Recommended Tech Stack

| Layer | Choice | Rationale |
| --- | --- | --- |
| Language | **Python 3.10+** | Ubiquitous, quick iteration, trivial packaging. |
| CLI | **argparse** (stdlib) | No dependency needed for flags/subcommands. |
| Config | `os.environ` | Zero-config file management; env vars are the standard for API keys. |
| Prompts | built-in `input()` | Enough for one-shot prompts; no TTY library required. |
| Git | **subprocess.run** (list argv) | Reuses user credentials/hooks; simpler and safer than a git library. |
| HTTP | **urllib** (stdlib) | Only two REST endpoints; no need for `requests`. |
| Tests | **pytest** + `pytest-cov` + `unittest.mock` | ~1000 hermetic tests, 90% branch gate enforced in CI. |
| Packaging | `pyproject.toml` + setuptools | `pip install -e .` yields a global `relay` console script. |

*Why not Go/Rust?* Both produce a single static binary, but Python's interpreter is already present on most developer machines, so `pip install` is the only distribution step, and provider/CLI changes don't require a rebuild. If a static binary is ever required, the stdlib-only constraint keeps a future PyInstaller/Nuitka build straightforward. *Why not `requests`/`typer`?* Zero dependencies means the tool installs and runs everywhere, even offline — the strongest property for a global CLI.

## 9. Extensibility

- **New AI provider** = subclass `AIManager` (implement `provider_name` + `generate_commit_message`) and register it in the `_PROVIDERS` dict in `relay/ai/__init__.py`. No workflow changes required.
- **New branch template** = set `RELAY_BRANCH_TEMPLATE` to any template containing a `<feature>` placeholder; sanitization guarantees a valid git ref.
- **New preflight checks** = add a check to `Orchestrator._preflight`; each is a pure predicate + message.
- **Config file** = all config reads go through `relay/config.py`, so new keys (or new sources) can be added without touching call sites.

## 10. Testing Strategy

- **Unit** — Conventional Commit validator table (`relay/commit.py`); branch-name sanitization; `AIManager.generate` error wrapping (an exception becomes a typed `AIError`).
- **Provider** — Gemini/Ollama request/response parsing against local stub HTTP servers (`unittest.mock.patch("urllib.request.urlopen", ...)`).
- **Integration** — run against a throwaway repo (`git init` + files) in CI on all 3 OSes; assert the exact git commands and the final `git log` subject.
- **Fallback E2E** — a provider that raises `AIError` + a monkeypatched `input()`; asserts the workflow still reaches a manual-input commit.
