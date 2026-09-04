#!/usr/bin/env bash
#
# e2e_test.sh - Safe end-to-end test for Relay (macOS / Linux / WSL)
#
# Creates a throwaway git repo, makes one dummy file change, and runs the real
# `relay --solo` binary against it. It never touches real projects, never needs
# an API key, and never hits the network:
#
#   * OLLAMA_BASE_URL is pointed at a dead port so the AI call fails
#     deterministically -> the shipped CLI's manual-input fallback kicks in.
#   * The expected commit message is piped into stdin so input() is answered.
#   * --no-push means no remote is required.
#
# Usage:
#   ./e2e_test.sh          (or:  bash e2e_test.sh)
set -euo pipefail

# Locate relay binary; fall back to python -m relay if not on PATH
if command -v relay >/dev/null 2>&1; then
  relay_cmd=(relay)
elif command -v python3 >/dev/null 2>&1; then
  relay_cmd=(python3 -m relay)
else
  relay_cmd=(python -m relay)
fi

expect="fix: e2e test commit"
repo="$(mktemp -d)"
trap 'rm -rf "$repo"' EXIT

# Force the offline fallback deterministically (dead port) and use ollama provider
# so the test runs completely offline without requiring third-party API keys.
export OLLAMA_BASE_URL="http://127.0.0.1:9"
export RELAY_AI_PROVIDER="ollama"

echo "[e2e] temp repo: $repo"

git init -q "$repo"
git -C "$repo" config user.email "e2e@relay.test"
git -C "$repo" config user.name "Relay E2E"
printf 'hello from e2e\n' >"$repo/dummy.txt"
git -C "$repo" add .

(
  cd "$repo"
  # Quick diagnostic smoke checks
  "${relay_cmd[@]}" --version >/dev/null
  "${relay_cmd[@]}" --help >/dev/null

  echo "[e2e] checking doctor probe"
  "${relay_cmd[@]}" doctor >/dev/null

  # Subject + trailing blank line so the manual-input loop terminates on
  # EOF-free, non-interactive stdin (blank line ends the body loop).
  printf '%s\n\n' "$expect" | "${relay_cmd[@]}" --solo --no-push --provider ollama

  subject="$(git -C "$repo" log -1 --format=%s)"
  if [[ "$subject" != "$expect" ]]; then
    echo "FAIL: commit subject '$subject' != '$expect'" >&2
    exit 1
  fi
  echo "[e2e] PASS: solo flow committed '$subject'"

  # Test direct message flag (-m)
  echo "[e2e] testing direct -m flag commit"
  printf 'direct commit test\n' >"$repo/direct.txt"
  git -C "$repo" add .
  direct_msg="feat: direct flag e2e"
  "${relay_cmd[@]}" -m "$direct_msg" --solo --no-push --yes >/dev/null
  subject2="$(git -C "$repo" log -1 --format=%s)"
  if [[ "$subject2" != "$direct_msg" ]]; then
    echo "FAIL: direct message '$subject2' != '$direct_msg'" >&2
    exit 1
  fi
  echo "[e2e] PASS: direct -m committed '$subject2'"

  # Test repo-level .relay.toml configuration
  echo "[e2e] testing repo-level .relay.toml configuration"
  printf '[relay]\nprovider = "ollama"\n' >"$repo/.relay.toml"
  env -u RELAY_AI_PROVIDER "${relay_cmd[@]}" doctor >/dev/null
  echo "[e2e] PASS: doctor verified .relay.toml"
)

echo "[e2e] PASS: all e2e checks passed and temp repo cleaned up"
