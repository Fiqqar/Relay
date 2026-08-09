# Relay Roadmap

Ordered plan from the current release to **v1.0.0 (GA)**. Versions `0.1.0`
through `0.4.1` are shipped and closed; `0.5.0`+ are planned.

## Legend

- `[x]` done · `[ ]` planned · `[~]` in progress
- **Exit criteria** = the definition of done that gates the next version.

---

## Shipped history (`0.1.0` → `0.4.1`)

### v0.1.0 — MVP

- [x] `relay` CLI with `--solo` and `--team [FEATURE]` modes
- [x] Manual commit-message input (zero AI dependency)
- [x] Preflight checks (git repo, identity, branch)
- [x] Push with clean error reporting (NFR-4)
- [x] Ollama provider (local models) with fallback
- [x] Conventional-Commits message validation

**Exit criteria:** `relay` completes both modes with zero AI dependency. ✅

### v0.2.0 — Workflow DX

- [x] Gemini provider + env-var config (`GEMINI_API_KEY`, never logged)
- [x] Diff truncation to provider token budget (FR-14)
- [x] `relay doctor` — diagnose PATH / git / AI / identity
- [x] `relay pr` — GitHub PR creation via REST (FR-16)
- [x] `relay amend` — rewrite last commit message
- [x] `--staged` / `--no-verify` flags
- [x] Multi-line commit messages (subject + body)
- [x] Dynamic team branch naming from commit type
- [x] AI retry with backoff; manual fallback on persistent failure
- [x] TOML config file (internal parser, no runtime deps)
- [x] CI + pytest suite (3 OS × 3 Python versions)

**Exit:** Python 3.10+ TOML config, stub-free AI providers behind an interface. ✅

### v0.3.0 — Release & Distribution

- [x] `.github/workflows/release.yml` — sdist + wheel on `v*` tags
- [x] Cross-platform CI matrix (Windows / macOS / Linux)
- [x] Homebrew formula (`Formula/relay.rb`)
- [x] Scoop manifest (`bucket/relay.json`)
- [x] Version-consistency guard (`tests/test_version.py`)
- [x] Release runbook (`RELEASE.md`)

**Acceptance:** package published to GitHub Release, installable via Homebrew + Scoop. ✅

### v0.4.0 — DX Layer

- [x] Shell completions: bash / zsh / fish / PowerShell
- [x] `relay man` — roff man page (raw f-string fix in 0.4.1)
- [x] Usage telemetry (opt-in, off by default)
- [x] `relay undo` — soft reset of last commit
- [x] `relay squash` — fold last N commits (local-only, never push)
- [x] `relay stage` — interactive file/hunk staging (`git add -p`)
- [x] OpenAI + Anthropic providers
- [x] OpenAI-compatible provider (llama.cpp / vLLM via `OPENAI_BASE_URL`)
- [x] GitLab MR support (`gitlab.com` + self-hosted, `GITLAB_TOKEN`)
- [x] `relay doctor` checks all 4 providers + forge tokens

**Acceptance:** provider API + forge support, all 479 tests green. ✅

### v0.4.1 — Patch (regression fixes)

- [x] **`relay man` form-feed bug** — `\fI`/`\fR`/`\fB` were escaped as Python
      `\x0c` in a plain f-string; now a raw f-string + regression test
- [x] **Homebrew install docs** — Homebrew ≥6 rejects raw-URL formulas; README
      + formula comment fixed to tap-by-URL
- [x] Formula + Scoop manifest re-pointed to `v0.4.1` assets
- [x] Verified end-to-end: Kali/WSL2 (`brew test` pass) + Windows (`scoop update`)

**Acceptance:** 0 form-feed bytes in `relay man`; both package managers install. ✅

---

## Planned (`0.5.0` → `1.0.0`)

### v0.5.0 — Team default-branch safety

- [ ] `relay team` mode refuses to commit to a configured protected branch
      by default (origin of the `team` naming; keeps solo-convention commits)
- [ ] Default-branch rules in TOML config (e.g. `[team.protected] branches = ["main"]`)
- [ ] Opt-out escape hatch (`--yes` / explicit flag) for force paths
- [ ] `relay doctor` reports protected-branch config + warns on risky state
- [ ] Unit tests for each safety rule (mirror `tests/test_doctor.py` patterns)

**Exit:** pushing to a protected branch is impossible by default on the
configured rules; tests cover every rule.

### v0.6.0 — Distribution polish

- [ ] Submit `relay.json` to `ScoopInstaller/Extras`
- [ ] Publish Homebrew **tap repo** (`homebrew-Relay`) so `brew tap Fiqqar/relay`
      works without an explicit URL
- [ ] Auto-update `checkver`/`autoupdate` verified on fresh machines
- [ ] `relay --version` smoke test on verified install paths in CI matrix
- [ ] Docs: single-line install instructions for each supported platform

**Exit:** clean one-liner installs for Windows / macOS / Linux via the resubmitted
storefronts (`scoop install extras/relay`, `brew install Fiqqar/relay/relay`).

### v0.7.0 — Provider & forge breadth

- [ ] Additional providers (Mistral, Groq, xAI) — add a class in `relay/ai/` +
      register in `_PROVIDERS`
- [ ] Bitbucket client for `relay pr` (pattern: new client + routing in `pr.py`)
- [ ] Provider per-command override already present (`--provider`); add per-mode
      default in config maybe (`[ai] default = "ollama"`)
- [ ] Doc: provider matrix (keys, base URLs, compat notes) in README/ARCHITECTURE

**Exit:** ≥ 6 providers + 2 forges covered; new provider = drop-in class + test.

### v0.8.0 — GA hardening

- [ ] Freeze CLI surface (subcommands/flags) — anything new requires a design note
- [ ] 100% error messages: every failure has a human-readable next action (NFR-7)
- [ ] Coverage gate in CI (e.g. ≥ 90% branch)
- [ ] Security review: secrets only from env, never logged (NFR-3)
- [ ] Performance pass (NFR-1): sub-500 ms CLI overhead excluding LLM latency

**Exit:** CI-green on 3 OS × 3 Python; coverage gate; error-message audit logged.

### v1.0.0 — GA

- [ ] Mark all `M` milestones (M0–M3) as **stable**, no loose ends
- [ ] Public docs: README/ARCHITECTURE/FLOW + roadmap point to stable API
- [ ] Cut `v1.0.0` per `RELEASE.md`; artifacts verified on all channels
- [ ] Deprecation policy documented (semver commits)

**Exit:** `v1.0.0` released; Homebrew + Scoop point at it; README says stable.

---

## Non-goals (explicitly out of scope)

- GUI/TUI — Relay is a CLI; interactive selection stays in the terminal
- Remote model hosting — providers are BYO-key / BYO-endpoint
- CI/CD pipeline integration (beyond git push) — hooks/forges remain user-managed
- Multi-user server fleet — single-user desktop tool