## Summary

<!-- Brief description of the changes made and problem solved. -->

## Changes Proposed

- 
- 

## Verification & Testing

<!-- How was this tested? E.g.: -->
- [ ] `pytest -q --cov --cov-fail-under=90` passes locally
- [ ] `ruff check .` passes (0 errors)
- [ ] `mypy relay` passes (0 errors)

## Repository Rules Checklist (`docs/WORKING_RULES.md`)

- [ ] **One logical change = one commit** with Conventional Commits format (`type(scope): subject`).
- [ ] **Zero runtime dependencies**: stdlib only (`dependencies = []` in `pyproject.toml`).
- [ ] **Subprocess safety**: all `subprocess` invocations use `argv-as-list` (`shell=True` strictly forbidden).
- [ ] **Secrets env-only**: no credentials or API keys logged or written to disk.
- [ ] Tests and docs updated alongside code changes.
