# Relay


[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)](https://www.python.org/)

**Your Git workflow, on autopilot.**

One workflow. From a messy working tree to a clean, AI-authored **Conventional Commit**, pushed and ready for a Pull Request - in Solo or Team mode.

```
git add .  →  generate commit message  →  git commit  →  git push  →  open PR
```

Relay reads your staged diff, hands it to an LLM (local **Ollama** or **Gemini API**), and returns a standards-compliant Conventional Commit message. If the AI is down, rate-limited, or offline, Relay never blocks your flow — it drops you straight into a manual commit-message prompt in the same terminal, and continues the workflow from there.

---

## Table of Contents

- [Why Relay](#why-relay)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Example](#example)
- [Product Requirements Document (PRD)](#product-requirements-document-prd)
- [Roadmap](#roadmap)
- [Documentation](#documentation)

---

## Why Relay

Daily Git work is repetitive and context-switching: stage files, invent a commit message, push, open a browser, and create a Pull Request. Commit messages are often lazy, inconsistent, or convention-free — which pollutes history and hurts `git bisect`, changelog generation, and code review.

Relay collapses this into a single workflow while keeping the developer in control at every meaningful checkpoint.

## Features

- **Solo mode** — stage all, generate message, commit, push to the current branch.
- **Team mode** — stage all, generate message, create & checkout a new branch (e.g. `feat/<feature>`), push that branch.
- **Instant Pull Requests** — open a GitHub Pull Request directly from your terminal using zero-dependency REST API integration (`relay pr`, incl. draft PRs via `--draft`).
- **AI-powered Conventional Commits** — reads `git diff --cached`, sends it to an LLM, validates the response as a Conventional Commit.
- **Pluggable AI providers** — **Gemini API** (default) and local **Ollama**, both behind a common interface.
- **Human-in-the-loop fallback** — on AI failure (rate limit, timeout, offline, garbage output), falls back to a manual terminal prompt **without exiting the workflow**.
- **Zero-config & safe** — works out of the box via environment variables, optionally overridden with a TOML config file; `--dry-run`, `--yes`, and an explicit confirm step.
- **Respect your staging** — `--staged` commits only what you already staged instead of `git add .`.
- **Non-destructive undo** — `relay undo` soft-resets the last commit (changes stay staged, nothing lost).
- **Rewrite the last commit** — `relay amend` regenerates the commit message in place (never force-pushes).
- **Multi-line messages** — manual fallback (and Edit) accept a Conventional-Commits subject plus an optional body.
- **Cross-platform** — pure-stdlib Python (no runtime deps beyond `git`), runs on Windows, macOS, and Linux.

## Installation

Requires **Python 3.10+** and `git` on your `PATH`

```bash
pip install "git+https://github.com/Fiqqar/Relay.git"
```

**One-command install (recommended):** the bundled installer verifies the
prerequisites, pip-installs Relay as a user-level editable package, and puts
`relay` on your `PATH` for every new terminal (Windows, macOS, Linux).

```bash
# from this repository
python install.py --yes      # skip the PATH prompt
```

> **Windows note:** pip installs the `relay` script into Python's `Scripts`
> directory. `install.py` adds that directory to your **user** `PATH`
> automatically (via PowerShell's `SetEnvironmentVariable(..., 'User')`).
> If it wasn't run with `--yes`, it asks first; you can always run `relay doctor`
> later to check whether `relay` is reachable.

Manual fallback (same thing, by hand):

```bash
# from this repository
python -m pip install -e .     # editable install -> `relay` on your PATH
```

GitHub Releases publishing is wired up via `.github/workflows/release.yml`
(push a `v*` tag). A Homebrew formula (`Formula/relay.rb`) and a Scoop
manifest (`bucket/relay.json`) are shipped in this repo for native package
managers.

On **macOS/Linux** (Homebrew ≥6 requires formulae to come from a *tap*, not a
URL):

```bash
brew tap Fiqqar/relay https://github.com/Fiqqar/Relay
brew install Fiqqar/relay/relay
```

On **Windows** (Scoop):

```bash
scoop bucket add relay https://github.com/Fiqqar/Relay
scoop install relay/relay
```

## Security

- **Secrets are environment-only.** `GEMINI_API_KEY`, `GITHUB_TOKEN`/`GH_TOKEN`,
  and `GITLAB_TOKEN` are read from the environment and never written to disk or
  logged. Relay never sends your diff, commit messages, or file names anywhere
  except the AI provider you explicitly configure.
- **No shell injection surface.** Every `git` invocation passes arguments as a
  list (`shell=True` is never used), so filenames with spaces or special
  characters cannot be injected into a shell.
- **Telemetry is opt-in and off by default.** Nothing leaves your machine until
  you run `relay telemetry on` *and* set `RELAY_TELEMETRY_URL`. The payload
  contains only mode/provider/outcome and the Relay version — no code.
- **Verify checksums for production installs.** Releases are served over HTTPS
  from GitHub, but `pip install` (as opposed to Scoop/Homebrew) does not
  pin an expected hash. For maximum supply-chain confidence, verify the
  artifact before installing — both published `sha256` hashes are listed on
  the [GitHub Release](https://github.com/Fiqqar/Relay/releases), and Scoop
  pins the wheel hash in `bucket/relay.json`.
- **Your keys are your own.** Relay talks only to the provider/forge you point
  it at. If you use `--verbose`, assume git commands (never keys) are echoed.

## Quick Start

```bash
# 0. (Optional but useful) verify the install in a fresh terminal
relay doctor

# 1. Configure your API keys (once)
set GEMINI_API_KEY=your_key              # Windows cmd (for commit generation)
set GITHUB_TOKEN=ghp_your_token          # Windows cmd (for GitHub PR)

# 2. Run the workflow
relay --solo                     # stage, commit, push to the current branch
relay --team "payments"          # new branch feat/payments, commit, push

# 3. Open a Pull Request natively
relay pr                       # create PR, print its URL (browser not touched)
relay pr --open                # ... and open it in the default browser
relay pr -d --open             # draft PR, opened in the browser
```
`relay pr` prints the PR URL but only launches your browser with `--open`
(or `RELAY_PR_OPEN=1` in the config/env). `relay pr --yes` implies `--open`
(no confirm prompt exists for `relay pr`).

### `relay doctor`

A read-only self-diagnostic. It checks that Python/git are available, that the
`relay` script is reachable on your `PATH`, that the current directory is a git
work tree, and that your AI provider and GitHub tokens are configured.

```text
$ relay doctor
[relay doctor] Relay 0.1.0 - gemini provider

  Python 3.10+       PASS   3.11.9
  relay on PATH      PASS   C:\Users\you\...\Python311\Scripts\relay.exe
  git installed      PASS   C:\Program Files\Git\cmd\git.EXE (2.42.0)
  inside a git repo  PASS   branch: main, remote: yes, working tree: clean
  provider: gemini   PASS   Gemini API
  AI credentials     FAIL   GEMINI_API_KEY is not set; see `relay --help`
  GitHub token       WARN   GITHUB_TOKEN is not set; `relay pr` cannot open pull requests

  5 pass, 1 warn, 1 fail - 1 issue(s) need fixing.
```

### Commands & Flags

| Command / Flag | Description |
| --- | --- |
| `pr` | Open a GitHub PR for the current branch. Prints the URL; opens the browser only with `--open`/`-o` or `RELAY_PR_OPEN=1`. `--base`, `--title`, `--draft`/`-d`, `--yes` (no prompt, implies `--open`). |
| `undo` | Undo the last commit (`git reset --soft HEAD~1`); changes stay staged. |
| `amend` | Rewrite the last commit's message with a freshly generated one (never pushes). |
| `doctor` | Diagnose this installation (PATH, git, AI credentials). |
| `--solo` | Stage, commit and push to the current branch (default). |
| `--team [FEATURE]` | Create & checkout `<type>/<feature>`, commit, push it (feature optional). |
| `--provider {gemini,ollama}` | Override the AI provider (default: gemini). |
| `--timeout SECONDS` | Seconds to wait for the AI response (default: 30, max: 120). |
| `--yes` | Skip the confirmation prompt. |
| `--no-push` | Commit but do not push. |
| `--staged` | Commit only what is already staged (skip `git add .`). |
| `--dry-run` | Show the plan and the generated message, change nothing. |
| `--verbose` | Print the git commands being run. |
| `--version` | Print the version. |

## Configuration

Relay is configured through **environment variables**, optionally overridden by
a **TOML config file**. Precedence: **flags > env var > config file >
defaults**.

Environment variables (always win over the config file):

| Variable | Purpose | Default |
| --- | --- | --- |
| `GEMINI_API_KEY` | Gemini API key (**required** when provider is `gemini`) | — |
| `GITHUB_TOKEN` | GitHub Personal Access Token (for `relay pr`) | — |
| `GEMINI_MODEL` | Gemini model id | `gemini-2.5-flash` |
| `OLLAMA_BASE_URL` | Ollama server endpoint | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model id | `qwen2.5-coder:7b` |
| `RELAY_AI_PROVIDER` | Default provider: `gemini` \| `ollama` | `gemini` |
| `RELAY_AI_TIMEOUT` | Seconds to wait for the AI response (clamped to 120 max) | `30` |
| `RELAY_MAX_DIFF_LINES` | Line cap on the staged diff sent to the LLM | `120` |
| `RELAY_BRANCH_TEMPLATE` | Team-mode branch template (`<feature>` placeholder) | `<type>/<feature>` |
| `RELAY_PR_OPEN` | Auto-open `relay pr` URLs in the browser (`1/true/yes/on`) | off |
| `RELAY_CONFIG` | Override the TOML config file path | see below |

The `--provider` flag overrides `RELAY_AI_PROVIDER`; `--timeout` overrides
`RELAY_AI_TIMEOUT`. **Secrets** (`GEMINI_API_KEY`, `GITHUB_TOKEN`/`GH_TOKEN`)
are only ever read from the environment — never from a file.

### Config file (optional)

Relay reads a `[relay]` TOML table at:

- `$XDG_CONFIG_HOME/relay/config.toml` on macOS/Linux
- `%APPDATA%\relay\config.toml` on Windows

or anywhere the `RELAY_CONFIG` env var points. Example:

```toml
[relay]
provider = "ollama"
ai_timeout = 45
branch_template = "release/<feature>"
max_diff_lines = 250
pr_open = true
gemini_model = "gemini-2.5-flash"
ollama_model = "qwen2.5-coder:7b"
ollama_base_url = "http://localhost:11434"
```

Keys mirror the non-secret env vars above. A missing/malformed file is ignored.

---

## Example

A real session — messy working tree, then a pushed commit and an open PR. No
magic, no third-party dependencies, all in one terminal:

```text
$ relay --team payments
[relay] AI message: feat(payments): add transaction retry handling
[Accept] [Edit] [Retry] [Abort] (a/e/r/A): a
[relay] done: pushed to 'feat/payments'

$ relay pr --open
[relay] opened PR #42: https://github.com/Fiqqar/Relay/pull/42
# ...and the PR opens in your default browser
```

The AI message above is generated from the staged diff, validated as a
Conventional Commit, and yours to review before anything is committed. If the
AI had been offline, Relay would have asked you for the message and continued
from there — the Git workflow never waits on the model.

---

## Product Requirements Document (PRD)

### 1. Problem Statement

Developers repeat a tedious, error-prone Git loop multiple times per day. Common pain points:

1. **Context switching** — staging, message writing, branch admin, pushing, and opening PRs are separate mental tasks.
2. **Low-quality messages** — "wip", "fix stuff", and convention-free messages degrade history.
3. **Manual branch discipline** — team members forget or misname feature branches.
4. **AI adoption friction** — AI tools that fail hard (block the flow) when the model is unreachable are worse than none.

### 2. Goals

- **G1.** Provide a single command that takes the working tree to a pushed commit in both solo and team workflows.
- **G2.** Generate meaningful, Conventional Commits-compliant messages from the staged diff via LLMs.
- **G3.** Never let AI availability block the Git workflow — if the AI is offline, rate-limited, or misconfigured, drop into an interactive manual-input prompt and keep going.
- **G4.** Keep the developer in control: preview, confirm, edit, and abort at meaningful checkpoints.
- **G5.** Ship as a fast, dependency-light, cross-platform global CLI.

### 3. Non-Goals (v1)

- No interactive hunk selection (`git add -p`) — Relay stages all (`git add .`) unless `--staged` is used to commit only what is already staged.
- No CI/CD integration, no changelog generation.
- No commit signing flows beyond what `git` supports natively (pass-through).
- No support for git LFS, submodules, or exotic custom hooks handling.
- No multi-provider routing/failover beyond a single configured provider + manual fallback.

### 4. Personas

- **Solo Developer (Sana)** — works on her own repos, wants speed and clean history, rarely thinks about branches.
- **Team Developer (Marcus)** — works on a shared repo, must keep `main` clean, relies on `<type>/<feature>`-style branches.
- **On-call / Low-connectivity Developer (Priya)** — works offline or on flaky networks; needs the tool to never be a blocker.

### 5. Functional Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-1 | Provide `relay` as the primary command; default mode **solo**, selectable via `--solo` / `--team`. | P0 |
| FR-2 | **Solo mode:** `git add .` → generate message → `git commit` → `git push origin <current-branch>`. | P0 |
| FR-3 | **Team mode:** `git add .` → generate message → `git checkout -b <branch>` → `git commit` → `git push -u origin <branch>`. | P0 |
| FR-4 | Read the staged diff (`git diff --cached`) and send it to the configured LLM provider. | P0 |
| FR-5 | Support **Gemini API** (default) and local **Ollama** providers behind a common interface. | P0 |
| FR-6 | Parse/validate the AI response into a **Conventional Commit** message (`type(scope): subject`). | P0 |
| FR-7 | On AI failure (timeout, rate limit, offline, invalid output), **fall back to a manual message prompt** in the same terminal and continue the workflow. | P0 |
| FR-8 | Preflight checks: is a Git repo present? are there staged/unstaged changes? is a remote configured? Abort early with clear messages otherwise. | P0 |
| FR-9 | Team-mode branch naming uses a configurable template (default `<type>/<feature>`); feature name from `--team <name>`, the current branch, or a prompt. | P1 |
| FR-10 | Show the generated message and request confirmation before committing (skippable via `--yes`). | P1 |
| FR-11 | Support `--dry-run` (plan + message, no mutations) and `--no-push`. | P1 |
| FR-12 | Respect git pre-commit hooks; surface hook output and abort cleanly on failure. | P1 |
| FR-13 | Handle push rejection (non-fast-forward) with actionable guidance (`pull --rebase`). | P1 |
| FR-14 | Truncate very large diffs to the provider's token budget and report truncation. | P2 |
| FR-15 | Provide `--verbose` command logging. (`relay doctor` shipped as a subcommand.) | P2 |
| FR-16 | Provide `relay pr` to create GitHub Pull Requests via GitHub REST API without third-party dependencies. | P1 |

### 6. Non-Functional Requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | **Performance:** sub-500 ms CLI overhead excluding LLM latency; parallel-safe, no network calls during preflight. |
| NFR-2 | **Portability:** pure-stdlib Python; runs on Windows, macOS, Linux with no runtime deps beyond `git` itself. |
| NFR-3 | **Security:** secrets (`GEMINI_API_KEY`, `GITHUB_TOKEN`/`GH_TOKEN`) are only ever read from the environment, never from a file; secrets never logged. |
| NFR-4 | **Reliability:** no partial states. If push fails after commit, the error reports state and the exact retry command. |
| NFR-5 | **Observability:** structured logs, clear exit codes (0 success, 1 workflow error, 130 user abort). |
| NFR-6 | **Testability:** AI providers behind an interface with a mock; Git executor unit-testable. |
| NFR-7 | **Usability:** every failure has a human-readable explanation plus a suggested next action. |

### 7. Success Metrics

- **Adoption:** % of daily commits made through Relay within target teams.
- **Acceptance:** % of AI-generated messages committed **without edits** after confirmation.
- **Reliability:** % of Relay runs that complete end-to-end without manual intervention.
- **Quality:** Conventional-Commits compliance rate across commits made with Relay.

### 8. Milestones

| Milestone | Scope | Exit criteria |
| --- | --- | --- |
| **M0 — MVP** | CLI, solo + team modes, manual commit input, preflight, push. | `relay` completes both modes with zero AI dependency. | ✅ done |
| **M1 — Ollama** | Ollama provider, diff collection, message validation, confirm step. | AI messages with a local model; fallback proven via forced failure. | ✅ done |
| **M2 — Gemini** | Gemini provider, env-var config. | Gemini selectable; keys never logged. | ✅ done |
| **M3 — Release & Distribution** | GitHub Release automation (`.github/workflows/release.yml` on `v*` tags), sdist + wheel builds, cross-platform verification (CI matrix: 3 OS × 3 Python versions). | Package published and attached to a GitHub Release for 3 platforms. | ✅ done |

## Roadmap

- **v0.1** — MVP: solo + team modes, Gemini + Ollama providers, manual fallback. ✅ shipped
- **v0.2** — diff truncation (FR-14), `relay doctor`, `relay pr` (GitHub PR automation), CI + pytest suite, TOML config file. ✅ shipped (current snapshot)
- **v0.3** — release pipeline: publish sdist/wheels to GitHub Releases on a tag (`git tag v0.3.0 && git push origin v0.3.0`); Homebrew / Scoop packaging. ✅ shipped
- **v0.4** — DX layer: telemetry opt-in, man pages (`man relay`), shell completions (bash/zsh/fish/PowerShell), `relay undo`, `relay squash`, `relay stage` (incl. `git add -p`), OpenAI / Anthropic / llama.cpp providers, GitLab MR creation. ✅ shipped
- **v1.0** — GA: stability freeze, coverage gate, docs + packaging finalized. *(planned — see [Roadmap](docs/ROADMAP.md))*
- **v0.5 – v0.8** — team default-branch safety, distribution polish, more providers/forges, GA hardening. *(planned — see [Roadmap](docs/ROADMAP.md))*
- **Later** — team default-branch safety rules.

## Documentation

- [System Architecture](docs/ARCHITECTURE.md)
- [Logical Flow & State Machine](docs/FLOW.md)
- [Roadmap → v1.0.0](docs/ROADMAP.md)

---

_License: MIT. Maintained for developers who value clean Git history._