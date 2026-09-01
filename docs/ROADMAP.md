# Relay Roadmap

Ordered plan from the current release to **v1.0.0 (GA)**. Versions `0.1.0`
through `0.9.0` are shipped and closed; `1.0.0` is planned.

## Legend

- `[x]` done · `[ ]` planned · `[~]` in progress
- **Exit criteria** = the definition of done that gates the next version.

---

## Shipped history (`0.1.0` → `0.9.0`)

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

### v0.5.0 — Team default-branch safety

- [x] `relay team` mode refuses to commit to a configured protected branch
      by default (origin of the `team` naming; keeps solo-convention commits)
- [x] Default-branch rules in TOML config (`[team.protected] branches = ["main"]`,
      or the `RELAY_PROTECTED_BRANCHES` env var)
- [x] Opt-out escape hatch (`--allow-protected` flag) for force paths — the
      `--yes` flag only skips the confirmation prompt and never bypasses the
      safety guard (decoupled in 0.5.1)
- [x] `relay doctor` reports protected-branch config + warns on risky state
- [x] Unit tests for each safety rule (`tests/test_protected.py`,
      mirroring `tests/test_doctor.py` patterns)

**Exit:** pushing to a protected branch is impossible by default on the
configured rules; tests cover every rule. ✅

### v0.5.1 — Patch (safety + packaging fixes)

- [x] **`--yes` decoupled from protected-branch safety** — `--yes` now only
      skips the confirmation prompt; it never bypasses the default-branch
      guard. Opting out requires the explicit `--allow-protected` flag, so a
      scripted/CI run can no longer silently land on `main`/`master`.
- [x] **`max_diff_lines` tolerant parsing** — a wrong-typed config entry
      (`max_diff_lines = [1, 2]` or `= true`) now falls back to the default
      instead of raising an uncaught `TypeError` (or silently capping the diff
      at one line for booleans), matching `ai_timeout()`.
- [x] **Feature-name prompt isolated** — the only `input()` in team branch
      resolution lives in `_prompt_feature_name()`, a single seam for a future
      `--no-input`/CI mode.
- [x] Homebrew formula + Scoop manifest re-pointed at `v0.5.0` assets
      (both had been left on `v0.4.1` when 0.5.0 shipped, so `brew install`
      and `scoop install` were still pulling the previous patch), then re-pointed
      at `v0.5.1` assets after this release
- [x] `RELEASE.md` step 1b now requires re-pointing the formula + manifest, so
      a release can never silently ship stale package channels

**Exit:** `brew install Fiqqar/relay/relay` and `scoop install relay` install
the shipped version; the runbook step prevents recurrence. ✅

### v0.5.2 — Patch (squash diff fix)

- [x] **`relay squash` fed the AI the wrong diff** — it used `staged_diff()` /
      `staged_stat()` (the current index) to generate the AI message, but
      `reset --soft` runs after message resolution, so the index held unrelated
      (or empty) working-tree changes. The AI message could describe the wrong
      thing while `log_between(base, tip)` above it already knew the correct
      range. Now `GitManager.diff_range(base, tip)` / `stat_range(base, tip)`
      (`git diff base..tip`) feed the combined diff of the squashed commits.
- [x] Regression tests: `FakeGit` now records `diff_range`/`stat_range` calls
      and asserts squash never touches the staging area (previously the
      hardcoded `staged_diff()` return silently hid this bug).

**Exit:** `relay squash --provider <ai>` sends the base..tip diff; unit tests
would fail if it ever regressed to reading the index. ✅

### v0.5.3 — Patch (fish completion fix)

- [x] **fish completion dropped 3 subcommands** — `fish_script()` was
      hand-written line-by-line and advertised only 6 of the 9 subcommands,
      silently missing `stage`, `man`, and `telemetry` (added in v0.4). The
      module docstring claims completions "always match the installed binary's
      actual subcommands" — that was only true for bash/zsh/powershell.
- [x] Fish now generates its subcommand lines in a loop from the `SUBCOMMANDS`
      source of truth (with a per-subcommand description map), like the other
      three generators.
- [x] Test tightened: every shell must advertise **every** item in
      `SUBCOMMANDS` (was: only checking `"doctor" in out`), so a future
      subcommand can never be forgotten again.

**Exit:** `relay completions fish` advertises all 9 subcommands; the suite
fails if any shell drops one. ✅

### v0.5.4 — Patch (full-codebase audit fixes)

- [x] **`relay squash` aborted when the AI failed** — `_message_from_ai`
      printed "keeping the original commit message" but then raised
      `UserAbort`, killing the whole fold whenever the provider was offline,
      rate-limited, or returned an unusable response. It now falls back to the
      top commit's subject so a non-destructive local operation degrades like
      the rest of the tool.
- [x] **`relay squash --message` failed without an API key** — the CLI built
      the provider unconditionally, so `--message` (which never consults the
      AI) died with a `ConfigError` on machines without `GEMINI_API_KEY`, and
      a plain squash couldn't fall back either. The provider is now built
      lazily and a missing key means "no provider" → fallback path runs.
- [x] **TOML parser mis-handled escaped quotes** — `_strip_comment`,
      `_split_kv` and `_split_items` each mis-parsed strings whose closing
      quote was preceded by backslashes (a value ending in `\\` swallowed the
      trailing `# comment`; an escaped `\"` leaked a top-level `=` through the
      key/value split). All three now close a string only when an even run of
      backslashes precedes the quote.
- [x] **Dead `SUBCOMMAND_FLAGS` map removed** from `completions.py` — it was
      documented as the source of truth for per-subcommand flags but no
      generator ever read it.
- [x] **Test suite made hermetic** — `build_prompt` tests no longer read
      `RELAY_MAX_DIFF_LINES` from the environment, the doctor Ollama probe and
      telemetry bad-URL thread are no longer real I/O, config env mutations
      use `monkeypatch`, and the previously dead `api_error` HTTP/retry
      branches are now covered. Fixture/assertion hygiene: `sample_diff` hunk
      counts corrected, `FakeGit` attribute name aligned, `--solo` asserted
      positively.

**Exit:** AI-failure paths never abort a squash; parser edge cases tested;
suite green (525 tests) with no environment-dependent tests. ✅

### v0.5.5 — Patch (project hygiene + CI hardening)

- [x] **Project governance files** — `LICENSE` (MIT, matching the declared
      license), `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and
      `CHANGELOG.md` (Keep a Changelog, dates verified against `git log`).
- [x] **CI coverage gate** — `pytest --cov` with an 85% branch-coverage floor
      (`[tool.coverage]` in `pyproject.toml`, `pytest-cov` added to dev extras).
- [x] **Static analysis + type checking in CI** — `ruff check .` and
      `mypy relay` run on every commit (`ruff`/`mypy` added to dev extras).
- [x] **Type-safety + lint fixes** — mypy/ruff flagged real bugs: a possible
      `None` `api_key` dereference in the Gemini/Anthropic providers, a
      mistyped GitLab MR payload, an unused variable, and a duplicated test;
      all fixed with the suite still green (525 tests).
- [x] **E2E in CI** — `e2e_test.sh` (Linux) and `e2e_test.ps1` (Windows) run on
      every commit; the scripts were also fixed (manual-input stdin now
      terminates with a blank line instead of crashing on EOF).

**Exit:** repo ships full governance docs; CI enforces coverage, lint, types,
and the e2e fallback flow on all platforms. ✅

### v0.5.6 — Patch (squash/undo robustness + working rules)

- [x] **`relay squash` refuses a dirty index** — anything pre-staged before the
      fold used to leak into the new commit (`reset --soft` keeps the index);
      squash now fails up front with `git reset -- <path>` in the message.
- [x] **`relay squash --count N` folds the whole history** — when `N` equals
      the total commit count, `HEAD~N` used to point past the root commit and
      fail with "not enough history"; the whole branch now folds into a single
      root-amended commit.
- [x] **`relay undo` on a single-commit repo** — now a clear, actionable error
      instead of leaking git's raw `fatal: unknown revision`.
- [x] **`docs/WORKING_RULES.md`** — the mandatory rules document for humans and
      AI agents; `AGENTS.md` and `CONTRIBUTING.md` point to it.

**Exit:** dirty-index squash and single-commit undo give actionable errors; the
working rules are the documented gate for all contributors. ✅

### v0.5.7 — Patch (post-release audit fixes)

- [x] **Team orphan-branch rollback** — on commit failure after the feature
      branch was created, Relay checks out the original branch and deletes the
      empty orphan instead of stranding the user (C-05).
- [x] **Squash HEAD restore** — if the fold commit fails, HEAD is soft-reset
      back to the original tip so nothing is lost mid-reset (C-04).
- [x] **Network git timeout** — `push`/`fetch`/`ls-remote` now time out after
      60s instead of hanging forever on an unreachable remote (C-06).
- [x] **AI response cap** — all four providers reject bodies over 1 MiB as
      `bad_response` instead of parsing them (H-02).
- [x] **Manual-input fallback hardening** — a missing API key (H-14), a
      binary-only staged diff (H-12), and a detached HEAD (H-13) all degrade
      to safe manual/skipped paths instead of aborting or pushing an empty ref.
- [x] **Config parsing fixes** — parsed once per file state (H-08), malformed
      files warn once (L-15), invalid env values warn (M-11), `max_diff_lines`
      clamps to a positive floor (M-02).
- [x] **Case-insensitive protected branches** — `Main` can no longer bypass a
      rule written for `main` (M-14); team mode on a protected branch prompts
      for a real feature name (L-10).
- [x] **Telemetry https-only** — non-HTTPS `RELAY_TELEMETRY_URL` is rejected
      with a warning (C-02); forge HTTP error bodies are read with a 10 KiB cap.
- [x] **Docs hygiene** — `BUG.md` dropped (all triaged issues resolved),
      `WORKING_RULES.md` + `AGENTS.md` translated to English.
- [x] **Test suite expanded to 638 tests (~96% branch coverage)** covering the
      fallback/error paths above.

**Exit:** every post-0.5.6 triaged issue is fixed and covered; suite green at
96% branch coverage with no environment-dependent tests. ✅

### v0.5.8 — Patch (cross-platform decode crash)

- [x] **Subprocess decode crash** — `git` output containing bytes the locale
      codec (cp1252 on Windows) cannot decode used to kill subprocess's reader
      thread, leaving `stdout`/`stderr` as `None` and crashing `relay --solo`
      with `'NoneType' object has no attribute 'strip'` (e.g. Unity repos with
      binary-ish diffs). Git output is now decoded as UTF-8 with
      `errors="replace"`, so stdout is always a `str` (C-17).

**Exit:** `relay` runs end-to-end in repos whose diffs hold non-cp1252 bytes;
the decode path is pinned by unit tests and the Windows e2e flow is green. ✅

### v0.6.0 — Distribution polish

- [x] Publish a Homebrew **tap repo** (`homebrew-Relay`) so `brew tap Fiqqar/relay` works
- [x] Scoop manifest `bucket/relay.json` with `checkver`/`autoupdate` verified
- [x] Docs: single-line install instructions per platform

**Exit:** `scoop install relay` and `brew tap Fiqqar/relay` work on a fresh machine. ✅

### v0.7.0 — Provider & forge breadth

- [x] Additional providers (Mistral, Groq, xAI): one class in `relay/ai/` + registration in `_PROVIDERS`
- [x] Bitbucket client for `relay pr` (new client + routing in `pr.py`)
- [x] Per-mode provider default in config (`[ai] default = "ollama"`)
- [x] Provider matrix doc (keys, base URLs, compat notes) in README/ARCHITECTURE

**Exit:** ≥ 6 providers + 2 forges covered; a new provider is a drop-in class + test. ✅

### v0.7.1 — Security hardening

- [x] Validate URL scheme before `webbrowser.open()` in `relay pr`
- [x] Reject path traversal in `parse_remote()` and URL-encode path segments
- [x] URL-encode model name in Gemini endpoint
- [x] Security note against untrusted `RELAY_CONFIG`

**Exit:** URL/remote handling hardened; security docs updated. ✅

### v0.7.2 — Security & correctness audit fixes

- [x] Git option injection hardening (`--` separator, `git switch --`)
- [x] AI base URLs and GitLab trusted hosts env-only
- [x] `relay --dry-run` side-effect free via `git diff HEAD`
- [x] TOCTOU guard via `git write-tree`
- [x] `relay pr --base` validation and `fetch --` separator
- [x] Byte-budget diff truncation (`512 KiB`)
- [x] Wire `branch_template` into CLI
- [x] Telemetry redirect SSRF validation
- [x] ANSI/control-sequence sanitization
- [x] Release workflow SHA-pinned and `dist/` cleaned

**Exit:** 13 audit findings fixed, tests 793 green, coverage 94%. ✅

### v0.7.3 — Supply-chain & SSRF hardening

- [x] Pin `ci.yml` actions to SHA (`checkout`/`setup-python`)
- [x] Enforce `https` for public AI base URLs (allow `http` only for `localhost`)
- [x] Harden remaining `merge-base --is-ancestor --` with `--`
- [x] Sanitize `cli.py` verbose/unexpected error output
- [x] Escape `install.py` PowerShell/POSIX paths
- [x] Harden Bitbucket `q` escaping and `stage` filename sanitization

**Exit:** 6 fresh findings fixed, no regressions. ✅

### v0.7.4 — Audit fixes (P2-P5)

- [x] `git switch -c -- <branch>` for team branch creation (P2-1)
- [x] Halve transient retry delay 6s → 3s (P2-2)
- [x] `relay squash` edit now prompts for new message (P2-3)
- [x] `relay doctor` IPv6 bracketed host handling (P3-1)
- [x] Percent-encoded traversal rejection in `parse_remote` (P3-2)
- [x] Restrict `http` to exact `localhost`/loopback for AI base URLs (P3-3)
- [x] Empty-repo `head_diff` newline separation (P4-1)
- [x] Robust fence extraction in `sanitize_ai_message` (P4-2)
- [x] Normalize Windows PATH duplicate check (P4-3)
- [x] Skip binary `numstat` probe unless `Binary files` in diff (P5-1)
- [x] `truncate_diff` ascii fast-path + cached count (P5-2)

**Exit:** 11 findings fixed across P2-P5, 793 tests green, coverage 92%. ✅

### v0.8.0 — Core workflow depth

- [x] **Hunk-level AI messages** — `relay --hunks` splits staged diff by file and
      generates per-file AI subjects, combined into a multi-part Conventional
      Commit body
- [x] **Multi-repo runs** — `relay --repo <path>` (repeatable) plus `[repos]`
      / `RELAY_REPOS` config list operate across worktrees/submodules in one
      invocation
- [x] **Custom hooks** — `[hooks.pre_commit]` and `[hooks.post_push]` TOML
      tables run via `subprocess.run(..., shell=False)` with argv-as-list and
      60s timeout
- [x] **AI diff ignore paths** — `[relay.ignore] paths = [...]` (or
      `RELAY_IGNORE_PATHS`) keeps generated files out of the AI prompt without
      hiding them from git

**Exit:** `relay --hunks` produces multi-part AI messages end-to-end; multi-repo
and hooks run with unit tests; ignore paths keep lockfiles/generated code out
of the prompt. ✅

### v0.9.0 — GA hardening

- [x] Freeze the CLI surface (subcommands/flags) — ADR-012 and automated freeze test
- [x] NFR-7 audit complete: every failure message carries an actionable next step (the `tests/test_error_audit.py` gate)
- [x] Coverage gate ≥ 90% branch in CI (enforced with ~96% coverage)
- [x] Security review & AST gate: secrets env-only, no `shell=True`, HTTPS SSRF validation (NFR-3)
- [x] Performance pass (NFR-1): automated timing harness verifying <50 ms CLI overhead

**Exit:** CI-green on 3 OS × 3 Python; coverage gate ≥ 90%; error-message and security audit verified. ✅

---

## Planned (`1.0.0`)

### v1.0.0 — GA

- [ ] Mark all `M` milestones (M0–M3) as **stable**, no loose ends
- [ ] Public docs: README/ARCHITECTURE/FLOW + roadmap point to the stable API
- [ ] Cut `v1.0.0` per `RELEASE.md`; artifacts verified on all channels
- [ ] Deprecation policy documented (semver commits)

**Exit:** `v1.0.0` released; Homebrew + Scoop point at it; README says stable.

---

## Non-goals (explicitly out of scope)

- GUI/TUI — Relay is a CLI; interactive selection stays in the terminal
- Remote model hosting — providers are BYO-key / BYO-endpoint
- CI/CD pipeline integration (beyond git push) — hooks/forges remain user-managed
- Multi-user server fleet — single-user desktop tool