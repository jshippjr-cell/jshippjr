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
