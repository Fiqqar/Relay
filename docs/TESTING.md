# Relay — Testing Strategy

> How Relay stays at ≥90% branch coverage and why every commit must ship its test.

---

## 1. Philosophy

- **Hermetic:** tests never touch network, `$HOME`, real AI, or real git identity. Everything is faked/mocked.
- **Same-commit tests:** new behavior + its test land in one commit (`WORKING_RULES.md` #2) — no "follow-up test PR".
- **Branch coverage, not line:** `branch = true` in `pyproject.toml:31` catches missing `if/else` arms.

## 2. Gates (must be green before push)

```bash
python -m pytest -q --cov=relay --cov-branch --cov-fail-under=90
ruff check .
mypy relay
```

CI mirrors this on 3 OS × 3 Python (see `.github/workflows/ci.yml`). E2E `e2e_test.sh` / `e2e_test.ps1` runs per platform.

## 3. Test Layers

### 3.1 Unit — pure logic

| Area | File | What it pins |
|------|------|--------------|
| Conventional Commit validation, sanitization, branch naming | `tests/test_commit.py` | `relay/commit.py` grammar, `build_branch_name` sanitization |
| TOML subset parser | `tests/test_toml.py` | `relay/toml.py` vs `tomllib` edge cases (escaped quotes, exponents) |
| Config resolution & precedence | `tests/test_config.py` | `relay/config.py` flags>env>file>defaults, env-only secrets, `_RAW_CACHE` |
| Protected-branch guard | `tests/test_protected.py` | `relay/protected.py` case-insensitive, env/file/default precedence |
| Version consistency | `tests/test_version.py` | `relay/__init__.py` == `pyproject.toml` version |
| Error taxonomy & NFR-7 audit | `tests/test_error_audit.py` | Every `raise RelayError` carries actionable message (scans `relay/**/*.py`) |
| CLI surface stability & freeze | `tests/test_cli.py` | All 9 subcommands, flags, and options match ADR-012 frozen contract |
| Performance timing harness (NFR-1) | `tests/test_performance.py` | CLI startup, config cache, and orchestrator dispatch latency < 50 ms |

### 3.2 Provider — HTTP without network

| Area | File | Pattern |
|------|------|---------|
| Gemini / Ollama / OpenAI / Anthropic / Mistral / Groq / xAI | `tests/test_ai.py`, `tests/test_prompt.py` | `unittest.mock.patch("urllib.request.urlopen", ...)` with fake `urlopen` + canned JSON; timeout/rate-limit/bad-response via `AIError(kind=...)` |
| Prompt building & truncation | `tests/test_prompt.py` | `build_prompt(diff, stat, branch)` + `RELAY_MAX_DIFF_LINES` mock via `monkeypatch` |

### 3.3 Git — subprocess without git

| Area | File | Pattern |
|------|------|---------|
| GitManager wrappers | `tests/test_git_manager.py` | `FakeGit` / mock `subprocess.run` argv assertions; `shell=False` never appears |
| Orchestrator state machine | `tests/test_orchestrator.py` | FakeGit + FakeAI + patched `input()` → assert `STAGE → COLLECT → GENERATE → CONFIRM → COMMIT → PUSH` & fallback paths |
| Squash / Undo / Stage | `tests/test_squash.py`, `tests/test_undo.py`, `tests/test_stage.py` | `diff_range`/`stat_range` vs `staged_diff` isolation; dirty-index refusal; soft-reset semantics |
| PR routing (GitHub/GitLab/Bitbucket) | `tests/test_github.py`, `tests/test_gitlab.py`, `tests/test_bitbucket.py`, `tests/test_pr.py` | Remote parsing, URL-encode, draft prefix, trusted-host refusal |

### 3.4 Integration / E2E

- `e2e_test.sh` (Linux/macOS) & `e2e_test.ps1` (Windows) — throwaway repo (`git init` + files), run real `relay` binary with no API key, assert fallback → manual input → commit → push path.
- CI runs the right script per OS; `relay doctor` also exercised there.

## 4. Hermetic Patterns (copy these)

```python
# Mock env, not real env
monkeypatch.setenv("RELAY_AI_PROVIDER", "ollama")
monkeypatch.delenv("GEMINI_API_KEY", raising=False)

# Mock HTTP, not real LLM
with patch("urllib.request.urlopen", return_value=fake_response):
    msg = provider.generate_commit_message(diff, stat, branch)

# Mock input, not real stdin
with patch("builtins.input", side_effect=["feat(x): add thing", ""]):
    orchestrator.run()

# Mock subprocess, not real git
# Use FakeGit from tests/conftest.py — it records argv lists and returns canned stdout
```

**Never do:** `os.environ["X"] = "..."` without cleanup, real `urlopen`, real `input()`, or `shell=True`.

## 5. Coverage Tips

- Run focused: `pytest -q --cov=relay --cov-branch --cov-report=term-missing -k test_orchestrator`
- Missing branches usually hide in: error/fallback arms, `ConfigError` lazy build, non-TTY `EOFError`, binary diff skip, detached HEAD refusal.
- Add the missing arm + a test that triggers `AIError(kind="...")` or `ConfigError` → assert fallback/manual path

## 6. Adding Tests for New Code

1. Add behavior in `relay/` + test in `tests/test_*.py` **same commit**.
2. Keep `pyproject.toml` dev array single-line (parser limitation).
3. Ensure `pytest --cov-fail-under=90` passes locally before `relay --solo --yes`.

## 7. Performance & Quality Guarantees
- Performance NFR-1 (<500 ms CLI overhead) is continuously benchmarked by `tests/test_performance.py` (<50 ms pure overhead).
- NFR-7 usability audit is enforced on every commit by `tests/test_error_audit.py`.
- Zero-dependency stdlib purity and ≥90% branch coverage gate enforced in CI.

## 8. Quick Commands

```bash
pytest -q                          # all
pytest -k "test_ai or test_commit" # filtered
pytest --cov=relay --cov-branch --cov-report=html  # html report in htmlcov/
ruff check .                       # lint
mypy relay                         # types
bash e2e_test.sh                   # e2e (Linux/macOS)
powershell -ExecutionPolicy Bypass -File e2e_test.ps1  # e2e Windows
```
