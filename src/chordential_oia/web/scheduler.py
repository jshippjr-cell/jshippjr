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
import os
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


def autofetch_enabled() -> bool:
    """On only when scraping is enabled AND the scheduler isn't explicitly off."""
    return discovery.scrape_enabled() and (
        os.environ.get("CHORDENTIAL_AUTOFETCH", "1").strip().lower() not in _FALSEY
    )


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


async def run_loop() -> None:
    """The forever loop, started from the app lifespan. Self-heals on errors."""
    await asyncio.sleep(15)  # let startup seeding settle before the first pass
    while True:
        if signals_active():                 # Signal Engine: RSS gigs + indicators
            try:
                await asyncio.to_thread(poll_feeds)
            except Exception:
                pass
        if autofetch_enabled():
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
        await asyncio.sleep(_interval_seconds())
