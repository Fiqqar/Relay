# Relay


[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)](https://www.python.org/)

**Your Git workflow, on autopilot.**

One command. From a messy working tree to a clean, AI-authored **Conventional Commit**, pushed, and instantly opened as a Pull Request - in Solo or Team mode.

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
- [Product Requirements Document (PRD)](#product-requirements-document-prd)
- [Roadmap](#roadmap)
- [Documentation](#documentation)

---

## Why Relay

Daily Git work is repetitive and context-switching: stage files, invent a commit message, push, open a browser, and create a Pull Request. Commit messages are often lazy, inconsistent, or convention-free — which pollutes history and hurts `git bisect`, changelog generation, and code review.

Relay collapses this into a single decision-free command while keeping the developer in control at every meaningful checkpoint.

## Features

- **Solo mode** — stage all, generate message, commit, push to the current branch.
- **Team mode** — stage all, generate message, create & checkout a new branch (e.g. `status/<feature>`), push that branch.
- **Instant Pull Requests** — open a GitHub Pull Request directly from your terminal using zero-dependency REST API integration (`relay pr`).
- **AI-powered Conventional Commits** — reads `git diff --cached`, sends it to an LLM, validates the response as a Conventional Commit.
- **Pluggable AI providers** — **Gemini API** (default) and local **Ollama**, both behind a common interface.
- **Human-in-the-loop fallback** — on AI failure (rate limit, timeout, offline, garbage output), falls back to a manual terminal prompt **without exiting the workflow**.
- **Zero-config & safe** — configuration via environment variables only; `--dry-run`, `--yes`, and an explicit confirm step.
- **Cross-platform** — pure-stdlib Python (no runtime deps beyond `git`), runs on Windows, macOS, and Linux.

## Installation

Requires **Python 3.10+** and `git` on your `PATH`

```bash
pip install git+[https://github.com/Fiqqar/Relay.git](https://github.com/Fiqqar/Relay.git)
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

Distribution via Homebrew / Scoop / GitHub Releases is planned.

## Quick Start

```bash
# 0. (Optional but useful) verify the install in a fresh terminal
relay doctor

# 1. Configure your API keys (once)
set GEMINI_API_KEY=your_key              # Windows cmd (for commit generation)
set GITHUB_TOKEN=ghp_your_token          # Windows cmd (for GitHub PR)

# 2. Run the workflow
relay --solo                     # stage, commit, push to the current branch
relay --team "payments"          # new branch status/payments, commit, push

# 3. Open a Pull Request natively
relay pr                         # opens a PR from current branch to main
```

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
| `pr` | Open a GitHub Pull Request for the current branch (`--base`, `--title`). |
| `doctor` | Diagnose this installation (PATH, git, AI credentials). |
| `--solo` | Stage, commit and push to the current branch (default). |
| `--team [FEATURE]` | Create & checkout `status/<feature>`, commit, push it (feature optional). |
| `--provider {gemini,ollama}` | Override the AI provider (default: gemini). |
| `--timeout SECONDS` | Seconds to wait for the AI response (default: 30, max: 120). |
| `--yes` | Skip the confirmation prompt. |
| `--no-push` | Commit but do not push. |
| `--dry-run` | Show the plan and the generated message, change nothing. |
| `--verbose` | Print the git commands being run. |
| `--version` | Print the version. |

## Configuration

Relay is configured entirely through **environment variables** — no config files to manage.

| Variable | Purpose | Default |
| --- | --- | --- |
| `GEMINI_API_KEY` | Gemini API key (**required** when provider is `gemini`) | — |
| `GITHUB_TOKEN` | GitHub Personal Access Token (for `relay pr`) | — |
| `GEMINI_MODEL` | Gemini model id | `gemini-2.5-flash` |
| `OLLAMA_BASE_URL` | Ollama server endpoint | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama model id | `qwen2.5-coder:7b` |
| `RELAY_AI_PROVIDER` | Default provider: `gemini` \| `ollama` | `gemini` |
| `RELAY_AI_TIMEOUT` | Seconds to wait for the AI response (clamped to 120 max) | `30` |
| `RELAY_BRANCH_TEMPLATE` | Team-mode branch template (`<feature>` placeholder) | `status/<feature>` |

The `--provider` flag overrides `RELAY_AI_PROVIDER`; `--timeout` overrides `RELAY_AI_TIMEOUT`. A TOML config file is a planned addition.

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
- **G3.** Guarantee the workflow always completes even when the AI is unavailable (offline, rate-limited, misconfigured) via a manual-input fallback.
- **G4.** Keep the developer in control: preview, confirm, edit, and abort at meaningful checkpoints.
- **G5.** Ship as a fast, dependency-light, cross-platform global CLI.

### 3. Non-Goals (v1)

- No partial staging / interactive hunk selection — always `git add .`.
- No CI/CD integration, no changelog generation.
- No commit signing flows beyond what `git` supports natively (pass-through).
- No support for git LFS, submodules, or exotic custom hooks handling.
- No multi-provider routing/failover beyond a single configured provider + manual fallback.

### 4. Personas

- **Solo Developer (Sana)** — works on her own repos, wants speed and clean history, rarely thinks about branches.
- **Team Developer (Marcus)** — works on a shared repo, must keep `main` clean, relies on `status/<feature>`-style branches.
- **On-call / Low-connectivity Developer (Priya)** — works offline or on flaky networks; needs the tool to never be a blocker.

### 5. Functional Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-1 | Provide `relay` as the primary command; default mode **solo**, selectable via `--solo` / `--team`. | P0 |
| FR-2 | **Solo mode:** `git add .` → generate message → `git commit` → `git push origin <current-branch>`. | P0 |
| FR-3 | **Team mode:** `git add .` → generate message → `git checkout -b <branch>` → `git commit` → `git push -u origin <branch>`. | P0 |
| FR-4 | Read the staged diff (`git diff --cached`) and send it to the configured LLM provider. | P0 |
| FR-5 | Support **Ollama** (local, default) and **Gemini API** providers behind a common interface. | P0 |
| FR-6 | Parse/validate the AI response into a **Conventional Commit** message (`type(scope): subject`). | P0 |
| FR-7 | On AI failure (timeout, rate limit, offline, invalid output), **fall back to a manual message prompt** in the same terminal and continue the workflow. | P0 |
| FR-8 | Preflight checks: is a Git repo present? are there staged/unstaged changes? is a remote configured? Abort early with clear messages otherwise. | P0 |
| FR-9 | Team-mode branch naming uses a configurable template (default `status/<feature>`); feature name from `--team <name>`, the current branch, or a prompt. | P1 |
| FR-10 | Show the generated message and request confirmation before committing (skippable via `--yes`). | P1 |
| FR-11 | Support `--dry-run` (plan + message, no mutations) and `--no-push`. | P1 |
| FR-12 | Respect git pre-commit hooks; surface hook output and abort cleanly on failure. | P1 |
| FR-13 | Handle push rejection (non-fast-forward) with actionable guidance (`pull --rebase`). | P1 |
| FR-14 | Truncate very large diffs to the provider's token budget and report truncation. | P2 |
| FR-15 | Provide `--verbose` command logging. (`relay doctor` deferred.) | P2 |
| FR-16 | Provide `relay pr` to create GitHub Pull Requests via GitHub REST API without third-party dependencies. | P1 |

### 6. Non-Functional Requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | **Performance:** sub-500 ms CLI overhead excluding LLM latency; parallel-safe, no network calls during preflight. |
| NFR-2 | **Portability:** pure-stdlib Python; runs on Windows, macOS, Linux with no runtime deps beyond `git` itself. |
| NFR-3 | **Security:** API keys read from env var or config; secrets never logged; config file permissions `0600` on POSIX. |
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
| **M3 — Polish** | `--dry-run`, `--yes`, diff truncation, hooks handling, `relay doctor`, GitHub PR automation (`relay pr`). | Full feature set; package published for 3 platforms. | in progress |

## Roadmap

- v0.1 — current Python implementation (solo + team, Gemini + Ollama, manual fallback).
- v0.2 — diff truncation (FR-14), `relay doctor`, GitHub PR creation (`relay pr`), CI + pytest suite, release builds.
- v1.0 — GA: stable config (TOML file), telemetry opt-in, man pages / shell completions.
- Later — GitLab PR creation, multi-commit squashing, `git add -p`-style partial staging, more providers (OpenAI, Anthropic, llama.cpp), team default-branch safety rules.

## Documentation

- [System Architecture](docs/ARCHITECTURE.md)
- [Logical Flow & State Machine](docs/FLOW.md)

---

_License: MIT (planned). Maintained for developers who value clean Git history._