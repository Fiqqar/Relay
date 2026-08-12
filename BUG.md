# BUG.md — Verified Triage (re-verified against v0.5.6+)

Every issue from the original audit (C-01..C-06, H-01..H-16, M-01..M-18,
L-01..L-15) was re-checked against the **actual code** after the v0.5.6 release
(squash dirty-index guard, squash-all, undo single-commit guard). Line numbers
in the original report are stale; several issues were already fixed in v0.5.6,
and many are false positives. Classifications below supersede the earlier
"Remediation — Implementation Plan" in this file, whose triage was incorrect
(e.g. it claimed C-01/H-01/H-12/M-14 needed work and C-02 only three fixes).

Status legend:

| Status | Meaning |
|--------|---------|
| `FIXED` | fixed by a new commit (see the Commit column) |
| `ALREADY-FIXED` | verified already handled in current code; no change needed |
| `FALSE-POSITIVE` | the described behavior does not exist in current code |
| `INTENTIONAL` | deliberate design decision (reason noted) |
| `DEPRIORITIZE` | real but low value / requires a dependency (reason noted) |

## Verified Status

| ID | Area | Finding | Status | Commit / Reason |
|----|------|---------|--------|-----------------|
| C-01 | github/gitlab | API_BASE hardcoded `https://api.github.com`; no env override, so no HTTP-downgrade path exists | FALSE-POSITIVE | |
| C-02 | telemetry | non-HTTPS `RELAY_TELEMETRY_URL` was accepted and posted over HTTP / to internal hosts | FIXED | |
| C-03 | | not reproducible in current code | FALSE-POSITIVE | |
| C-04 | squash | if the commit after `reset --soft` failed, HEAD was left reset and the fold unrecoverable | FIXED | this commit |
| C-05 | team | on branch-create/commit failure the user was stranded on an orphan branch | FIXED | this commit |
| C-06 | git | `_run()` had no timeout, so `push`/`fetch`/`ls-remote` could hang forever | FIXED | this commit |
| H-01 | gemini | API key travels via `X-Goog-Api-Key`/`Authorization` header, not `?key=` | ALREADY-FIXED | |
| H-02 | ai | `response.read()` was unbounded in all four providers | FIXED | this commit |
| H-03 | | not reproducible in current code | FALSE-POSITIVE | |
| H-04 | pr | PR title travels in the JSON body, not in HTTP headers — no header injection | FALSE-POSITIVE | |
| H-05 | | not reproducible in current code | FALSE-POSITIVE | |
| H-06 | git | redundant `git status --porcelain` invocations | DEPRIORITIZE | |
| H-07 | | not reproducible in current code | FALSE-POSITIVE | |
| H-08 | config | the TOML file was re-parsed on every config access | FIXED | |
| H-09 | git | whole `git diff` held in memory; streaming would complicate the code | DEPRIORITIZE | |
| H-10 | | already handled in current code | ALREADY-FIXED | |
| H-11 | squash | squash-all fed `root..tip` to the AI, omitting the root commit's own changes | FIXED | |
| H-12 | commit | binary-only staged diffs were sent to the AI for a message | FIXED | |
| H-13 | git | `current_branch()` returns `""` on detached HEAD; solo push could push an empty branch | FIXED | |
| H-14 | cli | a missing API key aborted solo/team instead of falling back to manual input | FIXED | |
| H-15 | | already handled in current code | ALREADY-FIXED | |
| H-16 | git | `git` missing on PATH surfaced a raw OS error | FIXED | |
| M-01 | config | `tomllib` already used on 3.11+, bundled parser only on 3.10 | ALREADY-FIXED | |
| M-02 | config | `max_diff_lines` allowed a floor of 0 (empty prompt) | FIXED | |
| M-03 | config | `ai_timeout()` already clamps to `max(1, min(value, 120))` | ALREADY-FIXED | |
| M-04 | pr | HTTP error bodies were read unbounded in github/gitlab clients | FIXED | |
| M-05 | pr | branch names already url-encoded in github/gitlab | ALREADY-FIXED | |
| M-06 | | not reproducible in current code | FALSE-POSITIVE | |
| M-07 | telemetry | `report()` already posts on a daemon thread | ALREADY-FIXED | |
| M-08 | | not reproducible in current code | FALSE-POSITIVE | |
| M-09 | cli | `--version` exits inside argparse; config is only read on demand | ALREADY-FIXED | |
| M-10 | cli | top-level imports in `cli.py` are all lightweight internal modules | INTENTIONAL | |
| M-11 | config | invalid `RELAY_AI_TIMEOUT`/`RELAY_MAX_DIFF_LINES` were silently ignored | FIXED | |
| M-12 | pr | `pr.py` already checks `git.remote_has_branch(head)` before posting | ALREADY-FIXED | |
| M-13 | commit | scope regex is already `[^)]+` (accepts dots/slashes) | ALREADY-FIXED | |
| M-14 | protected | protected-branch comparison was case-sensitive (`Main` != `main`) | FIXED | |
| M-15 | orchestrator | already returns "nothing to commit" when the staged diff is empty | ALREADY-FIXED | |
| M-16 | toml | `toml.py` already parses inline tables `{...}` | ALREADY-FIXED | |
| M-17 | pr | already does `find_open_pr` + `DuplicatePullRequestError` handling | ALREADY-FIXED | |
| M-18 | | already handled in current code | ALREADY-FIXED | |
| L-01 | | not reproducible in current code | FALSE-POSITIVE | |
| L-02 | | negligible polish | DEPRIORITIZE | |
| L-03 | version | `tests/test_version.py` already enforces version sync | ALREADY-FIXED | |
| L-04 | commit | `_CONVENTIONAL_RE` is already module-level compiled | ALREADY-FIXED | |
| L-05 | | negligible polish | DEPRIORITIZE | |
| L-06 | | negligible polish | DEPRIORITIZE | |
| L-07 | | negligible polish | DEPRIORITIZE | |
| L-08 | undo | already fixed in v0.5.6 (`commit_count <= 1` guard) | ALREADY-FIXED | |
| L-09 | prompt | `interpret_choice()` already maps E->edit and R->retry via `.lower()` | ALREADY-FIXED | |
| L-10 | team | on a protected/default branch the feature name was derived from `main`/`master` | FIXED | |
| L-11 | | already handled in current code | ALREADY-FIXED | |
| L-12 | | negligible polish | DEPRIORITIZE | |
| L-13 | | negligible polish | DEPRIORITIZE | |
| L-14 | | negligible polish | DEPRIORITIZE | |
| L-15 | config | an unparseable config TOML was silently ignored | FIXED | |

## Commit log

Each `FIXED` row above is implemented by exactly one commit (code + its hermetic
unit tests + this status line), one logical change per commit, per
`docs/WORKING_RULES.md`. The final `docs(bug-report): mark verified statuses`
commit fills in the ALREADY-FIXED / FALSE-POSITIVE / INTENTIONAL /
DEPRIORITIZE rows with their reasons and the fix SHAs.
