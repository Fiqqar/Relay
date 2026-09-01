# Relay — Product Specification (PRD)

> Source of truth for what Relay does, who it serves, and how success is measured.
> README summarises; this file specifies. If they conflict, this file wins.

---

## 1. Vision

**One command collapses the daily Git loop into a safe, reviewable, AI-assisted workflow:**

```
git add . → generate Conventional Commit → git commit → git push → open PR
```

Relay keeps the developer in control at every meaningful checkpoint and **never blocks** when the AI is down.

## 2. Personas

| Persona | Context | Core need |
|---------|---------|-----------|
| **Sana — Solo Dev** | Own repos, rarely thinks about branches | Speed + clean history without ceremony |
| **Marcus — Team Dev** | Shared repo, `main` must stay clean | Discipline: `<type>/<feature>` branches, never commit to `main` by accident |
| **Priya — Low-connectivity** | Offline / flaky network / rate-limited | Tool never blocks; manual fallback continues the workflow |

## 3. Goals & Non-Goals

### Goals (G1–G5)

- **G1.** Single command from working tree to pushed commit in solo and team workflows.
- **G2.** Generate Conventional Commits-compliant messages from the staged diff via LLM.
- **G3.** Never let AI availability block Git workflow → manual prompt fallback.
- **G4.** Developer stays in control: preview, confirm, edit, retry, abort.
- **G5.** Fast, dependency-light, cross-platform global CLI.

### Non-Goals (v1)

- No interactive hunk selection beyond `relay stage` / `git add -p`.
- No CI/CD integration, changelog generation, or commit signing flows beyond git pass-through.
- No LFS / submodules / exotic hooks handling.
- No multi-provider failover; one configured provider + manual fallback.

## 4. Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1 | `relay` primary command; default **solo**, selectable via `--solo` / `--team` | P0 | done |
| FR-2 | **Solo:** `git add .` → generate → `git commit` → `git push origin <cur>` | P0 | done |
| FR-3 | **Team:** `git add .` → generate → `git checkout -b <branch>` → `git commit` → `git push -u origin <branch>` | P0 | done |
| FR-4 | Read staged diff (`git diff --cached`) and send to configured LLM | P0 | done |
| FR-5 | Pluggable providers: Gemini (default), Ollama, OpenAI, Anthropic, Mistral, Groq, xAI | P0 | done |
| FR-6 | Parse/validate AI response as Conventional Commit `type(scope): subject` | P0 | done |
| FR-7 | On AI failure (timeout, rate-limit, offline, garbage) → **manual prompt fallback** in same terminal | P0 | done |
| FR-8 | Preflight: git repo? changes exist? remote configured? Abort early with actionable messages | P0 | done |
| FR-9 | Team branch naming via template (default `<type>/<feature>`); feature from `--team <name>` / current branch / prompt | P1 | done |
| FR-10 | Show generated message, request confirmation before commit (skippable via `--yes`) | P1 | done |
| FR-11 | `--dry-run` (plan+message, no mutations) and `--no-push` | P1 | done |
| FR-12 | Respect git pre-commit hooks; surface output, abort cleanly on failure | P1 | done |
| FR-13 | Push rejection (non-fast-forward) with actionable guidance (`pull --rebase`) | P1 | done |
| FR-14 | Truncate large diffs to provider budget (`RELAY_MAX_DIFF_LINES` + 512 KiB byte cap) | P2 | done |
| FR-15 | `--verbose` logging + `relay doctor` self-diagnostic | P2 | done |
| FR-16 | `relay pr` — create GitHub/GitLab/Bitbucket PR via REST, no deps | P1 | done |
| FR-17 | `relay undo` — soft-reset last commit (non-destructive) | P1 | done |
| FR-18 | `relay amend` — rewrite last commit message in place (never push) | P1 | done |
| FR-19 | `relay squash` — fold last N commits (local only) | P1 | done |
| FR-20 | `relay stage` — interactive file/hunk staging (`git add --` / `git add -p`) | P1 | done |

## 5. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Performance: CLI overhead (excl. LLM latency) | < 500 ms |
| NFR-2 | Portability: pure-stdlib Python | Windows / macOS / Linux, no runtime deps |
| NFR-3 | Security: secrets env-only, never logged | Audit gate `tests/test_error_audit.py` |
| NFR-4 | Reliability: no partial states; push failure reports committed state + retry cmd | — |
| NFR-5 | Observability: structured logs, exit codes 0/1/130 | — |
| NFR-6 | Testability: AI behind interface with mock; Git executor unit-testable | — |
| NFR-7 | Usability: every failure has human-readable explanation + suggested next action | — |

## 6. User Stories & Acceptance Criteria

**US-1 Solo happy path**
> As Sana, I run `relay --solo` on a dirty tree.
AC: `git add .` staged, AI message validated, confirmation shown, `git commit -F -` committed, `git push origin <branch>` succeeded, exit 0.

**US-2 Team safety**
> As Marcus, I run `relay --team payments` while on `main`.
AC: Refused by protected-branch guard unless `--allow-protected`; otherwise creates `feat/payments`, commits, pushes with `-u`, exit 0. `--yes` never bypasses guard.

**US-3 Offline fallback**
> As Priya, I run `relay --solo` with no API key / no network.
AC: Prints `AI unavailable (...) — continuing with manual input.`, prompts for subject+body, commits verbatim, pushes, exit 0. Non-TTY exits 1 without hanging.

**US-4 Dry run**
> As any dev, I run `relay --dry-run`.
AC: Resolves message + branch name, prints plan, mutates nothing (`git add .` not run, index unchanged), exit 0.

**US-5 PR creation**
> As Marcus, I run `relay pr --base main --draft --open` after pushing a feature branch.
AC: Validates base ref, creates PR via forge REST (trusted host only), prints URL, opens browser only with `--open`/`--yes`/`RELAY_PR_OPEN=1`.

## 7. Scope Boundaries (v0.9 → v1.0)

Explicitly in scope next: GA finalization, public documentation, and distribution channels — see `docs/ROADMAP.md`.
Explicitly out of scope: GUI/TUI, remote model hosting, CI/CD pipeline orchestration, multi-user server.

## 8. Success Metrics

- **Adoption:** % daily commits made through Relay within target teams.
- **Acceptance:** % AI messages committed without edits after confirmation.
- **Reliability:** % runs that complete end-to-end without manual intervention (excl. fallback).
- **Quality:** Conventional Commits compliance rate across Relay commits.

## 9. References

- `docs/FLOW.md` — state machine & edge-case matrix (implements FR-7/FR-10/FR-11).
- `docs/ARCHITECTURE.md` — component breakdown & data flow.
- `docs/WORKING_RULES.md` — contribution gate (coverage, lint, mypy, one-change-per-commit).
- `README.md#configuration` — user-facing config reference.
