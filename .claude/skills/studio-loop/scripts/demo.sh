#!/usr/bin/env bash
# Fresh, seeded demo server for Scoring Stage verification.
# Usage: demo.sh [port] [db-path]
set -euo pipefail
PORT="${1:-8093}"
SCRATCH="${SCRATCH:-/tmp/chordential-demo}"
mkdir -p "$SCRATCH"
DB="${2:-$SCRATCH/stage.db}"
LOG="$SCRATCH/uv-$PORT.log"

# Free the port. fuser matches by socket, never by process name (no self-kill).
fuser -k "${PORT}/tcp" 2>/dev/null || true
sleep 0.3
rm -f "$DB"

CHORDENTIAL_DB="$DB" CHORDENTIAL_SEED_DEMO=1 \
  nohup python -m uvicorn chordential_oia.web.app:app \
    --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
PID=$!
echo "server pid=$PID port=$PORT db=$DB log=$LOG"

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  echo "server failed to start; last log lines:" >&2
  tail -20 "$LOG" >&2
  exit 1
fi

python "$(dirname "$0")/tokens.py" "$DB" "http://127.0.0.1:$PORT"
