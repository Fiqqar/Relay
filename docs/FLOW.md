# Relay — Logical Flow & State Machine

> This document defines the step-by-step execution for **Solo** and **Team** modes, the **AI fallback mechanism**, and all edge cases.

---

## 1. Shared Entry Point

Every run begins the same way, regardless of mode:

```
relay [--solo | --team [FEATURE]] [flags]
     │
     ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. Parse flags; resolve AI provider (--provider >            │
│    RELAY_AI_PROVIDER > default "gemini") and construct it.   │
│    A missing GEMINI_API_KEY fails here, before any action.   │
│ 2. Resolve mode: --team given → team, otherwise solo.        │
│ 3. PREFLIGHT checks (fail fast, nothing mutated yet):        │
│      a. inside a git work tree?                              │
│      b. any staged/unstaged changes? (clean tree → exit 0)   │
│      c. remote configured? (warning-only for solo)           │
│    └─ any check fails → print actionable error → exit 1      │
└──────────────────────────────────────────────────────────────┘
  (--dry-run does NOT exit early: it still resolves the message
   and team branch name, prints the plan, then exits 0 before any
   branch creation / commit / push.)
```

## 2. Solo Mode

**Goal:** working tree → committed & pushed on the **current** branch.

```
SOLO
  │
  ├─ STAGE        git add .
  │
  ├─ COLLECT_DIFF git diff --cached --stat   (summary, for the UI)
  │               git diff --cached          (full diff → prompt)
  │               └─ truncate to token budget if too large (FR-14)
  │
  ├─ GENERATE     send {diff, stat, branch, model} to AIService
  │               ├─ OK        → validate → Conventional Commit message
  │               └─ FAIL      → FALLBACK ──────────────┐
  │                                                     │
  ├─ CONFIRM      PromptUI: [Accept message] [Edit] [Retry AI] [Abort]
  │               (auto-accept only with --yes)
  │
  ├─ COMMIT       git commit -F <message>   (message via stdin)
  │               └─ pre-commit hook fails → surface hook output → exit 1
  │
  └─ PUSH         git push origin <current-branch>
                  ├─ success → "done: pushed to '<branch>'" → exit 0
                  └─ failure → report committed state + retry command:
                         git push origin <current-branch>
                         → exit 1  (repo is committed, push is pending)
```

### Solo sequence diagram

```
Developer        relay              git               LLM
   │              │                 │                 │
   │  relay --solo │                 │                 │
   │─────────────▶│ preflight       │                 │
   │              │────────────────▶│ git add .       │
   │              │────────────────▶│ diff --cached   │
   │              │────────────────▶│                 │
   │              │  request ────────────────────────▶│
   │              │  conventional commit ◀─────────────│
   │   confirm    │                 │                 │
   │◀────────────▶│                 │                 │
   │   commit     │────────────────▶│                 │
   │   push       │────────────────▶│                 │
   │◀─────────────│  Done           │                 │
```

## 3. Team Mode

**Goal:** working tree → new `status/<feature>` branch → committed & pushed.

Differences from Solo: an extra **BRANCH** step before commit, and `push -u` sets upstream.

```
TEAM
  │
  ├─ STAGE        git add .
  │
  ├─ COLLECT_DIFF same as solo
  │
  ├─ GENERATE     same as solo (including FALLBACK path)
  │
  ├─ BRANCH       resolve feature name:
  │                 precedence: --team <name> > derive from current branch > prompt
  │               build name from template (default "status/<feature>",
  │                 env RELAY_BRANCH_TEMPLATE): lowercase, spaces→"-", strip
  │                 illegal chars and '.'/'..' path segments, cap at 100 chars
  │               if branch already exists locally → git error (exit 1, with stderr)
  │               git checkout -b status/<feature>
  │
  ├─ CONFIRM      same as solo
  │
  ├─ COMMIT       git commit -F <message>
  │
  └─ PUSH         git push -u origin status/<feature>   (upstream set)
                  ├─ success → "done: pushed to 'status/<feature>'" → exit 0
                  └─ failure → report committed state + retry command:
                         git push -u origin status/<feature>
                         → exit 1 (branch + commit are safe locally)
```

### Team sequence diagram

```
Developer        relay               git                LLM
   │              │                   │                  │
   │relay --team feat │ git add .     │                  │
   │─────────────▶│──────────────────▶│                  │
   │              │  diff --cached    │                  │
   │              │──────────────────▶│                  │
   │              │  request ───────────────────────────▶│
   │              │  message ◀────────────────────────────│
   │              │  checkout -b status/feat             │
   │              │──────────────────▶│                  │
   │  confirm     │                   │                  │
   │◀────────────▶│  commit -F        │                  │
   │              │──────────────────▶│                  │
   │              │  push -u origin   │                  │
   │              │──────────────────▶│                  │
   │◀─────────────│  Done             │                  │
```

## 4. The AI Fallback Mechanism (shared by both modes)

**Design invariant (FR-7):** an AI failure must never abort the workflow — it degrades to manual input and **continues from the same point**.

### 4.1 When fallback triggers

| Trigger | Detection |
| --- | --- |
| Provider offline / connection refused | `AIError{Unavailable}` |
| Request timeout | context deadline exceeded |
| Rate limited / server error (429, 5xx) | after 2 retries with backoff |
| Missing API key (Gemini) | fails fast during GENERATE |
| Garbage / invalid output | Conventional Commit validator rejects response |

### 4.2 Fallback state machine

```
                ┌───────────────┐
                │   GENERATE    │
                └───┬───────┬───┘
                    │       │
             AI success     │ AI error (typed AIError)
                    │       ▼
                    │  ┌──────────────┐   reason banner:
                    │  │   FALLBACK   │  "AI unavailable (<reason>)..."
                    │  └──────┬───────┘  + show diff stat (context)
                    │         ▼
                    │  ┌─────────────────────────────┐
                    │  │   MANUAL INPUT (input())    │
                    │  │   subject line, then an     │
                    │  │   optional body; blank line │
                    │  │   to finish                 │
                    │  └──────┬──────────┬───────────┘
                    │         │          │
                    │     message   empty / abort
                    │     entered      │
                    │         │        ▼
                    │         ▼   exit 130, nothing committed
                    │  ┌─────────────┐
                    └─▶│  proceed to │  ── normal path continues:
                       │  COMMIT     │      BRANCH (team) → COMMIT → PUSH
                       └─────────────┘   (confirmation is skipped for
                                          manually typed messages)
```

- The user's typed message is committed **verbatim** — no validation and no re-prompt. A body is accepted: type the subject on the first line, add body lines below, and press Enter on an empty line to finish; the subject and body are separated by a blank line so `git` keeps the first line as the subject.
- An immediately empty answer (blank first line) aborts the run.
- Non-TTY (piped) environments: the manual prompt cannot be answered (`EOFError`); the run ends with exit `1` and nothing committed — it never hangs.

### 4.3 Confirmation prompt (CONFIRM state)

```
Generated message:
  feat(payments): add invoice retry webhook handler

[Accept]  [Edit]  [Retry AI]  [Abort]
```

- **Accept** → proceed to COMMIT.
- **Edit** → type a replacement message at the manual-message prompt.
- **Retry AI** → re-run GENERATE (bounded, max 3 attempts total).
- **Abort** → exit 130, no changes beyond staging (`git add .` already happened).

## 5. Mode Comparison

| Step | Solo | Team |
| --- | --- | --- |
| Stage all | `git add .` | `git add .` |
| Collect diff | `git diff --cached` | `git diff --cached` |
| Generate message | AI → fallback → manual | AI → fallback → manual |
| Branch | — (stay on current) | `git checkout -b status/<feature>` |
| Commit | `git commit -F -` | `git commit -F -` |
| Push | `git push origin <cur>` | `git push -u origin <branch>` |
| On push failure | commit kept, retry hint shown | branch kept locally, retry hint shown |

## 6. Edge Cases & Error Handling Matrix

| # | Situation | Behavior | Exit |
| --- | --- | --- | --- |
| 1 | Not a git repository | `relay: not a git repository — run from inside a work tree` | 1 |
| 2 | Empty repo (no HEAD) | preflight fails, hints `git commit --allow-empty` | 1 |
| 3 | Nothing to commit | `nothing to commit, working tree clean` | 0 |
| 4 | No remote configured | warning; push fails with retry hint | 1 |
| 5 | Branch already exists (team) | `git checkout -b` fails; git stderr surfaced | 1 |
| 6 | AI offline | fallback → manual input → workflow continues | 0 |
| 7 | AI rate-limited / server error | `AIError` (429/5xx) → fallback | 0 |
| 8 | AI returns invalid format | validator rejects → fallback | 0 |
| 9 | User aborts prompt | no commit made (staging only), exit 130 | 130 |
| 10 | Pre-commit hook fails | abort before push; print hook output | 1 |
| 11 | Push rejected (non-fast-forward) | commit kept; retry hint shown | 1 |
| 12 | Commit OK, push network failure | report committed state + exact retry command | 1 |
| 13 | Diff exceeds token budget | truncation (FR-14) deferred to v0.2 | — |
| 14 | Non-TTY, AI fails | no hang; ends with exit 1, nothing committed | 1 |
| 15 | Missing `GEMINI_API_KEY` / unknown provider | fail fast at startup, before any git action | 1 |
| 16 | `--staged` but nothing staged | preflight passes (unstaged changes exist), staged diff is empty → "nothing to commit" | 0 |
| 17 | `relay undo` with no commits / not a repo | clear GitError, nothing changed | 1 |

## 7. Branch Naming Rules (Team Mode)

1. Feature name resolution: `--team <name>` **>** derive from current branch (last path segment) **>** interactive prompt.
2. Template expansion: `status/<feature>` (configurable via `RELAY_BRANCH_TEMPLATE`) → e.g. `status/payments`.
3. Sanitization: lowercase, whitespace → `-`, strip `~ ^ : ? * [ \`, drop `.`/`..` path segments, cap at 100 chars; `git checkout -b` is git's final authority.

## 8. Idempotency & Safety Guarantees

- **Atomicity** — the commit is the irreversible point. Everything before it is reversible (staging, branch creation). If anything fails before COMMIT, the repo is left in a clean, safe state.
- **No destructive git** — never `push --force`, never rebase without user action, never reset/delete branches.
- **Recovery** — every failure message states (a) the current repo state and (b) the exact next command to run.
