# Changelog

All notable changes to Relay are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note:** Release tags exist from `v0.3.0` onward; `v0.1.0` and `v0.2.0`
> shipped before the tag workflow existed, so their dates below are the date
> of the last commit in each era (from `git log`), not a tag date.

## [Unreleased]

## [1.1.2] - 2026-09-05

### Fixed
- **Message-Only Amend**: `relay amend` no longer stages working-tree changes or folds the index into the rewritten commit. A dirty index is refused with an actionable error unless `--staged` explicitly opts in to folding; the AI message is generated from the last commit's own diff.
- **Branch/HEAD TOCTOU Guard**: Re-verify branch and HEAD identity right before commit/push/reset in solo, team, amend, squash, and `relay pr` flows, aborting on a concurrent `git switch` instead of mutating the wrong branch.
- **Squash Dirty-Index Re-check**: Re-run the staged-changes refusal immediately before `reset --soft`, closing the check-then-act window across the AI call and confirmation.
- **Null AI Responses**: A present-but-null (or blank) message field from any provider is rejected as `bad_response` in the shared wrapper, routing to manual-input fallback instead of crashing.
- **Porcelain Arrow Parsing**: Only split `old -> new` for actual rename entries; untracked files literally named e.g. `a -> b` are no longer misparsed.
- **Doctor Output Sanitization**: Strip terminal escape sequences from git-config values in the `relay doctor` report.
- **Installer Robustness**: No more crash when `$HOME` has no shell profile; PowerShell PATH updates report failure honestly via a success sentinel; timeouts on all pip/PowerShell calls.

### Changed
- **Prompt Stat Cap**: The `--stat` summary sent to the LLM is capped at 50 lines, mirroring the existing diff truncation.
- **CI Supply Chain**: Pinned GitHub Actions bumped to current majors (checkout v6, setup-python v6.3.0, upload/download-artifact v5, attest-build-provenance v3) with a new Dependabot config; `pip-audit` now also scans the installed toolchain in environment mode; mypy and Bandit cover `install.py`.

## [1.1.1] - 2026-09-04

### Fixed
- **Preflight Conflict Guard**: Halt commit operations immediately if unresolved merge/rebase conflicts or active merge heads exist, preventing `git add .` from staging conflict markers (`<<<<<<< HEAD`).
- **Windows External Editor Paths**: Preserve backslashes in custom editor paths on Windows, and respect Git standard editor precedence (`$GIT_EDITOR` -> `git config core.editor` -> `$VISUAL` -> `$EDITOR`).
- **Non-ASCII Path Handling**: Decode Git porcelain C-style octal escape sequences (e.g. `\303\251` -> `é`) ensuring non-ASCII files stage and commit cleanly.
- **Diff UTF-8 Boundary Truncation**: Backtrack across incomplete trailing multi-byte UTF-8 codepoints during diff byte-capping, avoiding truncated Unicode characters.
- **Virtualenv & Shell Detection in Installer**: Detect active virtualenvs in `install.py` to target virtual environment script paths directly, prioritize `~/.zshrc` when zsh is the user shell, and recommend non-truncating PowerShell environment commands on Windows.
- **AI Gateway Error Diagnostics**: Extract structured JSON error payloads (e.g. quota limits, invalid tokens) from AI provider HTTP gateways to display actionable diagnostics instead of generic HTTP status lines.
- **Headless E2E Test Suite**: Configured offline fallback provider in the end-to-end test suite to ensure robust verification in headless CI environments.

## [1.1.0] - 2026-09-04

### Added
- **Direct Commit Flag (`-m` / `--message`)**: Pass commit messages directly via CLI, skipping AI generation while maintaining all preflight, staging, hook, and push workflows.
- **External Editor for Manual Input**: Interactive manual input and AI fallback now open `$VISUAL` / `$EDITOR` if configured, supporting multi-line subjects and bodies.
- **Context-Aware AI Scopes**: Injected recent commit history (`git log -n 10`) into AI generation prompts so proposed scopes align with repository conventions.
- **Dynamic Retry Exploration**: Retrying AI proposal generation (`r`) now alters temperature and prompts to explore alternative phrasing and scopes.
- **Repository-Local Configuration (`.relay.toml`)**: Safe loading of repository-root `.relay.toml` for project-specific rules, with strict exclusion of secrets and host URLs.
- **Self-Hosted GitHub Enterprise Support**: Added `RELAY_TRUSTED_GITHUB_HOSTS` environment variable to securely allow Pull Request creation against internal enterprise instances.
- **Active Authentication Probing (`relay doctor --probe`)**: Active health checks validating credentials against configured AI providers and forge APIs with response latency reporting.

## [1.0.2] - 2026-09-03

### Security
- Hardened against Git option injection across all remaining dynamic invocations: guarded `remote` in `fetch` and `remote_has_branch`, and guarded `key`/`name` in `config_get` and `remote_url`.

### Fixed
- Fixed error mapping in `OllamaProvider`: HTTP 429 now correctly maps to `rate_limited` (triggering transient retry) and 5xx to `unavailable`, aligning with all other providers.
- Added structured error response payload checking (`"error" in data`) in `GeminiProvider` for consistent error handling across providers.
- Fixed team branch name truncation on nested branches (`feat/frontend/login` no longer truncated to `login`).
- Fixed Conventional Commit regex to accept valid single-character subjects (e.g. `feat: a`).
- Updated Scoop manifest hash to match actual release artifacts and added CI validation in `release.yml` and `test_version.py` preventing releases with dummy zero hashes.

### Reliability & Improvements
- Added randomized jitter (`random.uniform(0.1, 0.5)`) to exponential/linear retry backoff sleeps across `orchestrator.py` and forge clients (`github.py`, `gitlab.py`, `bitbucket.py`) to prevent thundering herd during rate limits.
- Optimized orchestrator team branch resolution by reusing the already-queried branch name, eliminating a redundant Git subprocess spawn on Windows (~28 ms saved).

## [1.0.1] - 2026-09-02

### Security & Supply Chain (DevSecOps)
- Eliminated third-party GitHub Action `softprops/action-gh-release` in favor of native, zero-dependency `gh release create` CLI in the token-privileged release workflow (NIST SP 800-218 PW.4).
- Isolated wheel smoke testing into a standalone temporary virtualenv outside the source tree to eliminate local directory package shadowing.
- Added cryptographic `SHA256SUMS` generation for all release artifacts alongside CycloneDX SBOM before SLSA provenance attestation.
- Added Bandit SAST security scanning with SARIF report upload to GitHub Advanced Security.
- Enforced cross-platform POSIX bash shell defaults across all runner environments (Linux, macOS, and Windows).

### Performance & CI Optimization
- Optimized CI test matrix from 9 permutations to 5 high-impact configurations (Python 3.10-3.12 on Ubuntu + Python 3.12 on macOS and Windows), reducing runner queue time and pipeline compute by ~44%.
- Added documentation path ignore rules (`docs/**`, `**.md`, `.gitignore`, `LICENSE`) to prevent unnecessary CI execution on documentation-only commits.
- Configured non-destructive concurrency to prevent in-flight CI cancellation on the `main` branch while maintaining fast cancellation on PRs.

## [1.0.0] - 2026-09-01

### General Availability (GA) Release
Relay 1.0.0 marks the official **General Availability (GA)** release. All core workflows, CLI interfaces, configuration formats, and AI/forge integrations are finalized, production-hardened, and declared stable under Semantic Versioning.

### Highlights
- **Zero Runtime Dependencies**: 100% Python standard library architecture with no external package requirements at runtime.
- **Workflow Automation**: Full support for Solo mode (commit & push) and Team mode (dynamic feature branching) with human-in-the-loop manual input fallback that never strands the developer.
- **AI & Local Provider Ecosystem**: Native integration with Gemini, OpenAI, Anthropic, Ollama, Groq, Mistral, xAI, and custom OpenAI-compatible endpoints with transient backoff retries.
- **Forge REST Integrations**: Zero-dependency Pull Request / Merge Request creation for GitHub, GitLab (`gitlab.com` + self-hosted), and Bitbucket Cloud.
- **CLI Stability Guarantee (ADR-012)**: Frozen CLI surface across 9 subcommands (`amend`, `completions`, `doctor`, `man`, `pr`, `squash`, `stage`, `telemetry`, `undo`) and 14 global flags with backward compatibility guarantees.
- **Security & Integrity**: Strict AST-verified security protections (`_ENV_ONLY` secrets, `shell=False` subprocess execution, SSRF-guarded URLs, and ANSI terminal sanitization).
- **Sub-500 ms Performance**: Validated latency under 50 ms CLI overhead for preflight, configuration caching, and orchestrator dispatch.
- **Test & Coverage Rigor**: 931 hermetic unit and regression tests with ~96% branch coverage across Linux, macOS, and Windows.

## [0.9.1] - 2026-09-01

### Fixed
- **AI diff splitting**: Anchored diff header splitting regex to start-of-line (`(?m)^diff --git `) in `filter_ignored_diff` and `split_diff_by_file`, preventing data leakage and phantom hunks when files contain embedded `diff --git ` strings.
- **Team rollback on Ctrl+C**: Handled `KeyboardInterrupt` during `git commit` in team mode to safely delete empty orphan branches and restore original checkout.
- **Multi-repo CLI merging**: Appended and deduplicated CLI `--repo` arguments with configured `[repos]` instead of completely overwriting.
- **Multi-repo error isolation**: Isolated `RelayError` per repository in multi-repo runs so an error in one repo does not abort processing of subsequent repositories.
- **Terminal sanitization**: Wrapped all raw `AIError` exception prints with `sanitize_terminal` in `orchestrator.py` to prevent ANSI escape sequence injection.
- **Squash rollback reporting**: Accurately reported HEAD restoration status in `relay squash` error handling, distinguishing between successful rollback and failed reset.
- **PR AI title derivation**: Used actual commit range diff (`origin/{base}..{head}`) instead of uncommitted staged diff when generating PR titles with AI fallback.
- **Forge transient retry**: Added retry loop with exponential backoff for transient HTTP 429 and 5xx errors across GitHub, GitLab, and Bitbucket clients.
- **Git argv safety**: Added `--` argument separator to `diff_range`, `stat_range`, and `log_between` in `GitManager`.

## [0.9.0] - 2026-09-01

### Added
- CLI surface freeze contract (ADR-012) and automated test (`tests/test_cli.py:test_cli_surface_is_frozen`) locking all 9 subcommands and 14 global flags.
- Hermetic performance timing harness (`tests/test_performance.py`) continuously validating NFR-1 sub-500 ms overhead (<50 ms measured).
- Security audit static AST gate (`tests/test_security_audit.py`) validating NFR-3: secrets strictly in `_ENV_ONLY`, subprocess `shell=False` policy, and endpoint SSRF/HTTPS protections.
- Added `--hunks` and `--repo` shell completion support across Bash, Zsh, Fish, and PowerShell (`relay/completions.py`).
- Added manual page documentation for all AI providers and new CLI flags in `relay man`.

### Changed
- Elevated test suite to 923 passed tests with ~96% branch coverage in CI.
- Updated release pipeline to run pinned security scanners (`pip-audit`, `bandit`, `cyclonedx-bom`) and attest build provenance via Sigstore.

## [0.8.0] - 2026-08-30

### Added
- AI diff ignore paths — `[relay.ignore] paths = [...]` and `RELAY_IGNORE_PATHS` keep generated files out of the AI prompt without hiding them from git.
- Custom hooks — `[hooks.pre_commit]` and `[hooks.post_push]` TOML tables run via `subprocess.run(..., shell=False)` with argv-as-list and 60s timeout; pre-commit aborts on failure, post-push is best-effort.
- Multi-repo runs — `relay --repo <path>` (repeatable) plus `[repos]` / `RELAY_REPOS` config list operate across worktrees/submodules in one invocation.
- Hunk-level AI messages — `relay --hunks` splits staged diff by file and generates per-file AI subjects, combined into a multi-part Conventional Commit body.

## [0.7.4] - 2026-08-29

### Fixed
- Use `git switch -c -- <branch>` for team branch creation to correctly guard branch names starting with dash (P2-1).
- Halve transient AI retry delay (6s → 3s) to reduce UI freeze (P2-2).
- Allow `edit` in `relay squash` confirmation to prompt for a new message instead of aborting (P2-3).
- Fix `relay doctor` Ollama probe for bracketed IPv6 literals via `urllib.parse` (P3-1).
- Reject percent-encoded path traversal (`%2e`, `%2E`) in remote URL parsing (P3-2).
- Restrict `http://` for AI base URLs to exact `localhost`/loopback only, wild-card `*.localhost` now requires `https` (P3-3).
- Fix empty-repo `head_diff`/`head_stat` concatenation to separate staged+unstaged with newline (P4-1).
- Robustly extract commit message from fenced code blocks with trailing text (P4-2).
- Normalize Windows PATH duplicate check for trailing backslashes (P4-3).
- Skip binary-only `git diff --numstat` check unless diff contains `Binary files` marker — saves ~100 ms in text-only repos (P5-1).
- Optimize `truncate_diff` with ascii fast-path and cached line count (P5-2).

## [0.7.3] - 2026-08-28

### Security
- Pin CI workflow actions (`actions/checkout`, `actions/setup-python`) to commit SHAs (H1).
- Enforce `https://` for public AI base URLs — `http://` only allowed for `localhost`/loopback (Ollama, local llama.cpp) — to prevent cleartext API-key exfiltration (H2).
- Harden remaining Git rev parsing (`merge-base --is-ancestor --`) with `--` separator (M1).
- Sanitize `--verbose` and unexpected-error output for ANSI/log injection (M2).
- Escape PowerShell/POSIX paths in `install.py` to prevent quote injection via username (M3).
- Escape Bitbucket `q` query and sanitize `relay stage` filenames for ANSI (M4).

## [0.7.2] - 2026-08-28

### Security
- Prevent Git option injection via branch/ref names in `git push`/`fetch`/`checkout`/`branch -D`/`ls-remote` by inserting `--` separator and using `git switch --` (HIGH-1).
- Make AI base URLs (`OLLAMA_BASE_URL`, `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, `MISTRAL_BASE_URL`, `GROQ_BASE_URL`, `XAI_BASE_URL`) env-only so a repo-local `RELAY_CONFIG` cannot redirect credential-bearing requests (HIGH-2).
- Enforce GitLab trusted-host allowlist as env-only (`RELAY_TRUSTED_GITLAB_HOSTS`) — config-file `trusted_gitlab_hosts` is now ignored to prevent credential exfiltration (MEDIUM-7).
- Validate `relay pr --base` and reject option-like values (`--upload-pack`, `..`) before `git fetch` (MEDIUM-6).
- Sanitize ANSI/control sequences from remote error text before terminal output to prevent log injection (LOW-11).
- Telemetry redirects now validate each destination is public `https://` (LOW-10).

### Fixed
- `relay --dry-run` no longer mutates the index (`git add .`) — previews via `git diff HEAD` (MEDIUM-4).
- Add TOCTOU guard: capture `git write-tree` before AI and verify index unchanged before commit (MEDIUM-5).
- Add byte budget (`512 KiB`) to diff truncation alongside line cap to handle huge single lines (MEDIUM-8).
- Wire configured `branch_template` (`RELAY_BRANCH_TEMPLATE` / `[relay] branch_template`) into `Orchestrator` — `release/<feature>` now works (MEDIUM-9).
- Pin release workflow actions to commit SHAs and scope `contents: write` to job (HIGH-3).
- Clean `dist/` before `python -m build` to avoid stale artifacts in releases (LOW-12).

## [0.7.1] - 2026-08-26

### Security
- Validate URL scheme (`http`/`https` only) before `webbrowser.open()` in `relay pr`, rejecting `file://` or protocol-handler URIs (S1).
- Reject path traversal (`.` / `..`) in `parse_remote()` and URL-encode `owner` and `repo` path segments in GitHub and Bitbucket API URLs (S2).
- URL-encode model name in Google Generative Language (Gemini) REST API endpoint path (S3).
- Added security note in `README.md` against pointing `RELAY_CONFIG` to untrusted repositories (S4).

### Fixed
- Catch `ConfigError` in `relay amend` dispatch to fall back gracefully to manual input when no AI API key is configured (Bug 1).
- Use `Draft: ` title prefix for GitLab draft merge requests instead of non-standard body parameter (Bug 2).
- Guard `find_open_pr()` in `GitHubClient` against non-list JSON responses (Bug 3).
- Propagate exit code from `git add -p` in `relay stage --patch` (Bug 4).
- Correctly extract destination path for rename entries (`old -> new`) and unquote paths in `git status --porcelain` (Bug 5).
- Use case-insensitive matching for protected branch check in `relay doctor` (Bug 6).
- Explicitly catch `EOFError` in `cli.py` to give actionable guidance in non-interactive / CI environments (Bug 7).
- Support `COMSPEC`/`ComSpec` in Windows shell detection, omit misleading `--count 1` hint in squash error, and decouple user confirmation retry counter from transient AI retry backoff (Bug 8).

## [0.7.0] - 2026-08-21

### Added
- Mistral, Groq, and xAI providers — each a drop-in `relay/ai/` subclass
  of the OpenAI-compatible provider (`MISTRAL_API_KEY`, `GROQ_API_KEY`,
  `XAI_API_KEY`; overridable `*_MODEL` / `*_BASE_URL`; registered in
  `_PROVIDERS`).
- Bitbucket Cloud pull-request client for `relay pr` (`BITBUCKET_TOKEN` as
  `username:app_password`; routing in `relay/pr.py`, client in
  `relay/bitbucket.py`).
- Per-mode provider default in config (`[ai] default = "ollama"` in
  `config.toml`, lower precedence than `RELAY_AI_PROVIDER` and
  `[relay] provider`).
- Provider matrix documentation (keys, base URLs, compat notes) in
  `README.md` and `docs/ARCHITECTURE.md`.

### Security
- `relay pr` now enforces a GitLab trust boundary. The host is derived from
  the `origin` remote — attacker-controllable data — so `GITLAB_TOKEN` is
  only ever sent to `gitlab.com` unless a self-hosted host is explicitly
  allowed via `RELAY_TRUSTED_GITLAB_HOSTS` (env) or `trusted_gitlab_hosts`
  (the `[relay]` config table). Untrusted hosts are refused before any token
  is read or any request is made (credential-exfiltration hardening).
- `RELAY_TELEMETRY_URL` now rejects loopback/private/link-local endpoints
  (`localhost`, `127.0.0.1`, `10.x`, `192.168.x`, `[::1]`, IPv4-mapped
  addresses, ...), so a misconfigured operator URL can never point telemetry
  at a local/private host even over HTTPS.
- Successful GitHub/GitLab API responses are capped at 1 MiB (error bodies
  were already capped at 10 KiB), so a misbehaving forge endpoint can no
  longer make Relay hold a giant blob in memory.

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

[Unreleased]: https://github.com/Fiqqar/Relay/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Fiqqar/Relay/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/Fiqqar/Relay/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Fiqqar/Relay/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Fiqqar/Relay/compare/v0.9.1...v1.0.0
[0.9.1]: https://github.com/Fiqqar/Relay/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/Fiqqar/Relay/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Fiqqar/Relay/compare/v0.7.4...v0.8.0
[0.7.4]: https://github.com/Fiqqar/Relay/compare/v0.7.3...v0.7.4
[0.7.3]: https://github.com/Fiqqar/Relay/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/Fiqqar/Relay/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/Fiqqar/Relay/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/Fiqqar/Relay/compare/v0.6.0...v0.7.0
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
