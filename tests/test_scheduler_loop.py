"""The background loop's pacing: each periodic task gates itself by its OWN
interval, so a fast task (enrichment) fires on its own cadence and isn't throttled
by a slow one (autofetch). Regression test for "auto-enrichment only moved when I
clicked" — the shared 15-minute sleep used to gate everything.
"""

import asyncio

import pytest

from chordential_oia.web import scheduler as sch


def test_interval_helpers_read_env_and_default(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_LOOP_TICK", raising=False)
    assert sch._base_tick_seconds() == 30
    monkeypatch.setenv("CHORDENTIAL_LOOP_TICK", "5")     # clamped up to the floor
    assert sch._base_tick_seconds() == 10
    monkeypatch.setenv("CHORDENTIAL_AUTOENRICH_INTERVAL", "120")
    assert sch._enrich_interval_seconds() == 120


def test_loop_fires_enrichment_on_its_own_each_tick(monkeypatch):
    # Only enrichment enabled; with a zero interval it must run on every base tick
    # (i.e. without anyone clicking), proving the per-task gate works.
    calls = {"enrich": 0}
    monkeypatch.setattr(sch, "autonomous_engines_on", lambda: True)
    monkeypatch.setattr(sch, "enrich_enabled", lambda: True)
    for off in ("dm_enabled", "autofetch_enabled", "signals_active",
                "reddit_enabled", "triage_enabled"):
        monkeypatch.setattr(sch, off, lambda: False)
    monkeypatch.setattr(sch, "_enrich_interval_seconds", lambda: 0)
    monkeypatch.setattr(sch, "run_enrich_cycle",
                        lambda: calls.__setitem__("enrich", calls["enrich"] + 1) or 0)

    real_sleep = asyncio.sleep
    ticks = {"n": 0}

    async def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] > 3:                 # let a few base ticks pass, then stop
            raise asyncio.CancelledError
        await real_sleep(0)
    monkeypatch.setattr(sch.asyncio, "sleep", fake_sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await sch.run_loop()
    asyncio.run(run())

    assert calls["enrich"] >= 2            # fired on its own across multiple ticks


def test_autonomy_off_by_default_so_loop_skips_heavy_cycles(monkeypatch):
    # Default OFF: the heavy engines must NOT run autonomously (the CPU pile-up
    # that 502'd the live instance). enrich_enabled() is True, but with the master
    # switch off the loop never fires it.
    monkeypatch.delenv("CHORDENTIAL_AUTONOMOUS", raising=False)
    assert sch.autonomous_engines_on() is False
    calls = {"enrich": 0}
    monkeypatch.setattr(sch, "enrich_enabled", lambda: True)
    for off in ("dm_enabled", "autofetch_enabled", "signals_active",
                "reddit_enabled", "triage_enabled"):
        monkeypatch.setattr(sch, off, lambda: False)
    monkeypatch.setattr(sch, "_enrich_interval_seconds", lambda: 0)
    monkeypatch.setattr(sch, "run_enrich_cycle",
                        lambda: calls.__setitem__("enrich", calls["enrich"] + 1) or 0)
    real_sleep = asyncio.sleep
    ticks = {"n": 0}

    async def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] > 3:
            raise asyncio.CancelledError
        await real_sleep(0)
    monkeypatch.setattr(sch.asyncio, "sleep", fake_sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await sch.run_loop()
    asyncio.run(run())
    assert calls["enrich"] == 0            # never fired autonomously


def test_manual_start_works_even_when_autonomy_off(monkeypatch):
    # Manual buttons must keep working with autonomy off — they're user-initiated.
    monkeypatch.delenv("CHORDENTIAL_AUTONOMOUS", raising=False)
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)
    sch._enrich_status["running"] = False
    started = {}
    monkeypatch.setattr(sch.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: started.setdefault("yes", True)})())
    assert sch.start_manual_enrich(5) is True and started.get("yes")


def test_full_pipeline_runs_all_layers_in_order(tmp_path, monkeypatch):
    # "Build full profile" must chain enrich → decision makers → intelligence →
    # signals → score for one agency, in order, in one background job.
    from chordential_oia.web import (db as dbm, enrichment as en,
                                      decision_makers as dm)
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)

    conn = dbm.connect(str(tmp_path / "pipe.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "acme.example", "company": "Acme",
                                  "website": "https://acme.example"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    conn.commit()

    SITE = {"https://acme.example/": "<html><body><nav>"
            "<a href='/what-we-do'>What We Do</a><a href='/team'>Team</a></nav></body></html>",
            "https://acme.example/what-we-do": "<body><h2>What We Do</h2><ul>"
            "<li>Brand Films</li></ul></body>",
            "https://acme.example/team": "<body><h2>Leadership</h2><div><h3>Dana Reed</h3>"
            "<p>Executive Producer</p></div></body>"}
    fake_fetch = (lambda u, timeout=15.0:
                  ((SITE.get(u) or SITE.get(u + "/") or ""),
                   (u in SITE or u + "/" in SITE)))
    # Both enrichment and decision_makers hold their OWN binding of _default_fetch
    # (decision_makers did `from .enrichment import _default_fetch`), so the live-
    # network seam must be faked on both modules or the DM step hits the wire.
    monkeypatch.setattr(en, "_default_fetch", fake_fetch)
    monkeypatch.setattr(dm, "_default_fetch", fake_fetch)

    # run synchronously (don't spawn a thread) to assert the chained outcome
    monkeypatch.setattr(sch, "_run_in_background", lambda fn: fn(conn))
    assert sch.start_agency_pipeline(aid) is True

    assert dbm.get_agency_enrichment(conn, aid)["status"] == "complete"   # enriched
    assert dbm.count_decision_makers(conn, aid) >= 1                      # decision makers
    assert dbm.get_agency_intel(conn, aid).get("status") == "complete"   # intelligence
    assert dbm.get_agency_score(conn, aid).get("score") is not None       # scored


def test_only_one_heavy_cycle_runs_at_a_time():
    # The shared heavy lock prevents several batches hammering a small instance at
    # once (the overload that hung the live service): if one heavy job holds the
    # lock, every other heavy cycle is a no-op.
    sch._heavy_lock.acquire()
    try:
        assert sch.run_enrich_cycle() == 0
        assert sch.run_dm_cycle() == 0
        assert sch.run_intel_cycle() == 0
        assert sch.run_signals_cycle() == 0
        assert sch.run_score_cycle() == 0
        assert sch.run_reenrich_cycle() == 0
    finally:
        sch._heavy_lock.release()


def test_a_slow_task_does_not_block_a_fast_one(monkeypatch):
    # autofetch on a long interval must not stop enrichment from firing each tick.
    fired = {"enrich": 0, "autofetch": 0}
    monkeypatch.setattr(sch, "autonomous_engines_on", lambda: True)
    monkeypatch.setattr(sch, "enrich_enabled", lambda: True)
    monkeypatch.setattr(sch, "autofetch_enabled", lambda: True)
    for off in ("dm_enabled", "signals_active", "reddit_enabled", "triage_enabled"):
        monkeypatch.setattr(sch, off, lambda: False)
    monkeypatch.setattr(sch, "_enrich_interval_seconds", lambda: 0)
    monkeypatch.setattr(sch, "_interval_seconds", lambda: 10_000)   # autofetch ~never
    monkeypatch.setattr(sch, "run_enrich_cycle",
                        lambda: fired.__setitem__("enrich", fired["enrich"] + 1) or 0)
    monkeypatch.setattr(sch, "run_cycle",
                        lambda: fired.__setitem__("autofetch", fired["autofetch"] + 1) or 0)

    real_sleep = asyncio.sleep
    ticks = {"n": 0}

    async def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] > 3:
            raise asyncio.CancelledError
        await real_sleep(0)
    monkeypatch.setattr(sch.asyncio, "sleep", fake_sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await sch.run_loop()
    asyncio.run(run())

    # autofetch fired once (its interval elapses on the first tick from 0), then
    # never again within the window — but enrichment kept firing regardless.
    assert fired["enrich"] >= 2
    assert fired["autofetch"] <= 1
