#!/usr/bin/env bash
# Test runner. No args: full suite, parallel. With file args: targeted, serial
# (-n0 — parallel workers wedge in Thread.start() when the container suspends).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [ "$#" -eq 0 ]; then
  exec python -m pytest tests/ -q
else
  exec python -m pytest "$@" -q -n0
fi
