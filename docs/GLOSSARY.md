# Relay — Glossary

> Terms used across docs, code, and defense presentations. Concise definitions with real examples.

| Term | Meaning | Example |
|------|---------|---------|
| **Conventional Commits** | Commit message format `type(scope): subject` so history is machine-parseable | `feat(payments): add retry handling` |
| **type** | Change category: `feat`/`fix`/`docs`/`style`/`refactor`/`test`/`chore`/`perf`/`build`/`ci`/`revert` | `fix(squash): refuse dirty index` |
| **scope** | Area of code affected (optional) | `feat(ai): add groq provider` |
| **Solo mode** | `relay --solo` — stage → commit → push to the current branch | `relay --solo --yes` |
| **Team mode** | `relay --team <feature>` — create `<type>/<feature>` branch, then commit & push | `relay --team payments` → `feat/payments` |
| **Preflight** | Fast checks before mutation: inside a git repo? changes exist? remote configured? | `git rev-parse --is-inside-work-tree` |
| **Staged / Unstaged** | Staged = `git add` done, ready to commit. Unstaged = still in working tree | `relay --staged` commits only already-staged files |
| **Diff (`git diff --cached`)** | Summary of changes to be committed — sent to the LLM | `+ added line` / `- removed line` |
| **`--dry-run`** | Simulation: show plan + message, mutate nothing | `relay --dry-run` |
| **`--yes` / `-y`** | Skip confirmation `Accept/Edit/Retry/Abort` | `relay --solo --yes` |
| **`--no-push`** | Commit only, do not push | Use when you want to review before pushing |
| **`--staged`** | Skip `git add .`, commit only what is already staged | For manual file selection |
| **`--allow-protected`** | Bypass protected-branch guard (`main`/`master`) — only way in team mode | `relay --team fix --allow-protected` |
| **Protected branches** | Branches team mode refuses by default (`main`, `master`, configurable) | `RELAY_PROTECTED_BRANCHES=main,develop` |
| **Branch template** | Branch naming pattern: default `<type>/<feature>` → `feat/payments` | `RELAY_BRANCH_TEMPLATE=release/<feature>` |
| **Fallback (manual)** | If AI fails (offline/rate-limit/timeout/garbage) → prompt for manual input, continue workflow | `[relay] AI unavailable — continuing with manual input.` |
| **Provider** | LLM backend: `gemini`/`ollama`/`openai`/`anthropic`/`mistral`/`groq`/`xai` | `--provider ollama` |
| **Base URL** | Provider HTTP endpoint; can point to local server (llama.cpp/vLLM) — env-only | `OPENAI_BASE_URL=http://localhost:8080/v1` |
| **Token budget / truncation** | Limit on diff size sent to LLM (120 lines + 512 KiB) to stay within window | `RELAY_MAX_DIFF_LINES=250` |
| **Forge** | Git hosting platform: GitHub / GitLab / Bitbucket | `relay pr` creates PR/MR |
| **PR / MR** | Pull Request (GitHub/Bitbucket) / Merge Request (GitLab) — request to merge a branch | `relay pr --draft --open` |
| **Trusted hosts (GitLab)** | Hosts allowed to receive `GITLAB_TOKEN`; prevents exfiltration via fake `origin` | `RELAY_TRUSTED_GITLAB_HOSTS=gitlab.company.com` |
| **Dogfooding** | Commit the Relay project itself using `relay` — not `git commit` | `relay --solo --yes` inside Relay repo |
| **Hermetic tests** | Tests with no network/`$HOME`/real AI — deterministic in CI | `pytest` mocks `urllib.request.urlopen` |
| **Coverage gate 90%** | Minimum 90% branch coverage — push rejected below threshold | `pytest --cov=relay --cov-branch --cov-fail-under=90` |
| **argv-as-list / `shell=False`** | Run `git` without a shell, prevents injection from filenames/branches | `subprocess.run(["git", "push", "--", branch])` |
| **TOCTOU** | Time-of-check vs time-of-use race; Relay uses `git write-tree` guard | Check index before commit |
| **SSRF** | Server-Side Request Forgery — block malicious URL redirects for tokens | Validate `https` + host allowlist |
| **Telemetry (opt-in)** | Anonymous `mode/provider/ok` report — off by default, requires `relay telemetry on` + `RELAY_TELEMETRY_URL` | Never sends diffs/messages |
| **TOML config** | Optional config file `[relay]` at `$XDG_CONFIG_HOME/relay/config.toml` | `provider = "ollama"` |
| **Exit codes** | `0` success, `1` workflow error, `130` user abort (Ctrl-C) | Used by CI & scripts |
| **NFR** | Non-Functional Requirement — performance, security, portability | NFR-3 secrets env-only |
| **ADR** | Architecture Decision Record — log of why a design was chosen | `docs/ADR.md` |

## Quick Abbreviations

- **PRD** — Product Requirements Document (`docs/SPEC.md`)
- **FR/NFR** — Functional / Non-Functional Requirements
- **LLM** — Large Language Model (AI that generates commit messages)
- **CI** — Continuous Integration (GitHub Actions)
- **UKK** — Indonesian vocational competency exam (context for this project's origin)
