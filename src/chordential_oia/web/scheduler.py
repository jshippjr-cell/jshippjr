"""Background auto-fetch — the crawler runs on its own (Discovery Phase 2).

An in-process asyncio loop. The web service is an always-on Starter instance and
the SQLite DB lives on a disk only this service can mount, so the scheduler runs
*inside* the web process (a separate Render cron service couldn't reach the DB).

Each cycle, if auto-fetch is enabled, it fetches a bounded batch of *due* targets
on active (On), non-login-gated sources: newly-Approved targets (the backlog),
plus previously-Fetched ones due for a re-scan. The human gate is unchanged —
only approved-lineage targets are ever touched, results land in the review queue,
and login-gated sources are never auto-fetched.

Controls (env):
  CHORDENTIAL_ENABLE_SCRAPE      master switch; auto-fetch is off without it
  CHORDENTIAL_AUTOFETCH=0        disable just the scheduler (manual fetch only)
  CHORDENTIAL_AUTOFETCH_INTERVAL seconds between cycles (default 900)
  CHORDENTIAL_REFETCH_HOURS      re-scan a fetched target after this many hours (12)
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from . import db, discovery

# Live, in-process status surfaced on the Discovery console (single instance, so
# in-memory is fine; it's transient and resets on restart).
_status = {
    "running": False,      # a cycle is executing right now
    "current": None,       # label of the target being fetched right now
    "last_run": None,      # ISO timestamp of the last completed cycle
    "last_found": 0,       # leads/creators found in the last cycle
    "fetched_total": 0,    # cumulative since boot
    "cycles": 0,
}

_FALSEY = {"0", "false", "no", "off", ""}

# ONE shared lock across every heavy background cycle (enrich, re-enrich, decision
# makers, intelligence, signals, scoring). Only one heavy job runs at a time — auto
# OR manual — so a small instance is never hit by several batches at once (the
# overload that hung the live service). Each cycle keeps its own "running" flag for
# the UI but gates execution on this lock.
_heavy_lock = threading.Lock()

# The loop wakes on a short base tick and each periodic task gates itself by its
# own interval (below). This decouples them: enrichment can fire every 5 min even
# though the heavier feed/autofetch passes run every 15 — they no longer throttle
# each other through one shared sleep.
_last_signals_mono = 0.0
_last_reddit_mono = 0.0
_last_autofetch_mono = 0.0


def _base_tick_seconds() -> int:
    try:
        return max(10, int(os.environ.get("CHORDENTIAL_LOOP_TICK", "30")))
    except ValueError:
        return 30


def _signals_interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_SIGNALS_INTERVAL", "900")))
    except ValueError:
        return 900


def autofetch_enabled() -> bool:
    """On only when scraping is enabled AND the scheduler isn't explicitly off."""
    return discovery.scrape_enabled() and (
        os.environ.get("CHORDENTIAL_AUTOFETCH", "1").strip().lower() not in _FALSEY
    )


def _run_in_background(fn) -> None:
    """Run ``fn(conn)`` in a daemon thread, holding the shared heavy lock for its
    duration (so it never overlaps another heavy job) with its own DB connection.
    Used by the per-agency Enrich / Find-decision-makers actions: those fetch live
    pages (slow), so doing them inline spins the request — this returns instantly
    and the page shows progress on refresh."""
    def _job():
        _heavy_lock.acquire()                    # wait our turn; never overlap
        try:
            conn = db.connect()
            try:
                fn(conn)
            finally:
                conn.close()
        except Exception:
            pass
        finally:
            _heavy_lock.release()
    threading.Thread(target=_job, daemon=True).start()


def _worker_timeout_seconds(default: int) -> int:
    try:
        return max(30, int(os.environ.get("CHORDENTIAL_WORKER_TIMEOUT", str(default))))
    except ValueError:
        return default


def _run_worker(spec: dict, timeout: int, on_done=None) -> None:
    """Launch the heavy job in a SEPARATE, KILLABLE process and return at once.

    Parsing a hostile webpage can drive a C-level regex/parse into a runaway that
    holds Python's global lock forever — in-process that freezes the whole web
    server (silent logs, the live wheel of death) and cannot be interrupted from a
    thread. A subprocess has its own interpreter lock + memory and is killable, so a
    watchdog thread reaps it after ``timeout`` and the web process is never affected.
    The watchdog only does ``p.wait()`` (blocking I/O — releases the GIL), so it
    can't starve anything either."""
    args = [sys.executable, "-m", "chordential_oia.web._enrich_worker",
            json.dumps(spec)]

    def _supervise():
        try:
            try:
                proc = subprocess.Popen(args, env=dict(os.environ))
            except Exception:
                return                            # couldn't even spawn — give up
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()                   # runaway parse — kill, don't wait forever
                except Exception:
                    pass
            except Exception:
                pass
        finally:
            # ALWAYS run on_done — even if Popen failed — so a guard flag set by the
            # caller (e.g. "a batch is running") can never get stuck on permanently.
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    threading.Thread(target=_supervise, daemon=True).start()


def start_agency_enrich(agency_id: int, *, reset: bool = False) -> bool:
    """Enrich ONE agency in a separate, killable process (it fetches the live site).
    Returns True if started; False if scraping is off here (a no-op the UI explains)."""
    if not discovery.scrape_enabled():
        return False
    _run_worker({"action": "enrich", "agency_id": agency_id, "reset": reset},
                _worker_timeout_seconds(180))
    return True


def start_agency_decision_makers(agency_id: int, *, reset: bool = False) -> bool:
    """Discover ONE agency's decision makers in a separate, killable process."""
    if not discovery.scrape_enabled():
        return False
    _run_worker({"action": "decision_makers", "agency_id": agency_id, "reset": reset},
                _worker_timeout_seconds(180))
    return True


def start_agency_pipeline(agency_id: int, *, reset: bool = False) -> bool:
    """Run the WHOLE chain for ONE agency, in order, in a single killable worker
    process: enrich → decision makers → intelligence → signals → score. One agency,
    sequential — one press builds the complete profile instead of clicking five
    buttons. Each step consumes the prior step's output (the ordering guarantees it);
    a failing step never sinks the rest. Needs scraping for the live-fetch steps."""
    if not discovery.scrape_enabled():
        return False
    _run_worker({"action": "pipeline", "agency_id": agency_id, "reset": reset},
                _worker_timeout_seconds(600))
    return True


def autonomous_engines_on() -> bool:
    """Master switch for the heavy agency engines running AUTONOMOUSLY in the loop
    (enrich, re-enrich, decision makers, intelligence, signals, scoring). Default
    OFF: these are CPU-heavy batches that, run unattended on a small single-CPU
    instance, starve the web server (the live 502/restart loop). The manual buttons
    always work regardless; flip CHORDENTIAL_AUTONOMOUS=1 to let them run on their
    own (recommended only on a larger instance)."""
    return os.environ.get("CHORDENTIAL_AUTONOMOUS", "0").strip().lower() not in _FALSEY


# Autonomous Gmail triage (Phase B2). Off by default — opt in with
# CHORDENTIAL_TRIAGE_ENABLED — and only when triage is actually configured
# (Gmail creds + Anthropic key). Each due cycle reads the unread alert queue,
# lands real gigs in the review queue, and fires a phone alert per new gig.
_triage_status = {"last_run": None, "last_created": 0, "total_created": 0, "cycles": 0}
_last_triage_mono = 0.0


def triage_enabled() -> bool:
    from . import triage
    return (
        os.environ.get("CHORDENTIAL_TRIAGE_ENABLED", "0").strip().lower() not in _FALSEY
        and triage.is_configured()
    )


def _triage_interval_seconds() -> int:
    try:
        return max(120, int(os.environ.get("CHORDENTIAL_TRIAGE_INTERVAL", "900")))
    except ValueError:
        return 900


def run_triage_cycle() -> int:
    """One autonomous triage pass — reads unread alerts, lands + alerts on new
    gigs. Blocking; runs in a worker thread. Returns the new gigs created."""
    from . import triage
    conn = db.connect()
    try:
        res = triage.run_triage(conn, notify=True)
    finally:
        conn.close()
    return res.get("created", 0)


def triage_status() -> dict:
    s = dict(_triage_status)
    s["enabled"] = triage_enabled()
    return s


# Autonomous Company Enrichment (the agent enriches on its own). On when
# scraping is enabled and not explicitly disabled. Each due cycle enriches a
# bounded batch of not-yet-complete agencies, so the Master Company Database
# fills in quality over time without anyone pressing Enrich.
_enrich_status = {"last_run": None, "last_completed": 0, "total_completed": 0,
                  "cycles": 0, "pending": 0, "running": False,
                  "running_since": None, "running_ttl": 0.0,
                  "batch_done": 0, "batch_target": 0}
_last_enrich_mono = 0.0
_enrich_lock = threading.Lock()


def _manual_enrich_running() -> bool:
    """Is a manual enrich batch genuinely in flight? Self-healing: if the flag has
    been set longer than the worker's own timeout (+ margin), the worker is long
    gone and the flag is stale — clear it so the button can never stick disabled."""
    if not _enrich_status.get("running"):
        return False
    since = _enrich_status.get("running_since")
    ttl = _enrich_status.get("running_ttl") or 0.0
    if since is not None and (time.monotonic() - since) > ttl + 30:
        _enrich_status["running"] = False
        return False
    return True


def enrich_enabled() -> bool:
    return discovery.scrape_enabled() and (
        os.environ.get("CHORDENTIAL_AUTOENRICH", "1").strip().lower() not in _FALSEY
    )


def _enrich_interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_AUTOENRICH_INTERVAL", "300")))
    except ValueError:
        return 300


def _enrich_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_AUTOENRICH_BATCH", "10")))
    except ValueError:
        return 10


def _enrich_delay_seconds() -> float:
    """Pause between agencies in a batch. On a single-CPU instance a back-to-back
    batch pins the box and starves the one web worker (the "wheel of death" while
    a manual enrich runs); ``time.sleep`` here releases the GIL so the web server
    gets a guaranteed slice between each site. Tunable; 0 disables (tests)."""
    try:
        return max(0.0, float(os.environ.get("CHORDENTIAL_ENRICH_DELAY", "1.5")))
    except ValueError:
        return 1.5


def run_enrich_cycle(batch: int = 0) -> int:
    """One autonomous enrichment pass — enriches up to ``batch`` agencies, EACH in
    its own killable worker process (so a hostile page can't freeze the server or
    stall the queue). Lock-guarded: a no-op if another heavy job holds the lock, so
    it just retries next interval. Returns how many completed this pass."""
    limit = batch or _enrich_batch_size()
    if not _heavy_lock.acquire(blocking=False):
        return 0                              # a heavy job is already running
    _enrich_status["running"] = True
    try:
        return _supervised_pass_locked(
            "enrich", db.agencies_needing_enrichment, _enrich_status,
            limit=limit, on_timeout=_mark_enrichment_error, label="enrich",
            count_fn=db.count_needing_enrichment)
    finally:
        _enrich_status["running"] = False
        _heavy_lock.release()


def _agency_timeout_seconds() -> int:
    """Hard cap for enriching ONE agency. A page can hang the parser indefinitely
    (a runaway regex holds the lock and can't be interrupted), so each agency runs
    in its own worker and is killed past this. Legit-but-slow sites finish well
    under it; true hangs get caught. Tunable via CHORDENTIAL_AGENCY_TIMEOUT."""
    try:
        return max(30, int(os.environ.get("CHORDENTIAL_AGENCY_TIMEOUT", "180")))
    except ValueError:
        return 180


def _mark_enrichment_error(conn, agency_id: int) -> None:
    """Mark an enrichment 'error' (hang OR crash) so the queue advances past a
    hostile page — without a terminal status here, the same earliest-pending
    agency gets re-picked every pass and the whole batch wedges on it forever."""
    try:
        db.save_agency_enrichment(conn, agency_id, {
            "status": "error", "steps_done": [], "links": [], "profile": {},
            "detail": "enrichment failed (timed out or the worker crashed — "
                      "a page likely hung or broke the parser)"})
        conn.commit()
    except Exception:
        pass


def _mark_dm_error(conn, agency_id: int) -> None:
    try:
        db.save_agency_dm(conn, agency_id, {
            "status": "error", "found": 0, "total": 0,
            "detail": "decision-maker discovery failed (timed out or the "
                      "worker crashed — a page likely hung or broke the parser)"})
        conn.commit()
    except Exception:
        pass


def _defer_reenrich(conn, agency_id: int) -> None:
    """A re-enrichment timed out. Keep the existing (good) profile but stamp it
    fresh, so the stale-selector won't immediately pick the same hanging page again."""
    try:
        blob = db.get_agency_enrichment(conn, agency_id) or {}
        blob["last_enriched"] = _now_iso()
        db.save_agency_enrichment(conn, agency_id, blob)
        conn.commit()
    except Exception:
        pass


def _run_one_supervised(conn, action: str, agency_id: int, timeout: int,
                        *, reset: bool = False, label: str = "enrich",
                        on_timeout=None) -> bool:
    """Run ONE agency through ``action`` in its own killable worker process. Returns
    True on a clean exit. On a timeout OR a crash (any non-zero exit) the worker
    can't mark itself, and without a terminal status ``agencies_needing_enrichment``
    would re-pick this SAME agency (earliest not-yet-resolved row) every pass —
    wedging the whole batch on one bad page forever. So ``on_timeout`` runs
    whenever the worker doesn't exit cleanly, not just on a hang."""
    spec = {"action": action, "agency_id": agency_id, "reset": reset}
    args = [sys.executable, "-m", "chordential_oia.web._enrich_worker", json.dumps(spec)]
    try:
        proc = subprocess.Popen(args, env=dict(os.environ))
    except Exception as e:
        print(f"[{label}] agency {agency_id}: spawn failed: {e}", flush=True)
        return False
    try:
        rc = proc.wait(timeout=timeout)
        print(f"[{label}] agency {agency_id}: worker exited {rc}", flush=True)
        if rc != 0 and on_timeout:
            on_timeout(conn, agency_id)
        return rc == 0
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        print(f"[{label}] agency {agency_id}: TIMED OUT after {timeout}s — killed",
              flush=True)
        if on_timeout:
            on_timeout(conn, agency_id)
        return False
    except Exception as e:
        print(f"[{label}] agency {agency_id}: error {e}", flush=True)
        if on_timeout:
            on_timeout(conn, agency_id)
        return False


def _enrich_one_supervised(conn, agency_id: int, timeout: int, *,
                           reset: bool = False) -> bool:
    """Back-compat wrapper: enrich one agency, marking it error on timeout."""
    return _run_one_supervised(conn, "enrich", agency_id, timeout, reset=reset,
                               label="enrich", on_timeout=_mark_enrichment_error)


def _supervised_pass_locked(action, select_fn, status, *, limit, reset=False,
                            on_timeout=None, label="enrich", count_fn=None) -> int:
    """Process up to ``limit`` agencies, EACH in its own killable worker — the shared
    engine for both the manual buttons and the autonomous cycles. The CALLER holds
    ``_heavy_lock`` (so only one heavy job runs at a time). A hostile page freezes
    only that one agency's worker; it's killed, handled, and the pass moves on — so a
    pass always makes forward progress. Updates ``status`` live. Returns completed."""
    per_agency = _agency_timeout_seconds()
    delay = _enrich_delay_seconds()
    status["batch_target"] = limit
    status["batch_done"] = 0
    completed = 0
    conn = db.connect(os.environ.get("CHORDENTIAL_DB") or db.DEFAULT_DB_PATH)
    try:
        for _ in range(max(1, limit)):
            rows = select_fn(conn, limit=1)
            if not rows:
                break                              # nothing left for this engine
            if _run_one_supervised(conn, action, rows[0]["id"], per_agency,
                                   reset=reset, label=label, on_timeout=on_timeout):
                completed += 1
            status["batch_done"] = status.get("batch_done", 0) + 1
            if count_fn:
                try:
                    status["pending"] = count_fn(conn)
                except Exception:
                    pass
            if delay:
                time.sleep(delay)                  # breathe between agencies
    finally:
        status["cycles"] = status.get("cycles", 0) + 1
        status["last_completed"] = completed
        status["total_completed"] = status.get("total_completed", 0) + completed
        status["last_run"] = datetime.now(timezone.utc).isoformat()
        conn.close()
        print(f"[{label}] pass done: {completed} processed", flush=True)
    return completed


def _enrich_batch_supervised(limit: int, on_done=None) -> None:
    """Manual 'Enrich now': run a supervised per-agency pass in a background thread,
    serialized with the autonomous cycles via the shared heavy lock."""
    def _job():
        _heavy_lock.acquire()                      # never overlap another heavy job
        try:
            _supervised_pass_locked(
                "enrich", db.agencies_needing_enrichment, _enrich_status,
                limit=limit, on_timeout=_mark_enrichment_error, label="enrich",
                count_fn=db.count_needing_enrichment)
        finally:
            _heavy_lock.release()
            _enrich_status["running"] = False
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    threading.Thread(target=_job, daemon=True).start()


def start_manual_enrich(batch: int = 0) -> bool:
    """Kick a one-off enrichment pass and return at once. Each agency runs in its
    own SEPARATE, KILLABLE worker process: a hostile page that hangs the parser used
    to freeze the whole web server (the wheel of death); now it can't, and it can't
    even stall the batch — a hung agency is killed, marked failed, and the batch
    moves on. Returns True if started, False if enrichment is disabled or one is
    already running (a second nudge is a no-op, not a second batch on a small box)."""
    if not enrich_enabled():
        return False
    if _manual_enrich_running():
        return False
    limit = batch or _enrich_batch_size()
    # backstop TTL for the self-healing guard: worst case is every agency timing out
    _enrich_status["running"] = True
    _enrich_status["running_since"] = time.monotonic()
    _enrich_status["running_ttl"] = float(limit * _agency_timeout_seconds() + 60)
    _enrich_status["batch_target"] = limit
    _enrich_status["batch_done"] = 0
    _enrich_batch_supervised(
        limit, on_done=lambda: _enrich_status.__setitem__("running", False))
    return True


# Re-enrichment cadence — periodically refresh agencies whose enrichment has gone
# stale, so the Signal Detection Framework has fresh data to diff. Network-heavy
# (re-fetches sites), so it runs on a long interval with a small batch.
_reenrich_status = {"last_run": None, "last_refreshed": 0, "total_refreshed": 0,
                    "cycles": 0, "due": 0, "running": False}
_last_reenrich_mono = 0.0
_reenrich_lock = threading.Lock()


def reenrich_enabled() -> bool:
    return discovery.scrape_enabled() and (
        os.environ.get("CHORDENTIAL_REENRICH", "1").strip().lower() not in _FALSEY
    )


def _reenrich_interval_seconds() -> int:
    try:
        return max(300, int(os.environ.get("CHORDENTIAL_REENRICH_INTERVAL", "21600")))
    except ValueError:
        return 21600


def _reenrich_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_REENRICH_BATCH", "5")))
    except ValueError:
        return 5


def _reenrich_stale_days() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_REENRICH_STALE_DAYS", "7")))
    except ValueError:
        return 7


def run_reenrich_cycle(batch: int = 0) -> int:
    """One re-enrichment pass: refresh up to ``batch`` stale agencies (re-fetch their
    pages, reset=True), EACH in its own killable worker. On timeout the existing
    (good) profile is KEPT and just stamped fresh, so a newly-hostile page doesn't
    cost us the data — it's simply deferred. Lock-guarded. Returns how many ran."""
    limit = batch or _reenrich_batch_size()
    stale = _reenrich_stale_days()
    if not _heavy_lock.acquire(blocking=False):
        return 0
    _reenrich_status["running"] = True
    try:
        def _select(conn, limit):
            return db.agencies_due_for_reenrichment(conn, stale_days=stale, limit=limit)
        refreshed = _supervised_pass_locked(
            "enrich", _select, _reenrich_status, limit=limit, reset=True,
            on_timeout=_defer_reenrich, label="reenrich")
        _reenrich_status["last_refreshed"] = refreshed
        _reenrich_status["total_refreshed"] = \
            _reenrich_status.get("total_refreshed", 0) + refreshed
        return refreshed
    finally:
        _reenrich_status["running"] = False
        _heavy_lock.release()


def start_manual_reenrich(batch: int = 0) -> bool:
    """Kick a one-off re-enrichment pass in the background; return at once."""
    if not reenrich_enabled():
        return False
    if _reenrich_status.get("running"):
        return False
    threading.Thread(target=run_reenrich_cycle, args=(batch,), daemon=True).start()
    return True


def reenrich_status() -> dict:
    s = dict(_reenrich_status)
    s["enabled"] = reenrich_enabled()
    s["autonomous"] = autonomous_engines_on() and reenrich_enabled()
    s["stale_days"] = _reenrich_stale_days()
    return s


# Autonomous Decision Maker Discovery — the same shape as auto-enrichment: on when
# scraping is on and not explicitly disabled, a bounded batch per due cycle, fully
# in the background so the people-to-contact fill in over time on their own.
_dm_status = {"last_run": None, "last_found": 0, "total_found": 0,
              "cycles": 0, "pending": 0, "running": False}
_last_dm_mono = 0.0
_dm_lock = threading.Lock()


def dm_enabled() -> bool:
    return discovery.scrape_enabled() and (
        os.environ.get("CHORDENTIAL_AUTODM", "1").strip().lower() not in _FALSEY
    )


def _dm_interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_AUTODM_INTERVAL", "600")))
    except ValueError:
        return 600


def _dm_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_AUTODM_BATCH", "10")))
    except ValueError:
        return 10


def run_dm_cycle(batch: int = 0) -> int:
    """One decision-maker discovery pass over up to ``batch`` agencies, EACH in its
    own killable worker (live-fetches people pages, so same freeze risk as enrich).
    On timeout the agency is marked dm-'error' so the queue advances. Lock-guarded.
    Returns how many agencies were processed this pass."""
    limit = batch or _dm_batch_size()
    if not _heavy_lock.acquire(blocking=False):
        return 0
    _dm_status["running"] = True
    try:
        return _supervised_pass_locked(
            "decision_makers", db.agencies_needing_decision_makers, _dm_status,
            limit=limit, on_timeout=_mark_dm_error, label="decision-makers",
            count_fn=db.count_needing_decision_makers)
    finally:
        _dm_status["running"] = False
        _heavy_lock.release()


def start_manual_dm(batch: int = 0) -> bool:
    """Kick a one-off decision-maker discovery pass in the background and return at
    once. True if started; False if one's already running or discovery is off here."""
    if not dm_enabled():
        return False
    if _dm_status.get("running"):
        return False
    threading.Thread(target=run_dm_cycle, args=(batch,), daemon=True).start()
    return True


def dm_status() -> dict:
    s = dict(_dm_status)
    s["enabled"] = dm_enabled()
    s["autonomous"] = autonomous_engines_on() and dm_enabled()
    return s


# Autonomous Company Intelligence — derive the structured intelligence profile for
# enriched agencies. Pure computation (no network), so it runs whenever enabled,
# independent of scraping; it simply finds nothing until agencies are enriched.
_intel_status = {"last_run": None, "last_generated": 0, "total_generated": 0,
                 "cycles": 0, "pending": 0, "running": False}
_last_intel_mono = 0.0
_intel_lock = threading.Lock()


def intel_enabled() -> bool:
    return os.environ.get("CHORDENTIAL_AUTOINTEL", "1").strip().lower() not in _FALSEY


def _intel_interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_AUTOINTEL_INTERVAL", "600")))
    except ValueError:
        return 600


def _intel_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_AUTOINTEL_BATCH", "25")))
    except ValueError:
        return 25


def run_intel_cycle(batch: int = 0) -> int:
    """One Company Intelligence pass over up to ``batch`` enriched-but-unprofiled
    agencies. Blocking; runs in a worker thread. Lock-guarded. Returns how many
    profiles were generated this pass."""
    from . import intelligence
    limit = batch or _intel_batch_size()
    if not _heavy_lock.acquire(blocking=False):
        return 0
    _intel_status["running"] = True
    try:
        conn = db.connect()
        try:
            res = intelligence.generate_batch(conn, limit=limit)
            _intel_status["pending"] = db.count_needing_intelligence(conn)
        finally:
            conn.close()
        generated = res.get("generated", 0)
        _intel_status["cycles"] += 1
        _intel_status["last_generated"] = generated
        _intel_status["total_generated"] += generated
        _intel_status["last_run"] = datetime.now(timezone.utc).isoformat()
        return generated
    finally:
        _intel_status["running"] = False
        _heavy_lock.release()


def start_manual_intel(batch: int = 0) -> bool:
    """Kick a one-off intelligence pass in the background; return at once. True if
    started, False if one's already running or intelligence is disabled here."""
    if not intel_enabled():
        return False
    if _intel_status.get("running"):
        return False
    threading.Thread(target=run_intel_cycle, args=(batch,), daemon=True).start()
    return True


def intel_status() -> dict:
    s = dict(_intel_status)
    s["enabled"] = intel_enabled()
    s["autonomous"] = autonomous_engines_on() and intel_enabled()
    return s


# Autonomous Signal Detection — scan enriched agencies for new opportunity signals
# (change detection over the collected profile). Pure computation; a fingerprint
# short-circuit makes scanning cheap, so it sweeps a rotating batch each cycle.
_sig_status = {"last_run": None, "last_new": 0, "total_new": 0,
               "cycles": 0, "scanned": 0, "running": False}
_last_sig_mono = 0.0
_sig_lock = threading.Lock()


def signals_engine_enabled() -> bool:
    return os.environ.get("CHORDENTIAL_AUTOSIGNALS", "1").strip().lower() not in _FALSEY


def _sig_interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_AUTOSIGNALS_INTERVAL", "600")))
    except ValueError:
        return 600


def _sig_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_AUTOSIGNALS_BATCH", "25")))
    except ValueError:
        return 100


def run_signals_cycle(batch: int = 0) -> int:
    """One Signal Detection pass over a rotating batch of enriched agencies.
    Blocking; runs in a worker thread. Lock-guarded. Returns NEW signals stored."""
    from . import opportunity_signals
    limit = batch or _sig_batch_size()
    if not _heavy_lock.acquire(blocking=False):
        return 0
    _sig_status["running"] = True
    try:
        conn = db.connect()
        try:
            res = opportunity_signals.detect_batch(conn, limit=limit)
        finally:
            conn.close()
        new = res.get("new", 0)
        _sig_status["cycles"] += 1
        _sig_status["last_new"] = new
        _sig_status["total_new"] += new
        _sig_status["scanned"] = res.get("scanned", 0)
        _sig_status["last_run"] = datetime.now(timezone.utc).isoformat()
        return new
    finally:
        _sig_status["running"] = False
        _heavy_lock.release()


def start_manual_signals(batch: int = 0) -> bool:
    """Kick a one-off signal-detection pass in the background; return at once."""
    if not signals_engine_enabled():
        return False
    if _sig_status.get("running"):
        return False
    threading.Thread(target=run_signals_cycle, args=(batch,), daemon=True).start()
    return True


def signals_engine_status() -> dict:
    s = dict(_sig_status)
    s["enabled"] = signals_engine_enabled()
    s["autonomous"] = autonomous_engines_on() and signals_engine_enabled()
    return s


# Autonomous Music Opportunity scoring — recompute the explainable score for
# agencies with an intelligence profile. Pure reasoning (no network); re-runs over
# time so the score stays alive as signals and outreach change.
_score_status = {"last_run": None, "last_scored": 0, "movers": 0,
                 "cycles": 0, "running": False}
_last_score_mono = 0.0
_score_lock = threading.Lock()


def score_enabled() -> bool:
    return os.environ.get("CHORDENTIAL_AUTOSCORE", "1").strip().lower() not in _FALSEY


def _score_interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_AUTOSCORE_INTERVAL", "600")))
    except ValueError:
        return 600


def _score_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_AUTOSCORE_BATCH", "25")))
    except ValueError:
        return 100


def run_score_cycle(batch: int = 0) -> int:
    """One Music Opportunity scoring pass over a rotating batch. Blocking; runs in
    a worker thread. Lock-guarded. Returns how many agencies were (re)scored."""
    from . import music_opportunity
    limit = batch or _score_batch_size()
    if not _heavy_lock.acquire(blocking=False):
        return 0
    _score_status["running"] = True
    try:
        conn = db.connect()
        try:
            res = music_opportunity.score_batch(conn, limit=limit)
        finally:
            conn.close()
        scored = res.get("scored", 0)
        _score_status["cycles"] += 1
        _score_status["last_scored"] = scored
        _score_status["movers"] = res.get("movers", 0)
        _score_status["last_run"] = datetime.now(timezone.utc).isoformat()
        return scored
    finally:
        _score_status["running"] = False
        _heavy_lock.release()


def start_manual_score(batch: int = 0) -> bool:
    """Kick a one-off scoring pass in the background; return at once."""
    if not score_enabled():
        return False
    if _score_status.get("running"):
        return False
    threading.Thread(target=run_score_cycle, args=(batch,), daemon=True).start()
    return True


def score_status() -> dict:
    s = dict(_score_status)
    s["enabled"] = score_enabled()
    s["autonomous"] = autonomous_engines_on() and score_enabled()
    return s


def enrich_status() -> dict:
    running = _manual_enrich_running()           # self-heals a stale flag
    s = dict(_enrich_status)
    s["running"] = running
    s["enabled"] = enrich_enabled()
    s["autonomous"] = autonomous_engines_on() and enrich_enabled()
    return s


def _interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get("CHORDENTIAL_AUTOFETCH_INTERVAL", "900")))
    except ValueError:
        return 900


def _refetch_seconds() -> int:
    try:
        return max(1, int(os.environ.get("CHORDENTIAL_REFETCH_HOURS", "12"))) * 3600
    except ValueError:
        return 12 * 3600


def status() -> dict:
    """Snapshot for the UI (includes the live enabled flag)."""
    s = dict(_status)
    s["enabled"] = autofetch_enabled()
    return s


def configured_feeds():
    """RSS feeds to poll, from CHORDENTIAL_RSS_FEEDS — comma-separated, each
    either a URL or 'name|url' so the source is labeled on the radar."""
    feeds = []
    for part in os.environ.get("CHORDENTIAL_RSS_FEEDS", "").split(","):
        part = part.strip()
        if not part:
            continue
        if "|" in part:
            name, url = part.split("|", 1)
            feeds.append((name.strip() or "rss", url.strip()))
        else:
            feeds.append(("rss", part))
    return feeds


def signals_active() -> bool:
    return bool(configured_feeds())


def poll_feeds() -> int:
    """Poll configured gig RSS feeds into the signals tape. Blocking — runs in a
    worker thread; best-effort per feed. No-op when no feeds are configured."""
    feeds = configured_feeds()
    if not feeds:
        return 0
    from . import signals
    conn = db.connect()
    total = 0
    try:
        for name, url in feeds:
            try:
                total += signals.ingest_feed(conn, url, source=name)
            except Exception:
                pass
    finally:
        conn.close()
    return total


# Direct Reddit polling — the cap-free replacement for F5Bot's Reddit coverage.
# Reuses the OAuth adapter in crawl_adapters; runs each result through the strict
# is_music_gig filter (so only real paid gigs land) and the normal new-gig alert.
# Reddit blocks unauthenticated API traffic from datacenters, so this only
# activates when REDDIT_CLIENT_ID/SECRET are set — otherwise it would just 403.
DEFAULT_REDDIT_QUERIES = (
    'https://www.reddit.com/r/gameDevClassifieds/search/?q=composer OR music OR "sound design"&restrict_sr=1&sort=new',
    "https://www.reddit.com/r/INAT/search/?q=composer OR music&restrict_sr=1&sort=new",
    'https://www.reddit.com/r/forhire/search/?q=composer OR "original music" OR "sound design"&restrict_sr=1&sort=new',
    "https://www.reddit.com/r/composer/search/?q=hiring OR paid OR commission OR budget&restrict_sr=1&sort=new",
)


# Last manual poll summary, surfaced on the radar (like the triage/push summaries).
_last_poll = ""


def last_poll() -> str:
    return _last_poll


def poll_now() -> str:
    """Run every configured feed (RSS + Reddit) right now and build a per-feed
    summary — so a manual test shows exactly what each feed returned (and whether
    Reddit RSS is reachable from here). Best-effort; never raises."""
    global _last_poll
    from . import signals
    parts = []
    conn = db.connect()
    try:
        feeds = configured_feeds()
        if not feeds:
            parts.append("no RSS feeds set (CHORDENTIAL_RSS_FEEDS)")
        for name, url in feeds:
            try:
                rep = signals.ingest_feed_report(conn, url, source=name)
                if rep["fetched"] == 0:
                    parts.append(f"{name}: 0 items (blocked or empty)")
                else:
                    parts.append(f"{name}: {rep['fetched']} items → {rep['landed']} new gig(s)")
            except Exception as e:  # noqa: BLE001
                parts.append(f"{name}: error {type(e).__name__}")
    finally:
        conn.close()
    if reddit_enabled():
        try:
            parts.append(f"reddit-api: {poll_reddit()} new gig(s)")
        except Exception:  # noqa: BLE001
            parts.append("reddit-api: error")
    elif discovery.scrape_enabled():
        # Otherwise this is a fully silent gap: r/gameDevClassifieds etc. never
        # get polled and nothing on the radar hints why — a real gig (e.g. a
        # "[PAID] Looking for Music Composer" post) can sit unseen indefinitely.
        if not (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")):
            parts.append("reddit-api: not configured (set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET)")
        elif os.environ.get("CHORDENTIAL_REDDIT", "1").strip().lower() in _FALSEY:
            parts.append("reddit-api: off (CHORDENTIAL_REDDIT=0)")
    _last_poll = " · ".join(parts) if parts else "nothing to poll"
    return _last_poll


def reddit_queries():
    """Subreddit search/listing URLs to poll — from CHORDENTIAL_REDDIT_QUERIES
    (comma-separated) or a curated high-intent default set."""
    raw = os.environ.get("CHORDENTIAL_REDDIT_QUERIES", "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(DEFAULT_REDDIT_QUERIES)


def reddit_enabled() -> bool:
    """On when scraping is enabled, Reddit app credentials are present, and it's
    not explicitly switched off."""
    return (
        discovery.scrape_enabled()
        and bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))
        and os.environ.get("CHORDENTIAL_REDDIT", "1").strip().lower() not in _FALSEY
    )


def poll_reddit() -> int:
    """Poll the configured subreddit searches into the signals tape. Blocking —
    runs in a worker thread; best-effort per query. Returns the new gigs landed."""
    from . import crawl_adapters, signals
    conn = db.connect()
    total = 0
    try:
        for url in reddit_queries():
            try:
                res = crawl_adapters.fetch_reddit(url)
                for rec in res.get("records", []):
                    company = str(rec.get("company") or "")
                    sid = signals.ingest_signal(
                        conn, source="reddit",
                        title=rec.get("need", ""), body=rec.get("description", ""),
                        url=rec.get("url") or "", external_ref=rec.get("url") or "",
                        strict=True,                       # is_music_gig keeps only real gigs
                        contact_handle=company if company.startswith("u/") else "",
                    )
                    if sid is not None:
                        total += 1
            except Exception:
                pass  # one bad query must never stall the loop
            time.sleep(2)  # politeness between subreddit calls
    finally:
        conn.close()
    return total


def run_cycle(batch: int = 5, delay: float = 3.0) -> int:
    """One pass: fetch a bounded batch of due targets. Blocking — runs in a worker
    thread off the event loop. Returns the number of leads/creators ingested."""
    conn = db.connect()
    found = 0
    try:
        before = (
            datetime.now(timezone.utc) - timedelta(seconds=_refetch_seconds())
        ).isoformat()
        for tgt in db.autofetch_due_targets(conn, before, limit=batch):
            _status["current"] = tgt["label"]
            try:
                found += discovery.fetch_or_refetch(conn, tgt)
            except Exception:
                pass  # one bad target must never stall the loop
            time.sleep(delay)  # politeness between fetches
    finally:
        _status["current"] = None
        conn.close()
    return found


def _ingest_ready_meetings() -> None:
    """Blocking helper (run off-loop): ingest transcript_ready meetings via the Meeting
    domain. Lazy imports avoid any import cycle with the web layer."""
    from . import meetings_service
    conn = db.connect()
    try:
        meetings_service.process_ready_meetings(conn)
    finally:
        conn.close()


async def run_loop() -> None:
    """The forever loop, started from the app lifespan. Self-heals on errors.

    Wakes on a short base tick; each periodic task gates itself by its OWN
    interval (via a monotonic timer). The heavy cycles also share one lock, so only
    one runs at a time. Their first runs are STAGGERED after boot (below) rather
    than all firing at once — the boot-time pile-up that overloaded the instance."""
    global _last_signals_mono, _last_reddit_mono, _last_autofetch_mono
    global _last_enrich_mono, _last_reenrich_mono, _last_dm_mono, _last_intel_mono
    global _last_sig_mono, _last_score_mono, _last_triage_mono
    await asyncio.sleep(20)  # let startup seeding + the first requests settle
    # Stagger first-runs: seed each timer to now-(interval-offset) so the first
    # pass of each heavy cycle comes due spread out (≈ the offset seconds from now),
    # never all at once. The shared lock makes any residual overlap a no-op.
    base = time.monotonic()

    def _stagger(interval: int, offset: int) -> float:
        # first run ≈ ``offset`` seconds from now; never pushes into the future
        # for tiny intervals (so fast/test cadences still fire promptly)
        return base - max(0, interval - offset)

    _last_enrich_mono = _stagger(_enrich_interval_seconds(), 60)
    _last_dm_mono = _stagger(_dm_interval_seconds(), 150)
    _last_intel_mono = _stagger(_intel_interval_seconds(), 240)
    _last_sig_mono = _stagger(_sig_interval_seconds(), 330)
    _last_score_mono = _stagger(_score_interval_seconds(), 420)
    _last_reenrich_mono = base                       # first re-enrich after a full interval
    while True:
        now_mono = time.monotonic()

        def due(last: float, interval: int) -> bool:
            return now_mono - last >= interval

        if signals_active() and due(_last_signals_mono, _signals_interval_seconds()):
            _last_signals_mono = now_mono
            try:
                await asyncio.to_thread(poll_feeds)
            except Exception:
                pass
        if reddit_enabled() and due(_last_reddit_mono, _signals_interval_seconds()):
            _last_reddit_mono = now_mono
            try:
                await asyncio.to_thread(poll_reddit)
            except Exception:
                pass
        # Discovery transcripts (ADR-0015): ingest any meeting a signal-then-fetch capture
        # provider left at transcript_ready. Fully gated — a NO-OP unless a provider is
        # configured, so dev/tests/prod-without-Recall never touch it.
        try:
            from .. import meetings as _M
            if _M.capture_configured():
                await asyncio.to_thread(_ingest_ready_meetings)
        except Exception:
            pass
        if autofetch_enabled() and due(_last_autofetch_mono, _interval_seconds()):
            _last_autofetch_mono = now_mono
            _status["running"] = True
            try:
                found = await asyncio.to_thread(run_cycle)
                _status["cycles"] += 1
                _status["last_found"] = found
                _status["fetched_total"] += found
                _status["last_run"] = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
            finally:
                _status["running"] = False
        # The heavy agency engines run autonomously ONLY behind the master switch
        # (default off) — otherwise their CPU-heavy batches starve this single-CPU
        # web instance. The manual buttons remain available either way.
        auto = autonomous_engines_on()
        if auto and enrich_enabled() and due(_last_enrich_mono, _enrich_interval_seconds()):
            _last_enrich_mono = now_mono
            try:
                await asyncio.to_thread(run_enrich_cycle)       # self-bookkeeping
            except Exception:
                pass
        if auto and reenrich_enabled() and due(_last_reenrich_mono, _reenrich_interval_seconds()):
            _last_reenrich_mono = now_mono
            try:
                await asyncio.to_thread(run_reenrich_cycle)     # self-bookkeeping
            except Exception:
                pass
        if auto and dm_enabled() and due(_last_dm_mono, _dm_interval_seconds()):
            _last_dm_mono = now_mono
            try:
                await asyncio.to_thread(run_dm_cycle)           # self-bookkeeping
            except Exception:
                pass
        if auto and intel_enabled() and due(_last_intel_mono, _intel_interval_seconds()):
            _last_intel_mono = now_mono
            try:
                await asyncio.to_thread(run_intel_cycle)        # self-bookkeeping
            except Exception:
                pass
        if auto and signals_engine_enabled() and due(_last_sig_mono, _sig_interval_seconds()):
            _last_sig_mono = now_mono
            try:
                await asyncio.to_thread(run_signals_cycle)      # self-bookkeeping
            except Exception:
                pass
        if auto and score_enabled() and due(_last_score_mono, _score_interval_seconds()):
            _last_score_mono = now_mono
            try:
                await asyncio.to_thread(run_score_cycle)        # self-bookkeeping
            except Exception:
                pass
        if triage_enabled() and due(_last_triage_mono, _triage_interval_seconds()):
            _last_triage_mono = now_mono
            try:
                created = await asyncio.to_thread(run_triage_cycle)
                _triage_status["cycles"] += 1
                _triage_status["last_created"] = created
                _triage_status["total_created"] += created
                _triage_status["last_run"] = datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
        await asyncio.sleep(_base_tick_seconds())
