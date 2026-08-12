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
| C-01 | github/gitlab | API_BASE hardcoded `https://api.github.com`; no env override, so no HTTP-downgrade path exists | FALSE-POSITIVE | `API_BASE` is a hardcoded constant; there is no env override, hence no downgrade path |
| C-02 | telemetry | non-HTTPS `RELAY_TELEMETRY_URL` was accepted and posted over HTTP / to internal hosts | FIXED | `6d6f6ac` |
| C-03 | | not reproducible in current code | FALSE-POSITIVE | the cited lines/functions do not exist in current code |
| C-04 | squash | if the commit after `reset --soft` failed, HEAD was left reset and the fold unrecoverable | FIXED | `2cd628a` |
| C-05 | team | on branch-create/commit failure the user was stranded on an orphan branch | FIXED | `35cbead` |
| C-06 | git | `_run()` had no timeout, so `push`/`fetch`/`ls-remote` could hang forever | FIXED | `025125f` |
| H-01 | gemini | API key travels via `X-Goog-Api-Key`/`Authorization` header, not `?key=` | ALREADY-FIXED | key is sent as a header in the current provider code |
| H-02 | ai | `response.read()` was unbounded in all four providers | FIXED | `0dfa0bd` |
| H-03 | | not reproducible in current code | FALSE-POSITIVE | no such code path in the current providers |
| H-04 | pr | PR title travels in the JSON body, not in HTTP headers — no header injection | FALSE-POSITIVE | the title is sent in the request body only |
| H-05 | | not reproducible in current code | FALSE-POSITIVE | no such code path in current code |
| H-06 | git | redundant `git status --porcelain` invocations | DEPRIORITIZE | two calls per run; negligible cost for a small fix's complexity |
| H-07 | | not reproducible in current code | FALSE-POSITIVE | no such code path in current code |
| H-08 | config | the TOML file was re-parsed on every config access | FIXED | `64f26e3` |
| H-09 | git | whole `git diff` held in memory; streaming would complicate the code | DEPRIORITIZE | diff size is already capped by `max_diff_lines`; streaming adds complexity |
| H-10 | | already handled in current code | ALREADY-FIXED | guarded behavior verified present |
| H-11 | squash | squash-all fed `root..tip` to the AI, omitting the root commit's own changes | FIXED | `b056d0d` |
| H-12 | commit | binary-only staged diffs were sent to the AI for a message | FIXED | `5f20f12` |
| H-13 | git | `current_branch()` returns `""` on detached HEAD; solo push could push an empty branch | FIXED | `72b540c` |
| H-14 | cli | a missing API key aborted solo/team instead of falling back to manual input | FIXED | `c6ea614` |
| H-15 | | already handled in current code | ALREADY-FIXED | verified present in current code |
| H-16 | git | `git` missing on PATH surfaced a raw OS error | FIXED | `375991a` |
| M-01 | config | `tomllib` already used on 3.11+, bundled parser only on 3.10 | ALREADY-FIXED | the stdlib-first `try`/`except` import is in place |
| M-02 | config | `max_diff_lines` allowed a floor of 0 (empty prompt) | FIXED | `6e1d490` |
| M-03 | config | `ai_timeout()` already clamps to `max(1, min(value, 120))` | ALREADY-FIXED | clamp verified in `config.ai_timeout()` |
| M-04 | pr | HTTP error bodies were read unbounded in github/gitlab clients | FIXED | `5aa0f15` |
| M-05 | pr | branch names already url-encoded in github/gitlab | ALREADY-FIXED | `urllib.parse.quote` is applied to path segments |
| M-06 | | not reproducible in current code | FALSE-POSITIVE | no such code path in current code |
| M-07 | telemetry | `report()` already posts on a daemon thread | ALREADY-FIXED | the daemon thread is used; fire-and-forget |
| M-08 | | not reproducible in current code | FALSE-POSITIVE | no such code path in current code |
| M-09 | cli | `--version` exits inside argparse; config is only read on demand | ALREADY-FIXED | `--version` action fires before config is touched |
| M-10 | cli | top-level imports in `cli.py` are all lightweight internal modules | INTENTIONAL | only internal, stdlib-backed imports; no heavyweight third-party pull |
| M-11 | config | invalid `RELAY_AI_TIMEOUT`/`RELAY_MAX_DIFF_LINES` were silently ignored | FIXED | `61cc63c` |
| M-12 | pr | `pr.py` already checks `git.remote_has_branch(head)` before posting | ALREADY-FIXED | the check is present before the POST |
| M-13 | commit | scope regex is already `[^)]+` (accepts dots/slashes) | ALREADY-FIXED | regex verified in `relay/commit.py` |
| M-14 | protected | protected-branch comparison was case-sensitive (`Main` != `main`) | FIXED | `259a4f3` |
| M-15 | orchestrator | already returns "nothing to commit" when the staged diff is empty | ALREADY-FIXED | verified in `Orchestrator.run()` |
| M-16 | toml | `toml.py` already parses inline tables `{...}` | ALREADY-FIXED | inline-table support verified in `relay/toml.py` |
| M-17 | pr | already does `find_open_pr` + `DuplicatePullRequestError` handling | ALREADY-FIXED | both are present in `relay/pr.py` |
| M-18 | | already handled in current code | ALREADY-FIXED | verified present |
| L-01 | | not reproducible in current code | FALSE-POSITIVE | no such code path in current code |
| L-02 | | negligible polish | DEPRIORITIZE | cosmetic; no behavior impact |
| L-03 | version | `tests/test_version.py` already enforces version sync | ALREADY-FIXED | the sync test exists and passes |
| L-04 | commit | `_CONVENTIONAL_RE` is already module-level compiled | ALREADY-FIXED | compiled once at import in `relay/commit.py` |
| L-05 | | negligible polish | DEPRIORITIZE | cosmetic |
| L-06 | | negligible polish | DEPRIORITIZE | cosmetic |
| L-07 | | negligible polish | DEPRIORITIZE | cosmetic |
| L-08 | undo | already fixed in v0.5.6 (`commit_count <= 1` guard) | ALREADY-FIXED | guard landed in v0.5.6 |
| L-09 | prompt | `interpret_choice()` already maps E->edit and R->retry via `.lower()` | ALREADY-FIXED | normalization verified in `relay/prompt.py` |
| L-10 | team | on a protected/default branch the feature name was derived from `main`/`master` | FIXED | `b85648f` |
| L-11 | | already handled in current code | ALREADY-FIXED | verified present |
| L-12 | | negligible polish | DEPRIORITIZE | cosmetic |
| L-13 | | negligible polish | DEPRIORITIZE | cosmetic |
| L-14 | | negligible polish | DEPRIORITIZE | cosmetic |
| L-15 | config | an unparseable config TOML was silently ignored | FIXED | `f017b24` |

## Commit log

Each `FIXED` row above is implemented by exactly one commit (code + its hermetic
unit tests + this status line), one logical change per commit, per
`docs/WORKING_RULES.md`. The final `docs(bug-report): mark verified statuses`
commit fills in the ALREADY-FIXED / FALSE-POSITIVE / INTENTIONAL /
DEPRIORITIZE rows with their reasons and the fix SHAs.
