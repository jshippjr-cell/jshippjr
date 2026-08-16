"""Out-of-process runner for the heavy enrichment engines.

Why a separate process and not a thread: enrichment fetches and *parses* real
agency webpages, and a pathological page can send a C-level parse/regex into a
runaway that holds Python's global lock and never returns. In-process (even on a
daemon thread) that freezes the whole web server — no requests served, no logs,
the live "wheel of death" — and it cannot be interrupted from another thread; the
only cure is to kill the process. So the web app launches this module as its own
process with a hard timeout (see scheduler._run_worker): its own interpreter lock,
its own memory, and fully killable, so a runaway job dies alone and the site never
even notices.

Invoked as:  python -m chordential_oia.web._enrich_worker '<json-spec>'
where spec is {"action": "enrich"|"decision_makers"|"pipeline"|"batch",
"agency_id": int, "reset": bool, "limit": int, "delay": float}.
"""
from __future__ import annotations

import json
import os
import sys

# Memory ceiling: this worker parses arbitrary web pages, and one runaway
# allocation must kill THIS process, not the 512MB instance it shares with the
# web server (an instance-level OOM takes the whole site down — observed live).
# RLIMIT_AS makes a runaway die here as MemoryError -> non-zero exit, which the
# supervisor already handles by marking the agency and moving on.
def _cap_memory() -> None:
    """Apply the ceiling. Called from ``main`` — deliberately NOT at import.

    It used to run at import time, and the limit is set soft AND hard together, which is
    irreversible even as root. So any process that merely IMPORTED this module was capped
    at 320MB for the rest of its life, and the only symptom was that `Thread.start()`
    silently blocked for ever once the process grew past the cap — no exception, no
    message, just a hang. `tests/test_scheduler_loop.py` imports this module to drive the
    worker in-process, which capped pytest; run alone the suite fit inside 320MB and
    passed, and in a batch alongside other files it deadlocked in `asyncio.to_thread`.
    Diagnosed by py-spy on the hung process after a full-suite run stalled.

    Guarding on ``__main__`` would be subtler and weaker: `run()` is called directly by
    tests, so the entrypoint is the honest place to put a whole-process side effect.
    """
    try:  # pragma: no cover - platform-dependent
        import resource
        cap_mb = max(128, int(os.environ.get("CHORDENTIAL_WORKER_MAX_MB", "320")))
        resource.setrlimit(resource.RLIMIT_AS, (cap_mb * 1024 * 1024,) * 2)
    except Exception:  # noqa: BLE001 — best-effort; absent on non-POSIX
        pass


from . import db


def _log(msg: str) -> None:
    print(f"[enrich-worker] {msg}", flush=True)   # goes to the parent's stdout → Render logs


def run(spec: dict) -> None:
    """Execute one job described by ``spec`` against a fresh DB connection."""
    action = spec.get("action")
    agency_id = spec.get("agency_id")
    reset = bool(spec.get("reset", False))
    _log(f"start action={action} agency={agency_id}")

    # Re-read the DB path from the environment (the parent passes it through), so
    # the worker connects to the same database whether it runs as a real subprocess
    # or is driven in-process by a test.
    conn = db.connect(os.environ.get("CHORDENTIAL_DB") or db.DEFAULT_DB_PATH)
    try:
        if action == "enrich":
            from . import enrichment
            res = enrichment.enrich_agency(conn, agency_id, reset=reset)
            _log(f"done action=enrich agency={agency_id} status={res.get('status')}")

        elif action == "decision_makers":
            from . import decision_makers
            decision_makers.discover_decision_makers(conn, agency_id, reset=reset)

        elif action == "pipeline":
            # The whole chain for one agency, in order; a failing step never sinks
            # the rest (each consumes the prior step's stored output).
            from . import (enrichment, decision_makers, intelligence,
                           opportunity_signals, music_opportunity)
            steps = (
                lambda: enrichment.enrich_agency(conn, agency_id, reset=reset),
                lambda: decision_makers.discover_decision_makers(conn, agency_id, reset=reset),
                lambda: intelligence.generate_intelligence(conn, agency_id),
                lambda: opportunity_signals.detect_signals(conn, agency_id, force=True),
                lambda: music_opportunity.score_agency(conn, agency_id),
            )
            for step in steps:
                try:
                    step()
                except Exception:
                    pass

        elif action == "batch":
            from . import enrichment
            enrichment.enrich_batch(conn, limit=int(spec.get("limit", 5)),
                                    delay=float(spec.get("delay", 0.0)))
    finally:
        conn.close()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return 2
    # The ceiling belongs to the WORKER PROCESS, so it is applied here, where we know
    # this process exists to run one job and die. See `_cap_memory`.
    _cap_memory()
    try:
        spec = json.loads(argv[0])
    except (ValueError, TypeError):
        return 2
    run(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
