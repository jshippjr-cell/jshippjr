#!/usr/bin/env bash
# Commit (and optionally push) with the required author + trailers.
# Usage: commit.sh [--push] "Subject line" ["extra body paragraph"]
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PUSH=0
if [ "${1:-}" = "--push" ]; then PUSH=1; shift; fi
SUBJECT="${1:?usage: commit.sh [--push] \"subject\" [\"body\"]}"
BODY="${2:-}"

SESSION_URL="https://claude.ai/code/session_01PSpX4aKyR8QswBcjt2tLDp"
MSG="$SUBJECT"
if [ -n "$BODY" ]; then MSG="$MSG

$BODY"; fi
MSG="$MSG

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: $SESSION_URL"

git -c user.name="Claude" -c user.email="noreply@anthropic.com" \
  commit -m "$MSG"

if [ "$PUSH" = "1" ]; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  for delay in 0 2 4 8 16; do
    sleep "$delay"
    if git push -u origin "$BRANCH"; then exit 0; fi
  done
  echo "push failed after retries" >&2
  exit 1
fi
