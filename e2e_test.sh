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

expect="fix: e2e test commit"
repo="$(mktemp -d)"
trap 'rm -rf "$repo"' EXIT

# Force the offline fallback deterministically (dead port).
export OLLAMA_BASE_URL="http://127.0.0.1:9"

echo "[e2e] temp repo: $repo"

git init -q "$repo"
git -C "$repo" config user.email "e2e@relay.test"
git -C "$repo" config user.name "Relay E2E"
printf 'hello from e2e\n' >"$repo/dummy.txt"
git -C "$repo" add .

(
  cd "$repo"
  # Subject + trailing blank line so the manual-input loop terminates on
  # EOF-free, non-interactive stdin (blank line ends the body loop).
  printf '%s\n\n' "$expect" | relay --solo --no-push --provider ollama
)

subject="$(git -C "$repo" log -1 --format=%s)"
if [[ "$subject" != "$expect" ]]; then
  echo "FAIL: commit subject '$subject' != '$expect'" >&2
  exit 1
fi

echo "[e2e] PASS: solo flow committed '$subject'"
