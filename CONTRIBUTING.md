# Contributing to Relay

Thanks for taking the time to contribute! Relay is a small, dependency-light CLI
that prides itself on clean Git history — so we take our conventions seriously.

> **Start here:** [`docs/WORKING_RULES.md`](docs/WORKING_RULES.md) is the
> mandatory rules document. Read it fully before touching any code — it binds
> humans and AI/agents alike (one logical change per commit, coverage gate,
> zero runtime deps, no `ruff format` mass reformatting).

## Table of Contents

- [Getting started](#getting-started)
- [Development setup](#development-setup)
- [Conventions](#conventions)
  - [Conventional Commits](#conventional-commits)
  - [Branch naming](#branch-naming)
- [Working rules](#working-rules)
- [Adding an AI provider](#adding-an-ai-provider)
- [Running tests](#running-tests)
- [Static analysis & type checking](#static-analysis--type-checking)
- [End-to-end test](#end-to-end-test)
- [Releases](#releases)

## Getting started

- Fork the repository and clone your fork.
- Relay targets **Python 3.10+** and has **zero runtime dependencies** —
  please keep it that way. Any contribution that adds a runtime dependency
  needs a strong justification.
- Ask before starting a large change: open an issue or a discussion so the work
  doesn't collide with something already in flight.

## Development setup

```bash
python -m pip install -e ".[dev]"
```

The `dev` extra installs the test suite (`pytest`), the build backend
(`build`), plus the lint/type-check tooling (`ruff`, `mypy`, `pytest-cov`).

## Conventions

### Conventional Commits

- Commit messages **must** follow [Conventional Commits](https://www.conventionalcommits.org/):
  `type(scope): subject`.
- Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`,
  `perf`, `style`.
- Keep subject lines under ~72 characters, imperative mood ("add", not "added").
- One logical change per commit. If you have to say "and" in the subject, split it.

### Branch naming

- Feature branches use the same convention Relay itself generates:
  `<type>/<feature>`, e.g. `feat/squash-file-whitespace`.
- Never push directly to `main`/`master`.

## Working rules

The full binding rules live in [`docs/WORKING_RULES.md`](docs/WORKING_RULES.md).
The short version every change must satisfy:

- One logical change per commit (Conventional Commits).
- Unit tests for new behavior ship in the same commit.
- Before pushing: `pytest` (coverage ≥ 90%), `ruff check .`, `mypy relay` all green.
- Zero runtime dependencies; keep `pyproject.toml` dev deps as a single-line array.
- Never `ruff format` the whole repo; only touch code related to your task.

## Adding an AI provider

Providers live behind a common interface (see `relay/ai/base.py`):

1. Create `relay/ai/<name>.py` with a class subclassing the base provider.
2. Register it in the `_PROVIDERS` registry used by the CLI.
3. Add unit tests mirroring the existing provider tests (`tests/test_ai.py`),
   using the fake/offline patterns already there.
4. Add a `done` check to `relay doctor` if it needs credentials.
5. Update `docs/ARCHITECTURE.md` and the README provider matrix.

## Running tests

```bash
pytest            # full suite
pytest -q         # quiet
pytest -k <sub>   # filter by test name
```

- The suite must stay **hermetic**: never depend on the network, `$HOME`,
  real AI providers, or environment variables that CI won't set.
- New behavior should ship with its unit test in the same commit.

## Static analysis & type checking

```bash
ruff check .      # lint
mypy relay        # type checking
```

CI enforces both, so running them locally before pushing saves a round trip.

## End-to-end test

`e2e_test.sh` (macOS/Linux) and `e2e_test.ps1` (Windows) exercise the real
`relay` binary against a throwaway git repo, with no API key and no network.
CI runs the right script per platform — verify your change doesn't break the
solo fallback flow:

```bash
bash e2e_test.sh                       # macOS/Linux
powershell -ExecutionPolicy Bypass -File e2e_test.ps1   # Windows
```

## Releases

- Versions follow Semantic Versioning.
- Releasing is runbooked in [`RELEASE.md`](RELEASE.md).
- Every release bumps `relay/__init__.py`/`pyproject.toml`, re-points the
  Homebrew formula and Scoop manifest, and updates `CHANGELOG.md`.
- Maintainers cut releases by pushing a `v*` tag; CI publishes the artifacts.

Need something not covered here? Open an issue and we'll figure it out together.