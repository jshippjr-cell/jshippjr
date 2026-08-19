#!/bin/bash
# The whole suite, in batches, on a small container.
#
# `pytest -n auto` stalls here (CLAUDE.md), so the suite is run in batches of N files
# with -n0. The reason this script exists rather than a one-liner: a batch runner that
# summarises with `tail -3` and greps that for the word "failed" is easy to write and
# easy to misread — a commit went out with four red tests under exactly that arrangement
# (2026-08-19). So this prints every FAILED/ERROR line it saw, and exits non-zero.
#
#   scripts/run_tests_batched.sh [batch_size]
set -u
cd "$(dirname "$0")/.."
SIZE=${1:-7}
files=(tests/*.py)
n=${#files[@]}
i=0; b=0; failing=0
declare -a names=()
while [ $i -lt $n ]; do
  batch=("${files[@]:$i:$SIZE}")
  b=$((b + 1))
  out=$(python -m pytest "${batch[@]}" -q -n0 2>&1)
  echo "batch $b/$(( (n + SIZE - 1) / SIZE )): $(echo "$out" | grep -E '[0-9]+ (passed|failed)' | tail -1)"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    names+=("$line")
    failing=$((failing + 1))
  done < <(echo "$out" | grep -E '^(FAILED|ERROR)')
  i=$((i + SIZE))
done
echo
if [ $failing -gt 0 ]; then
  echo "=== $failing FAILING:"
  printf '%s\n' "${names[@]}"
  exit 1
fi
echo "=== $b batches, all green."
