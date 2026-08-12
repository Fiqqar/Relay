# Changelog

All notable changes to Relay are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `LICENSE` file (MIT) matching the license declared in `pyproject.toml`.
- `CHANGELOG.md` itself, `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`.
- CI coverage gate (`pytest --cov` with a branch-coverage threshold).
- Static analysis (`ruff`) and type checking (`mypy`) jobs in CI.
- E2E scripts (`e2e_test.sh` / `e2e_test.ps1`) wired into CI.

## [0.5.4] - 2026-08-12

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

## [0.5.3] - 2026-07-29

### Fixed
- Fish completion dropped 3 subcommands (`stage`, `man`, `telemetry`); it now
  generates subcommand lines from the `SUBCOMMANDS` source of truth and the
  test asserts every shell advertises every subcommand.

## [0.5.2] - 2026-07-22

### Fixed
- `relay squash` fed the AI the wrong diff (the current index instead of the
  combined diff of the squashed commits); now uses `git diff base..tip` via
  `GitManager.diff_range` / `stat_range`, with regression tests asserting the
  staging area is never touched.

## [0.5.1] - 2026-07-15

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

## [0.5.0] - 2026-07-08

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

## [0.4.1] - 2026-06-18

### Fixed
- `relay man` rendered troff escapes as form-feed bytes (`\x0c`); now a raw
  f-string plus regression test.
- Homebrew install docs — Homebrew ≥6 rejects raw-URL formulas; README +
  formula comment fixed to tap-by-URL.

## [0.4.0] - 2026-06-11

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

## [0.3.0] - 2026-05-27

### Added
- Release pipeline: sdist + wheel builds published to GitHub Releases on `v*`
  tags (`.github/workflows/release.yml`).
- Cross-platform CI matrix (Windows / macOS / Linux).
- Homebrew formula (`Formula/relay.rb`) and Scoop manifest (`bucket/relay.json`).
- Version-consistency guard (`tests/test_version.py`).
- Release runbook (`RELEASE.md`).

## [0.2.0] - 2026-05-10

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

## [0.1.0] - 2026-04-22

### Added
- `relay` CLI with `--solo` and `--team [FEATURE]` modes.
- Manual commit-message input (zero AI dependency).
- Preflight checks (git repo, identity, branch).
- Push with clean error reporting.
- Ollama provider (local models) with manual fallback.
- Conventional-Commits message validation.

[Unreleased]: https://github.com/Fiqqar/Relay/compare/v0.5.4...HEAD
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
