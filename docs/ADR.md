# Relay — Architecture Decision Records (ADR)

> Why Relay is built this way. Each ADR: Context → Decision → Consequences.
> Numbers are permanent — never delete; if a decision changes, add a new ADR that supersedes it.

---

## ADR-001 — Pure-stdlib, zero runtime dependencies

**Context:** Global CLI must install anywhere, including offline machines / labs with unstable internet. Heavy deps (`requests`, `typer`, `pydantic`) increase supply-chain risk and break offline.

**Decision:** Stdlib only: `argparse`, `subprocess`, `urllib`, `tomllib`/`relay/toml.py`, `unittest.mock` for tests. `pyproject.toml:dependencies = []`.

**Consequences:** + Install always succeeds, small audit surface. − Must write a tiny TOML parser & manual HTTP; no fancy framework features.

## ADR-002 — Git via subprocess (argv-as-list) bukan library

**Context:** Alternative: `GitPython` / `dulwich`. They reimplement credential helpers & hook handling.

**Decision:** `subprocess.run(["git", ...], shell=False)` — reuse the user's credential helpers, SSH agent, and hooks as-is. All args as a list; `shell=True` forbidden (enforced in `WORKING_RULES.md`).

**Consequences:** + Compatible with any git setup; anti shell-injection. − Must handle `FileNotFoundError` when git is not on PATH (`relay/doctor.py`, `relay/git_manager.py`).

## ADR-003 — AI behind `AIManager` interface + provider registry

**Context:** Need Gemini default, local Ollama, plus OpenAI-compatible providers. Avoid scattered `if provider ==` branches.

**Decision:** `relay/ai/base.py` abstract `generate_commit_message(diff, stat, branch) -> str` + `build_prompt`. Registry `_PROVIDERS` in `relay/ai/__init__.py`. New provider = subclass `OpenAIProvider` + register + tests + doctor check. See `CONTRIBUTING.md#adding-an-ai-provider`.

**Consequences:** + Add provider without touching orchestrator. − Must keep `AIError(kind, provider)` contract consistent.

## ADR-004 — Manual fallback, never block workflow

**Context:** FR-7: AI down/rate-limited/offline must not abort. Many AI tools fail hard — bad for low-connectivity.

**Decision:** Every `AIError` / invalid Conventional Commit → `FALLBACK` → manual `input()` (subject + optional body, blank line to finish). Lazy provider build: missing API key → `provider=None` → fallback, not a hard `ConfigError`. Non-TTY → exit 1 without hanging.

**Consequences:** + Workflow always continues. − Manual message is not validated (verbatim commit).

## ADR-005 — Precedence: flags > env > config file > defaults; secrets env-only

**Context:** Config file is convenient, but secrets in a file leak when the repo is shared. `RELAY_CONFIG` can be pointed at an untrusted repo.

**Decision:** `relay/config.py:_resolve` — env wins over file. Secrets (`*_API_KEY`, `*_TOKEN`) + AI base URLs + GitLab trusted hosts are **env-only**; file values for those keys are ignored. Config file cached per `(path, mtime, size)`.

**Consequences:** + File can be shared without leak risk; malicious repo cannot redirect tokens. − User must set secrets via env (documented in `relay doctor`).

## ADR-006 — Protected-branch guard default-deny

**Context:** Team mode `relay --team` is often run from `main` — risk of committing directly to the default branch.

**Decision:** `RELAY_PROTECTED_BRANCHES` / `[team.protected] branches` default `["main","master"]` (case-insensitive). Team mode refuses when `current_branch` is protected; only `--allow-protected` bypasses. `--yes` never bypasses (decoupled in v0.5.1). Solo mode may still commit anywhere (convention).

**Consequences:** + Prevents the most costly mistake (push to main). − Requires an explicit escape hatch for repos that intentionally commit to main.

## ADR-007 — Diff truncation: line cap + byte budget

**Context:** Large diffs can exceed the LLM token window or cause OOM. Line cap alone fails for a single very long line.

**Decision:** `RELAY_MAX_DIFF_LINES` (default 120) + hard byte budget 512 KiB (`relay/orchestrator.py`). Truncation is reported to the user. `max_diff_lines` has tolerant parsing (bool/list → default).

**Consequences:** + Prompt always fits; no OOM from diffs. − AI message may lack context when truncated (user can raise the limit).

## ADR-008 — Dry-run via `git diff HEAD`, TOCTOU guard via `write-tree`

**Context:** `--dry-run` must not mutate the index. A race between the AI call and `git add .` could commit a different state.

**Decision:** Dry-run does not run `git add .`; it uses `git diff HEAD` for preview. Guard: `git write-tree` before AI, verify index unchanged before `git commit`. See `docs/FLOW.md`.

**Consequences:** + Dry-run is truly side-effect free; races are detected. − One extra subprocess per run.

## ADR-009 — Forge routing with trusted-host allowlist

**Context:** `relay pr` derives the host from the `origin` remote — data controllable by a malicious repo. Tokens could be exfiltrated to an attacker host.

**Decision:** `github.com` / `bitbucket.org` hard-trusted; `gitlab.com` default trusted + `RELAY_TRUSTED_GITLAB_HOSTS` env-only allowlist (additive, not replacing). Untrusted host → refuse before reading the token or sending the request. `https` only; `http` allowed only for `localhost` (Ollama). Validate URL scheme before `webbrowser.open`.

**Consequences:** + Token never reaches an attacker host. − Self-hosted GitLab requires an explicit env var.

## ADR-010 — Single-line `dev` array in `pyproject.toml`

**Context:** `relay/toml.py` subset parser does not support multi-line arrays. CI does not use `tomllib` on 3.10.

**Decision:** Keep `dev = ["pytest>=8", ...]` single-line. Rule in `WORKING_RULES.md` + guards in `tests/test_version.py` / `test_toml.py`.

**Consequences:** + Simple parser keeps working. − `pyproject.toml` cannot auto-wrap the array.

## ADR-011 — One logical change = one commit; dogfooding via `relay` itself

**Context:** Clean history is the guiding star. AI/agents often bundle many fixes into one commit.

**Decision:** `WORKING_RULES.md` + `AGENTS.md` require one commit per logical change + commit & push via `relay --solo/--team --yes` (split & push straight). Whole-repo `ruff format` is forbidden.

**Consequences:** + History stays bisectable, reviewable. − Requires discipline (but `relay` itself enforces it).

## ADR-012 — CLI Surface Stability & Freeze for GA

**Context:** Ahead of v1.0.0 GA, Relay must guarantee CLI interface stability. Scripted invocations, shell aliases, and team CI integrations depend on predictable flags and subcommands.

**Decision:** The CLI surface is frozen across 9 subcommands (`amend`, `completions`, `doctor`, `man`, `pr`, `squash`, `stage`, `telemetry`, `undo`) and 14 global flags (`--solo`, `--team`, `--provider`, `--timeout`, `--yes`, `--dry-run`, `--no-push`, `--staged`, `--no-verify`, `--allow-protected`, `--hunks`, `--repo`, `--verbose`, `--version`). Any removal, rename, or breaking change requires a new ADR and major version bump.

**Consequences:** + Stable automation and backward compatibility for all users. − New subcommands or flags require a formal design note.

---

## Superseded / Future

- If multi-provider failover is needed, create ADR-013 (currently out of scope).
- If a TUI is needed, create a new ADR that justifies deps — do not silently add deps.
