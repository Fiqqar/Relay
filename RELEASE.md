# Releasing Relay

This runbook describes how to cut a release. Every step is scripted or
CI-verified, so the only manual work is choosing a version number.

## Checklist

- [ ] Working tree is clean and CI is green on `main`.
- [ ] The version-consistency test (`tests/test_version.py`) passes — it
      asserts `pyproject.toml` and `relay.__version__` match, so a bump can
      never ship half-applied.

## Steps

### 1. Bump the version

Update **both** of these to the same value (e.g. `0.3.0`):

- `pyproject.toml` → `[project] version`
- `relay/__init__.py` → `__version__`

### 2. Verify + commit

```bash
python -m pytest -q        # must be green (version test included)
relay --yes                # AI commit message, solo mode, pushes to main
```

Wait for CI (`main`) to go green before tagging.

### 3. Tag and publish

```bash
git tag v0.3.0
git push origin v0.3.0
```

Pushing the `v*` tag triggers the **Release** workflow
(`.github/workflows/release.yml`), which:

1. runs the full test suite,
2. builds the sdist and wheel (`python -m build`),
3. smoke-tests the built wheel (`pip install dist/*.whl && relay --version`),
4. creates a GitHub Release and uploads `dist/*` as assets.

### 4. Verify the artifact

The wheel is published at a predictable URL:

```bash
pip install "https://github.com/Fiqqar/Relay/releases/download/v0.3.0/relay_cli-0.3.0-py3-none-any.whl"
relay --version    # -> relay 0.3.0
relay doctor       # -> all checks resolve
```

## Rollback

Nothing is ever deleted from GitHub Releases; a broken release is fixed by
bumping to the next patch (`v0.3.1`) and following the same steps.

## Distribution channels

| Channel | Status |
| --- | --- |
| GitHub Releases (sdist + wheel) | primary |
| Homebrew / Scoop | planned |

_This file is part of the v0.3 "Release & Distribution" milestone._
