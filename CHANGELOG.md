# Changelog

All notable changes to Relay are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** Release tags exist from `v0.3.0` onward; `v0.1.0` and `v0.2.0`
> shipped before the tag workflow existed, so their dates below are the date
> of the last commit in each era (from `git log`), not a tag date.

## [Unreleased]

### Security
- `relay pr` now enforces a GitLab trust boundary. The host is derived from
  the `origin` remote — attacker-controllable data — so `GITLAB_TOKEN` is
  only ever sent to `gitlab.com` unless a self-hosted host is explicitly
  allowed via `RELAY_TRUSTED_GITLAB_HOSTS` (env) or `trusted_gitlab_hosts`
  (the `[relay]` config table). Untrusted hosts are refused before any token
  is read or any request is made (credential-exfiltration hardening).

### Changed
- `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` documented as a trust decision:
  the API key is sent to that host as a Bearer credential, so it must only
  point at endpoints you control (README Security section).
- Prompt injection from diffs documented: the staged diff is untrusted LLM
  input; the model's output is only used as a sanitized, user-confirmed
  commit message and is never executed.

## [0.6.0] - 2026-08-16

### Fixed
- TOML parser no longer silently mis-parses: unterminated strings, unknown
  escape sequences, duplicate keys, and scalar/table redefinitions now fail
  loudly (with a line number) instead of returning wrong values or dropping
  data — a config file containing any of them falls back to defaults with the
  usual one-time warning.
- Workflow error messages now always carry an actionable next step (NFR-7):
  `relay undo` on an empty repo, `relay squash` with no commits / not enough
  history, `relay stage` selection mistakes, `relay pr` without an `origin`
  remote, and git timeouts/failures each tell the developer exactly what to
  do next.
- The Scoop manifest now declares `git` as a runtime dependency and runs its
  launcher in Python isolated mode (`-I`) with the bundled lib path, so a
  `relay.py` / `relay/` package in the working directory can never shadow the
  installed CLI (flagged in the Scoop Extras review, PR #18536).

### Added
- `tests/test_error_audit.py` — a static NFR-7 gate that scans every
  `raise <RelayError>` site under `relay/` and requires an exact
  command/flag reference or an imperative verb in the message.
- TOML parser accepts spec-valid `1e5`-style exponent floats and `\UXXXXXXXX`
  escapes; booleans are case-strict (`True` is now rejected, matching
  `tomllib`).

### Changed
- Coverage gate raised from 85% to 90% branch coverage (`pyproject.toml`,
  `docs/WORKING_RULES.md`, `AGENTS.md`, `CONTRIBUTING.md`).
- Roadmap re-scoped: v0.8 becomes core workflow depth (hunk-level AI
  messages, multi-repo, custom hooks, AI diff ignore paths); GA hardening
  moves to v0.9.

## [0.5.8] - 2026-08-13

### Fixed
- `relay` on Windows no longer crashes with `'NoneType' object has no
  attribute 'strip'` when a repo contains bytes the locale codec (cp1252)
  cannot decode — git output is now read as UTF-8 with replacement, so a
  binary-ish diff (e.g. in a Unity project) never kills subprocess's reader
  thread and leaves `stdout` as `None`.

## [0.5.7] - 2026-08-13

### Fixed
- `relay team` no longer strands you on an orphan branch when the commit fails —
  it checks out the original branch and deletes the empty feature branch
  (best-effort; a cleanup failure prints a reflog hint instead of crashing).
- `relay squash` restores `HEAD` if the fold commit fails, so the branch is
  never left mid-reset with the fold unrecoverable.
- Network git commands (`push`/`fetch`/`ls-remote`) now time out after 60s
  instead of hanging the CLI forever on an unreachable remote.
- AI provider responses are capped at 1 MiB — an oversized body is treated as
  an unusable answer and falls back instead of being parsed (H-02).
- `relay` on a machine without git on PATH reports a clear error instead of a
  raw `FileNotFoundError` traceback (H-16).
- A missing API key no longer aborts the run — the provider is built lazily
  and solo/team degrade to manual input (H-14).
- Binary-only staged diffs skip the AI entirely and go straight to manual
  input instead of asking the AI to summarize content it cannot read (H-12).
- Solo mode refuses to push on a detached HEAD, committing safely and telling
  you how to turn the commit into a branch (H-13).
- `relay squash --count N` now feeds the root commit's own changes to the AI
  when folding the whole history, via the empty-tree diff base (H-11).
- The config file is parsed at most once per (path, mtime, size) state instead
  of re-opened on every config access (H-08).
- Telemetry collection URLs are restricted to `https://` — a non-HTTPS or
  local `RELAY_TELEMETRY_URL` is ignored with a warning (C-02).
- Protected-branch matching is case-insensitive, so `Main` cannot bypass a
  rule written for `main` (M-14).
- `max_diff_lines` clamps to a positive floor of 1 line, so a bad config value
  can no longer send the AI an empty prompt (M-02).
- Invalid `RELAY_AI_TIMEOUT` / `RELAY_MAX_DIFF_LINES` env values now warn
  instead of being silently ignored (M-11).
- Forge HTTP error bodies (GitHub/GitLab) are read with a 10 KiB cap so a
  huge error response can't be slurped into memory.
- A malformed config file prints a one-time warning and falls back to defaults
  instead of silently dropping the file (L-15).
- `relay team` on a protected/default branch now prompts for a real feature
  name instead of deriving it from `main`/`master` (L-10).

### Changed
- `BUG.md` removed — every triaged issue is resolved or marked false-positive.
- `docs/WORKING_RULES.md` and `AGENTS.md` translated to English.
- Test suite expanded to 638 tests (~96% branch coverage), covering the
  error/fallback paths above.

## [0.5.6] - 2026-08-12

### Fixed
- `relay squash` no longer silently folds unrelated pre-staged files into the
  new commit (`reset --soft` kept the index as-is, so anything staged before
  the squash leaked in); it now refuses up front with `git reset -- <path>` in
  the message.
- `relay squash --count N` now works when `N` equals the total history —
  previously `HEAD~N` pointed past the root commit and the fold failed with
  "not enough history"; the whole branch now folds into a single root-amended
  commit.
- `relay undo` on a repository with exactly one commit now gives a clear,
  actionable error instead of leaking git's raw `fatal: unknown revision`.
- The `relay squash` "not enough history" message now reports the real commit
  count (the old one referenced a non-existent `commit_count()` helper).

### Added
- `docs/WORKING_RULES.md` — the mandatory rules document for contributors and
  AI agents (one logical change per commit, coverage gate before push, zero
  runtime deps, no mass reformatting). Root `AGENTS.md` points agents at it,
  and `CONTRIBUTING.md` links it as the starting point.

## [0.5.5] - 2026-08-12

### Added
- `LICENSE` file (MIT) matching the license declared in `pyproject.toml`.
- `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`.
- CI coverage gate (`pytest --cov` with a branch-coverage threshold).
- Static analysis (`ruff`) and type checking (`mypy`) jobs in CI.
- E2E scripts (`e2e_test.sh` / `e2e_test.ps1`) wired into CI.

### Fixed
- Type-safety and lint issues flagged by `mypy` and `ruff`, including a
  possible `None` `api_key` dereference in the Gemini/Anthropic providers, a
  mistyped GitLab MR payload (`dict[str, str]` vs. `dict[str, str | bool]`),
  and a duplicated `test_config` test.
- E2E scripts piped only a subject line, but the manual-input fallback reads a
  subject followed by a blank line — `input()` hit EOF and crashed; the scripts
  now terminate stdin with a blank line.

## [0.5.4] - 2026-08-11

### Fixed
- `relay squash` no longer aborts the whole fold when the AI is offline,
  rate-limited, or returns an unusable response — it falls back to the top
  commit's subject so a non-destructive local operation degrades like the rest
  of the tool.
- `relay squash --message` no longer fails without an API key — the AI provider
  is now built lazily; a missing key means "no provider" and the fallback path
  runs.
- TOML parser mis-handled escaped quotes (`_strip_comment`, `_split_kv`,
  `_split_items`); all three now close a string only when an even run of
  backslashes precedes the quote.
- Removed the dead `SUBCOMMAND_FLAGS` map from `completions.py`.

### Changed
- Test suite made hermetic: no environment-dependent tests, `api_error`
  HTTP/retry branches now covered (525 tests green).

## [0.5.3] - 2026-08-11

### Fixed
- Fish completion dropped 3 subcommands (`stage`, `man`, `telemetry`); it now
  generates subcommand lines from the `SUBCOMMANDS` source of truth and the
  test asserts every shell advertises every subcommand.

## [0.5.2] - 2026-08-11

### Fixed
- `relay squash` fed the AI the wrong diff (the current index instead of the
  combined diff of the squashed commits); now uses `git diff base..tip` via
  `GitManager.diff_range` / `stat_range`, with regression tests asserting the
  staging area is never touched.

## [0.5.1] - 2026-08-11

### Fixed
- `--yes` decoupled from protected-branch safety — it now only skips the
  confirmation prompt and never bypasses the default-branch guard; opting out
  requires the explicit `--allow-protected` flag.
- `max_diff_lines` tolerant parsing — wrong-typed config entries fall back to
  the default instead of raising or silently capping the diff at one line.
- Feature-name prompt isolated in `_prompt_feature_name()` (single seam for a
  future `--no-input`/CI mode).
- Homebrew formula + Scoop manifest re-pointed to the shipped version's assets;
  `RELEASE.md` step 1b now requires re-pointing so a release can never
  silently ship stale package channels.

## [0.5.0] - 2026-08-11

### Added
- Team-mode default-branch safety: `relay team` refuses to commit to a
  configured protected branch by default.
- Protected-branch rules in TOML config (`[team.protected] branches = [...]`)
  or the `RELAY_PROTECTED_BRANCHES` env var.
- `--allow-protected` escape hatch for force paths.
- `relay doctor` reports protected-branch config and warns on risky state.
- Unit tests for each safety rule (`tests/test_protected.py`).

### Security
- New README Security section: env-only secrets, no shell injection surface,
  opt-in telemetry, checksum verification for production installs.

## [0.4.1] - 2026-08-09

### Fixed
- `relay man` rendered troff escapes as form-feed bytes (`\x0c`); now a raw
  f-string plus regression test.
- Homebrew install docs — Homebrew ≥6 rejects raw-URL formulas; README +
  formula comment fixed to tap-by-URL.

## [0.4.0] - 2026-08-09

### Added
- Shell completions: bash / zsh / fish / PowerShell (`relay completions`).
- `relay man` — roff man page.
- Opt-in usage telemetry, off by default (`relay telemetry`).
- `relay undo` — soft reset of the last commit.
- `relay squash` — fold the last N commits into one Conventional Commit.
- `relay stage` — interactive file/hunk staging (`git add -p`).
- OpenAI, Anthropic, and OpenAI-compatible (llama.cpp/vLLM) providers.
- GitLab MR support (`gitlab.com` + self-hosted, `GITLAB_TOKEN`).
- `relay doctor` checks all 4 providers + forge tokens.

## [0.3.0] - 2026-08-08

### Added
- Release pipeline: sdist + wheel builds published to GitHub Releases on `v*`
  tags (`.github/workflows/release.yml`).
- Cross-platform CI matrix (Windows / macOS / Linux).
- Homebrew formula (`Formula/relay.rb`) and Scoop manifest (`bucket/relay.json`).
- Version-consistency guard (`tests/test_version.py`).
- Release runbook (`RELEASE.md`).

## [0.2.0] - 2026-08-08

### Added
- Gemini provider + env-var config (`GEMINI_API_KEY`, never logged).
- Diff truncation to the provider's token budget.
- `relay doctor` — diagnose PATH / git / AI / identity.
- `relay pr` — GitHub PR creation via REST, incl. draft PRs (`--draft`).
- `relay amend` — rewrite the last commit's message in place.
- `--staged` / `--no-verify` flags.
- Multi-line commit messages (subject + body).
- Dynamic team-branch naming from commit type.
- AI retry with backoff; manual fallback on persistent failure.
- TOML config file (internal parser, no runtime deps).
- CI + pytest suite (3 OS × 3 Python versions).

## [0.1.0] - 2026-08-03

### Added
- `relay` CLI with `--solo` and `--team [FEATURE]` modes.
- Manual commit-message input (zero AI dependency).
- Preflight checks (git repo, identity, branch).
- Push with clean error reporting.
- Ollama provider (local models) with manual fallback.
- Conventional-Commits message validation.

[Unreleased]: https://github.com/Fiqqar/Relay/compare/v0.5.8...HEAD
[0.5.8]: https://github.com/Fiqqar/Relay/compare/v0.5.7...v0.5.8
[0.5.7]: https://github.com/Fiqqar/Relay/compare/v0.5.6...v0.5.7
[0.5.6]: https://github.com/Fiqqar/Relay/compare/v0.5.5...v0.5.6
[0.5.5]: https://github.com/Fiqqar/Relay/compare/v0.5.4...v0.5.5
[0.5.4]: https://github.com/Fiqqar/Relay/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/Fiqqar/Relay/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/Fiqqar/Relay/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/Fiqqar/Relay/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/Fiqqar/Relay/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/Fiqqar/Relay/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Fiqqar/Relay/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Fiqqar/Relay/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Fiqqar/Relay/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Fiqqar/Relay/releases/tag/v0.1.0
