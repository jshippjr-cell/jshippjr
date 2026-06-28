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

from . import db


def run(spec: dict) -> None:
    """Execute one job described by ``spec`` against a fresh DB connection."""
    action = spec.get("action")
    agency_id = spec.get("agency_id")
    reset = bool(spec.get("reset", False))

    # Re-read the DB path from the environment (the parent passes it through), so
    # the worker connects to the same database whether it runs as a real subprocess
    # or is driven in-process by a test.
    conn = db.connect(os.environ.get("CHORDENTIAL_DB") or db.DEFAULT_DB_PATH)
    try:
        if action == "enrich":
            from . import enrichment
            enrichment.enrich_agency(conn, agency_id, reset=reset)

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
    try:
        spec = json.loads(argv[0])
    except (ValueError, TypeError):
        return 2
    run(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
