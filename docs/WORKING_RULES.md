# Working Rules (Mandatory Reading)

> **MUST-READ.** This document **must** be read in full **before doing any work**
> in this repo — by humans and by any AI/agent working on their behalf. If you are
> an AI, start every work session by reading this file first (and
> `CONTRIBUTING.md` for the release process). Breaking a rule here = PR rejected /
> work redone.

## Core principles

Relay is a small CLI that prides itself on **zero runtime dependencies** and a
**clean Git history**. Those two things are the guiding star. Every technical
decision must protect both.

## Mandatory rules

### 1. Commits — Conventional Commits, one change per commit

- Format: `type(scope): subject`, e.g. `fix(squash): refuse dirty index`.
- Valid types: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`,
  `perf`, `build`, `ci`, `revert`.
- **One logical change = one commit.** If the subject needs the word "and", split it.
- Don't mix a fix + docs + refactor into a single commit.
- Imperative subject ("add", not "added"), under ~72 characters.

### 2. Never push without verification

Before pushing, run these in order and make sure they all PASS:

```bash
python -m pytest -q --cov=relay --cov-branch --cov-fail-under=90
ruff check .
mypy relay
```

- The 90% (branch) coverage gate is mandatory.
- Unit tests for new behavior **must land in the same commit** as the code.
- Tests must be hermetic: no dependence on the network, `$HOME`, real AI
  providers, or env vars that are not set in CI.

### 3. Zero runtime dependencies — absolute

- Stdlib only. Do not add a runtime dependency without a very strong reason
  (and it must be discussed first).
- Dev dependencies live in a single-line array in `pyproject.toml` — **do not
  split them into multi-line**, because `tests/test_version.py` parses
  `pyproject.toml` with Relay's internal TOML parser, which does not support
  multi-line arrays. Breaking this = tests fail.

### 4. Security & Git integrity

- **All subprocesses go through argv-as-list; `shell=True` is NEVER allowed.**
- Secrets (API keys, tokens) **come only from env vars** — never written to a
  file, never committed, never logged.
- Don't add destructive git operations (`reset --hard`, `checkout -- .`,
  automatic force-push) to the flow. Relay's flow guarantees "no destructive git".

### 5. No mass reformatting

- Don't run `ruff format` (or any other formatter) over the whole repo — it
  reformats dozens of files and adds noise to history. Lint with `ruff check .` only.

### 6. If you are an AI, special rules

- Read this file at **the start of every work session** before touching any file.
- Don't bundle multiple tasks into one commit — create a separate commit per
  fix/feature, per the convention above.
- One task = one branch = one PR (rule #8); never push to `main` directly.
- Don't "tidy up" code unrelated to your task. If you spot another bug, note it
  and report it — don't silently fix it inside an unrelated commit.
- Never edit a file without reading the surrounding context first.
- If an instruction is unclear or large in scope, ask first — don't guess.

### 7. Final verification before handing off

- Run all checks from rule #2.
- If you touched the solo fallback flow, also run the e2e:
  `bash e2e_test.sh` (macOS/Linux) or `powershell -ExecutionPolicy Bypass -File e2e_test.ps1` (Windows).
- Report concisely: what changed, why, and the verification results

### 8. Dogfooding — commit via Relay itself (humans push straight, AI via PR)

- Every logical change **must be committed with `relay` itself** — not `git commit`.
  This self-tests the workflow on the repo that builds the tool and proves the
  change survives the real preflight → stage → AI/manual → confirm → commit →
  push path, not just `pytest`.
- If AI is offline/rate-limited, `relay` falls back to manual input — still use
  it (type the Conventional subject + body, blank line to finish). Never bypass
  with `git commit -m`.
- **Humans — split & push straight:** one `relay` run = one Conventional Commit =
  one `git push` immediately after verification (rule #2), via `relay --solo --yes`
  (`main`) or `relay --team <feat> --yes` (feature). Don't batch multiple fixes
  into one push; don't hold commits locally.
- **AI — branch + PR + self-merge, never direct to `main`:**
  1. One task = one branch (`relay --team <feat> --yes`), one PR (`relay pr`).
     AI must never push to `main` directly.
  2. Push the branch, open the PR, wait for CI to go green.
  3. AI self-reviews: re-read the full diff, re-run the rule #2 checks, confirm
     the PR contains only the task's files.
  4. AI merges itself (e.g. `gh pr merge --merge`) only when CI is green and the
     review is clean — the human never has to click merge.

### 9. Release tagging — strictly 'vx.y.z' only

- Tag format: `vx.y.z` (e.g. `v1.0.1`), strictly SemVer with a leading `v`.
- **No extra words or descriptive phrases** in the tag name or GitHub release title (never `Release vx.y.z`, `v1.0.1-final`, etc.). Tag identifier and release title must always be strictly `vx.y.z` only.
- Tag annotations can contain release notes (`git tag vx.y.z -m "..."`), but the tag name itself must remain purely `vx.y.z`.

## Common mistakes (checklist)

- [ ] Commit subject > 72 characters / not imperative
- [ ] One commit bundles many unrelated changes
- [ ] New test not included in the same commit
- [ ] `pyproject.toml` changed to a multi-line array
- [ ] Added a runtime dependency without discussion
- [ ] Reformatted files untouched by the task
- [ ] Pushed before tests/lint/mypy are green
- [ ] Committed with `git commit` instead of `relay --solo/--team --yes` (not dogfooded)
- [ ] Batched multiple `relay` commits locally instead of push-straight per change (humans)
- [ ] AI pushed directly to `main` instead of branch → PR → self-merge
- [ ] Release tag or release title contains extra words (must be strictly 'vx.y.z' only)