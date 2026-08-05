# NEXT SESSION — handoff notes

> **Temporary handoff doc.** Delete this file once the remaining work below is done.

## Where things stand

All work is on independent feature branches off `main`. `main` does **not** contain
the pushed features below — each branch was created from `main` and pushed via
`relay --team <feature> --yes` (AI-generated Conventional Commit message).

### Done & pushed
| Feature | Branch | Commit message |
| --- | --- | --- |
| `relay pr` pre-push check (`relay/pr.py`, `relay/git_manager.py`, `tests/test_pr.py`) | `feat/pr-push-check` | `feat(pr): fail fast if PR branch is unpushed` |
| `--no-verify` flag (`relay/cli.py`, `relay/git_manager.py`, `relay/orchestrator.py` + tests) | `feat/no-verify-flag` | `feat(git): add --no-verify option to skip git hooks` |

### In progress — `relay amend` (WIP on `feat/amend`)
Done so far:
- `relay/git_manager.py` — `commit()` gained `amend: bool = False` → appends `--amend`.
- `relay/orchestrator.py` — `mode="amend"` support: `run()` routes to new
  `_run_amend(message, branch)` (dry-run support + "already pushed → force-with-lease"
  warning). Never pushes.

**Still missing (finish next session):**
1. `relay/cli.py` — add an `amend` subparser with `--provider`, `--timeout`, `--yes`,
   `--staged`, `--dry-run`, `--verbose`; route it so `Orchestrator(mode="amend", ...)` is
   built. In `main()`, branch on `args.command == "amend"` before the solo/team mode
   resolution.
2. Tests:
   - `tests/test_git_manager.py` — commit with `amend=True` → `["git", "commit", "--amend", "-F", "-"]`.
   - `tests/test_cli.py` — amend subcommand parses + routes to `mode="amend"`.
   - `tests/test_orchestrator.py` — amend mode: commit called with `amend=True`,
     no branch/push; "already pushed" warning; dry-run; empty staged diff → `0`.
3. Update `README.md` commands table with the `amend` row.

## Remaining features (in suggested order)

- **F4 — auto-retry + backoff for 429/5xx** in `relay/orchestrator.py::_obtain_message`.
  `docs/FLOW.md` §4.1 already promises "after 2 retries with backoff". Retry only on
  `AIError.kind in {"rate_limited", "api_error"}`, max 2 tries, backoff ~2s/4s
  (`time.sleep`); mock `relay.orchestrator.time.sleep` in tests. Other kinds fall back
  to manual input immediately (current behavior).
- **F5 — `relay pr --draft`**: `relay/github.py::open_pull` gains `draft=False` →
  `payload["draft"] = draft`; `relay/pr.py::run_pr` + CLI `pr` subparser gain `--draft`; tests.
- **F6 — TOML config file**: `relay/config.py`. Use `tomllib` (Python 3.11+; warn +
  fall back to env on 3.10). Path: `$XDG_CONFIG_HOME/relay/config.toml` (POSIX) or
  `%APPDATA%\relay\config.toml` (Windows), overridable via `RELAY_CONFIG`. `[relay]`
  table: `provider`, `ai_timeout`, `branch_template`, `max_diff_lines`, `pr_open`,
  `gemini_model`, `ollama_model`, `ollama_base_url`. Precedence: flags > env > file >
  defaults. Secrets (`GEMINI_API_KEY`, `GITHUB_TOKEN`) stay env-only (NFR-3). Refactor
  accessors through a `_resolve(env_key, cfg_key, default)` helper. Update `tests/test_config.py`.
- **F7 — untrack `tests/__pycache__/*.pyc`**: `git rm -r --cached tests/__pycache__`,
  commit. `.gitignore` already ignores `__pycache__/` and `*.pyc`. (`relay/__pycache__`
  and `relay/ai/__pycache__` were already untracked in the merge-commit chore.)
- **F8 — fix docs mismatch**: README (Features, Commands table, Configuration table) and
  `docs/FLOW.md` still say the team-mode default branch template is `status/<feature>`,
  but `relay/config.py` `DEFAULT_BRANCH_TEMPLATE = "<type>/<feature>"`. Make docs match code.

## Workflow rules for the next session

1. Base = `main` (`git checkout main` first; keep it in sync with `origin/main`).
2. Per feature: implement → `python -m pytest -q` → **`git checkout -- tests/__pycache__`**
   (the `tests/__pycache__/*.pyc` files are still *tracked*, so pytest dirties the tree
   and `git add .` would stage them) → verify `git status --porcelain` shows only the
   feature's files → `python -m relay --team <feature> --yes` (AI message; `GEMINI_API_KEY`
   is already set) → verify the remote branch → `git checkout main`.
3. Each feature is an independent branch off `main`. `main` never contains the pushed
   feature changes, so don't build one feature on top of another's changes.
4. If a feature touches the same files as an already-pushed feature (e.g. `commit()` /
   `orchestrator.py`), you'll get merge conflicts when those branches merge into `main` —
   resolve them in the merge/PR, not by rebasing onto the other feature branch.

## Environment notes
- `GEMINI_API_KEY`, `GITHUB_TOKEN` set in env. `relay` runs as `python -m relay` or `relay`.
- Repo: `https://github.com/Fiqqar/Relay.git`, default branch `main`, PRs per branch.
