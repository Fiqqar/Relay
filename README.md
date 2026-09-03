# Relay

<p align="left">
  <a href="https://github.com/Fiqqar/Relay/releases"><img src="https://img.shields.io/github/v/release/Fiqqar/Relay?style=for-the-badge&logo=github&logoColor=white" alt="Release"></a>
  <a href="https://github.com/Fiqqar/Relay/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Fiqqar/Relay/ci.yml?branch=main&label=CI&style=for-the-badge&logo=githubactions&logoColor=white" alt="CI"></a>
  <a href="https://github.com/Fiqqar/Relay/security/code-scanning"><img src="https://img.shields.io/badge/Security-CodeQL-success?style=for-the-badge&logo=github&logoColor=white" alt="CodeQL"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=for-the-badge" alt="Ruff"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License: MIT"></a>
</p>

**Your Git workflow, on autopilot.**

One command collapses the tedious daily Git loop into a reviewable, AI-assisted workflow:

```text
git add .  →  generate Conventional Commit  →  git commit  →  git push  →  open PR
```

<p align="center">
  <img src="assets/relay-demo.gif" alt="Relay Demo" width="100%" style="max-width: 800px; border-radius: 8px;">
</p>

Relay reads your staged diff, consults your preferred AI model (Gemini, local Ollama, OpenAI, Anthropic, Mistral, Groq, or xAI), and formats a compliant **Conventional Commit**. If the AI is rate-limited, offline, or unavailable, Relay **never blocks your flow** — it drops straight into a manual terminal prompt and continues smoothly.

---

## Highlights

- ⚡ **Zero Runtime Dependencies** — 100% Python standard library. Instant install, minimal attack surface, works offline.
- 🤖 **AI Conventional Commits** — Generates meaningful `type(scope): subject` messages from your actual staged changes.
- 🛡️ **Human-in-the-Loop Fallback** — Always review before committing (`[Accept] [Edit] [Retry] [Abort]`). Seamless terminal fallback if AI fails.
- 🚀 **Solo & Team Modes** — Commit and push straight to the current branch (`--solo`), or auto-create `<type>/<feature>` branches with default-branch protection (`--team`).
- 🌐 **Instant Forge Pull Requests** — Open PRs/MRs natively on GitHub, GitLab, and Bitbucket Cloud (`relay pr`) without external CLI tools.
- 🔒 **Security-First Architecture** — Secrets are strictly environment-only. No `shell=True` subprocess calls. Protected-branch safety guards against accidental pushes to `main`.

---

## Installation

Requires **Python 3.10+** and `git` on your `PATH`.

| Platform | Package Manager | Command |
| :--- | :--- | :--- |
| **macOS / Linux** | Homebrew | `brew tap Fiqqar/relay && brew install Fiqqar/relay/relay` |
| **Windows** | Scoop | `scoop bucket add relay https://github.com/Fiqqar/Relay && scoop install relay/relay` |
| **Anywhere** | pip / git | `pip install "git+https://github.com/Fiqqar/Relay.git"` |

> Or install locally from source:
> ```bash
> python install.py --yes
> ```

---

## Quick Start

```bash
# 1. Set your API key (environment variable)
export GEMINI_API_KEY="your-api-key"   # or OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.

# 2. Verify installation & health
relay doctor

# 3. Daily workflow:
relay --solo                     # Stage all, generate AI commit, push to current branch
relay --team "payments"          # Create feat/payments branch, commit, push
relay pr --open                  # Create PR and open it in your browser
```

---

## Core Commands & Flags

| Command / Flag | Purpose |
| :--- | :--- |
| `relay --solo` | Stage all, generate commit message, push to current branch *(default)*. |
| `relay --team [FEATURE]` | Auto-create `<type>/<feature>` branch, commit, push upstream. |
| `relay pr` | Open a GitHub / GitLab / Bitbucket PR directly from terminal (`-d` draft, `-o` open browser). |
| `relay undo` | Soft-reset the last commit (`git reset --soft HEAD~1`); changes remain staged. |
| `relay amend` | Regenerate commit message for the last commit in place (never force pushes). |
| `relay squash` | Fold the last N commits into a clean single Conventional Commit locally. |
| `relay stage` | Interactive file and hunk staging (`git add -p` helper). |
| `relay doctor` | Diagnose environment (Python, Git, PATH, provider credentials, forge tokens). |
| `--yes` | Auto-accept AI message and skip confirmation prompt. |
| `--staged` | Only commit already-staged changes (skips `git add .`). |
| `--dry-run` | Preview diff, AI message, and execution plan without making changes. |
| `--allow-protected` | Override team-mode default-branch protection. |
| `--hunks` | Generate multi-part Conventional Commit message per changed file/hunk. |

---

## AI Providers & Configuration

Relay works out-of-the-box with environment variables, or an optional TOML config file (`~/.config/relay/config.toml` or `%APPDATA%\relay\config.toml`).

| Provider | Required Env Variable | Default Model | Custom Base URL (Env) |
| :--- | :--- | :--- | :--- |
| **Gemini** *(default)* | `GEMINI_API_KEY` | `gemini-2.5-flash` | — |
| **Ollama** *(local)* | *None (local)* | `qwen2.5-coder:7b` | `OLLAMA_BASE_URL` (`http://localhost:11434`) |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o-mini` | `OPENAI_BASE_URL` (vLLM, llama.cpp compatible) |
| **Anthropic** | `ANTHROPIC_API_KEY` | `claude-3-5-haiku-latest` | `ANTHROPIC_BASE_URL` |
| **Mistral** | `MISTRAL_API_KEY` | `mistral-small-latest` | `MISTRAL_BASE_URL` |
| **Groq** | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | `GROQ_BASE_URL` |
| **xAI** | `XAI_API_KEY` | `grok-beta` | `XAI_BASE_URL` |

### Example Config (`config.toml`)

```toml
[relay]
provider = "gemini"
branch_template = "feat/<feature>"
pr_open = true

[team.protected]
branches = ["main", "master", "develop"]

[relay.ignore]
paths = ["dist/*", "*.lock", "package-lock.json"]
```

> 🔐 **Security Guarantee:** Secrets (`*_API_KEY`, `GITHUB_TOKEN`, `GITLAB_TOKEN`) are **strictly environment-only** and never read from config files or logged to disk.

---

## Documentation

Comprehensive architectural design and governance documentation:

- 📖 [Product Specification (PRD)](docs/SPEC.md) — Personas, functional requirements, and non-goals.
- 🏗️ [Architecture & Components](docs/ARCHITECTURE.md) — Data flow and internal module design.
- 🔄 [State Machine & Logic Flow](docs/FLOW.md) — State transitions, error matrix, and edge cases.
- 📜 [Architecture Decision Records (ADR)](docs/ADR.md) — Permanent rationale behind key technical choices.
- 🛡️ [Threat Model & Security](docs/THREAT_MODEL.md) — Security boundaries and attack surface mitigations.
- 🚦 [Working Rules](docs/WORKING_RULES.md) — Mandatory engineering rules (90% coverage gate, zero dependencies).
- 🗺️ [Project Roadmap](docs/ROADMAP.md) — Milestones, shipped history, and future directions.

---

## Contributing & License

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/WORKING_RULES.md](docs/WORKING_RULES.md) before opening a pull request.

Relay is distributed under the [MIT License](LICENSE).
