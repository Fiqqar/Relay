# AGENTS.md — for AI / agents working in this repo

> Read this first, every time you start a new work session in this repo.

## Required reading

Before changing any code, read **`docs/WORKING_RULES.md`** in full and follow its
rules. Those rules bind humans and AI alike and are summarized briefly here:

- **One logical change = one commit** (Conventional Commits:
  `type(scope): subject`). Don't mix unrelated topics into a single commit.
- **Never commit/push before** `pytest` (coverage ≥ 85%), `ruff check .`, and
  `mypy relay` are all green. New tests must ship in the same commit as the code.
- **Zero runtime dependencies** — stdlib only.
- **`pyproject.toml`** dev deps must stay a single-line array (tests parse it
  with an internal TOML parser that does not support multi-line arrays).
- **All subprocesses argv-as-list; `shell=True` is forbidden.** Secrets env-only.
- **No mass reformatting** (don't `ruff format` the whole repo), don't tidy up
  code unrelated to the task.
- Do tasks one at a time and create a separate commit per task as instructed.

## Repo info

- Python 3.10+, entry point `relay.cli:main`, packages `relay` + `relay.ai`.
- Git identity: `Fiqqar` / `fiqarsilmy@gmail.com`.
- Remote: `https://github.com/Fiqqar/Relay.git`. Default branch: `main`.
- Releases: runbook in `RELEASE.md` (bump version, re-point Formula/Scoop with
  real hashes from a local `python -m build`, tag `v*` triggers release CI).