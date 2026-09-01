# Releasing Relay

This runbook describes how to cut a release. Every step is scripted or
CI-verified, so the only manual work is choosing a version number.

## Checklist

- [ ] Working tree is clean and CI is green on `main`.
- [ ] The version-consistency test (`tests/test_version.py`) passes — it
      asserts `pyproject.toml` and `relay.__version__` match, so a bump can
      never ship half-applied.
- [ ] The Homebrew tap formula (`Fiqqar/homebrew-Relay` → `relay.rb`) and
      `bucket/relay.json` point at the new version's assets (URL + `sha256`) —
      see step 1b below.

## Steps

### 1. Bump the version

Update **both** of these to the same value (e.g. `0.3.0`):

- `pyproject.toml` → `[project] version`
- `relay/__init__.py` → `__version__`

### 1b. Re-point the package channels (same version)

After the version bump, re-point both package channels so installs track the
release:

- **Homebrew** — update `relay.rb` in the **`Fiqqar/homebrew-Relay` tap repo**:
  `url` (sdist `...v<ver>/relay_cli-<ver>.tar.gz`) + `sha256`, then commit and
  push there. The main repo no longer ships a formula.
- **Scoop** — update `bucket/relay.json` → `version`, `url` (wheel), and `hash`
  (the installer script already references the wheel via `$version`, so Scoop
  autoupdate keeps it in sync automatically)

Fetch the hashes from the **published** release's assets (built by CI once
the tag is pushed) — **never** from a local `python -m build`, because pure-
Python wheels and sdists are not byte-reproducible across environments
(e.g. a local build on Windows/Python 3.14 hashes differently from the CI
build on Ubuntu/Python 3.12), and a wrong hash breaks `scoop install`.
A release whose manifests still point at an older patch silently ships the
previous version.

### 2. Verify + commit

```bash
python -m pytest -q        # must be green (version test included)
relay --yes                # AI commit message, solo mode, pushes to main
```

Wait for CI (`main`) to go green before tagging.

### 3. Tag and publish

```bash
git tag v1.0.0
git push origin v1.0.0
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
pip install "https://github.com/Fiqqar/Relay/releases/download/v0.9.0/relay_cli-0.9.0-py3-none-any.whl"
relay --version    # -> relay 0.9.0
relay doctor       # -> all checks resolve
```

## Rollback

Nothing is ever deleted from GitHub Releases; a broken release is fixed by
bumping to the next patch (`v0.3.1`) and following the same steps.

## Distribution channels

| Channel | Status |
| --- | --- |
| GitHub Releases (sdist + wheel) | primary |
| Homebrew | tap `Fiqqar/relay` (repo `Fiqqar/homebrew-Relay`, formula `relay.rb`) |
| Scoop | bucket `relay` (`bucket/relay.json`, autoupdate via `$version`) |

_This file is part of the v0.3 "Release & Distribution" milestone._
