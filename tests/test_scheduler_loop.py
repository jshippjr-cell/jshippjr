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
    try:
        assert sch.start_manual_enrich(5) is True and started.get("yes")
    finally:
        sch._enrich_status["running"] = False        # don't leak the guard flag


def test_full_pipeline_runs_all_layers_in_order(tmp_path, monkeypatch):
    # "Build full profile" must chain enrich → decision makers → intelligence →
    # signals → score for one agency, in order, in one killable worker process.
    from chordential_oia.web import (db as dbm, enrichment as en,
                                      decision_makers as dm, _enrich_worker)
    db_path = str(tmp_path / "pipe.db")
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.setenv("CHORDENTIAL_DB", db_path)
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)

    conn = dbm.connect(db_path)
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

    # drive the worker synchronously in-process (don't spawn a real subprocess) to
    # assert the chained outcome — the worker opens its own connection to the same DB.
    monkeypatch.setattr(sch, "_run_worker",
                        lambda spec, timeout: _enrich_worker.run(spec))
    assert sch.start_agency_pipeline(aid) is True

    assert dbm.get_agency_enrichment(conn, aid)["status"] == "complete"   # enriched
    assert dbm.count_decision_makers(conn, aid) >= 1                      # decision makers
    assert dbm.get_agency_intel(conn, aid).get("status") == "complete"   # intelligence
    assert dbm.get_agency_score(conn, aid).get("score") is not None       # scored


def test_manual_enrich_guard_self_heals_when_stale():
    # The "a batch is running" guard must never stick: once the flag is older than
    # the worker's own timeout, it's stale and a new pass is allowed again (so the
    # button can't end up permanently disabled).
    import time as _time
    try:
        sch._enrich_status["running"] = True
        sch._enrich_status["running_since"] = _time.monotonic() - 10_000
        sch._enrich_status["running_ttl"] = 600.0
        assert sch._manual_enrich_running() is False          # stale → auto-cleared
        assert sch._enrich_status["running"] is False

        sch._enrich_status["running"] = True                  # a fresh pass still counts
        sch._enrich_status["running_since"] = _time.monotonic()
        sch._enrich_status["running_ttl"] = 600.0
        assert sch._manual_enrich_running() is True
    finally:
        sch._enrich_status["running"] = False


def test_enrich_one_supervised_marks_error_on_timeout(tmp_path, monkeypatch):
    # The crux of resilient batch enrichment: a worker that hangs on a hostile page
    # is killed AND the agency is marked 'error', so the batch skips it next time
    # instead of re-picking the same page forever.
    import subprocess as sp
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "e.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "x", "company": "X",
                                  "website": "https://x.example"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    conn.commit()

    class HangProc:
        def wait(self, timeout=None):
            raise sp.TimeoutExpired("w", timeout)

        def kill(self):
            pass

    monkeypatch.setattr(sch.subprocess, "Popen", lambda *a, **k: HangProc())
    assert sch._enrich_one_supervised(conn, aid, timeout=1) is False
    st = dbm.get_agency_enrichment(conn, aid)
    assert st and st.get("status") == "error"            # marked → batch will skip it
    assert dbm.count_needing_enrichment(conn) == 0       # no longer "awaiting"


def test_enrich_one_supervised_marks_error_on_crash(tmp_path, monkeypatch):
    # A worker that CRASHES (e.g. an unhandled exception on a malformed page) must
    # be treated the same as a hang: marked 'error' so the batch advances past it.
    # Before this fix only a timeout cleared the queue — a crashing agency stayed
    # at the front forever and every pass re-picked (and re-crashed on) it,
    # completing 0 no matter how many times "Enrich now" was pressed.
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "e2.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "x", "company": "X",
                                  "website": "https://x.example"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    conn.commit()

    class CrashProc:
        def wait(self, timeout=None):
            return 1                          # non-zero exit, no timeout

        def kill(self):
            pass

    monkeypatch.setattr(sch.subprocess, "Popen", lambda *a, **k: CrashProc())
    assert sch._enrich_one_supervised(conn, aid, timeout=1) is False
    st = dbm.get_agency_enrichment(conn, aid)
    assert st and st.get("status") == "error"            # marked → batch will skip it
    assert dbm.count_needing_enrichment(conn) == 0       # no longer "awaiting"


def test_supervised_batch_advances_through_agencies(tmp_path, monkeypatch):
    # The batch must make forward progress: enrich N, leaving the rest, and record
    # how many completed (the "click Enrich, count drops" behaviour).
    from chordential_oia.web import db as dbm
    db_path = str(tmp_path / "b.db")
    monkeypatch.setenv("CHORDENTIAL_DB", db_path)
    conn = dbm.connect(db_path)
    dbm.init_db(conn)
    for i in range(4):
        dbm.upsert_agency(conn, "s", {"dedup_key": f"a{i}", "company": f"A{i}",
                                      "website": f"https://a{i}.example"})
    conn.commit()

    def fake_one(conn, action, aid, timeout, *, reset=False, label="enrich",
                 on_timeout=None):                        # stand in for the worker
        dbm.save_agency_enrichment(conn, aid, {"status": "complete", "steps_done": [],
                                               "links": [], "profile": {}})
        conn.commit()
        return True

    monkeypatch.setattr(sch, "_run_one_supervised", fake_one)
    monkeypatch.setattr(sch, "_enrich_delay_seconds", lambda: 0)
    monkeypatch.setattr(sch.threading, "Thread",
                        lambda target=None, **k: type("T", (), {"start": lambda self: target()})())
    sch._enrich_batch_supervised(3)
    assert dbm.count_needing_enrichment(dbm.connect(db_path)) == 1   # 3 of 4 done
    assert sch._enrich_status["last_completed"] == 3
    assert sch._enrich_status["batch_done"] == 3                     # live progress tracked


def test_dm_error_status_drops_out_of_the_queue(tmp_path):
    # A timed-out decision-maker discovery is marked dm-'error'; that MUST exclude it
    # from the needing-queue, or the autonomous cycle would re-pick the same hostile
    # page every pass and never advance.
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "d.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "x", "company": "X",
                                  "website": "https://x.example"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    conn.commit()
    assert dbm.count_needing_decision_makers(conn) == 1
    dbm.save_agency_dm(conn, aid, {"status": "error", "found": 0, "total": 0})
    conn.commit()
    assert dbm.count_needing_decision_makers(conn) == 0
    assert dbm.agencies_needing_decision_makers(conn) == []


def test_worker_hung_job_is_killed_not_awaited_forever(monkeypatch):
    # The whole point of out-of-process enrichment: a runaway parse that would
    # otherwise freeze the web server (silent logs, wheel of death) is reaped by the
    # watchdog. Simulate a process whose wait() times out and assert kill() fires.
    import subprocess as sp
    killed = {"n": 0}

    class FakeProc:
        def wait(self, timeout=None):
            raise sp.TimeoutExpired("worker", timeout)

        def kill(self):
            killed["n"] += 1

    monkeypatch.setattr(sch.subprocess, "Popen", lambda *a, **k: FakeProc())
    # run the watchdog body synchronously instead of on a real thread
    monkeypatch.setattr(sch.threading, "Thread",
                        lambda target=None, **k: type("T", (), {"start": lambda self: target()})())
    sch._run_worker({"action": "enrich", "agency_id": 1}, timeout=1)
    assert killed["n"] == 1                       # hung worker killed, not hung on forever


def test_worker_normal_job_is_not_killed(monkeypatch):
    killed = {"n": 0}

    class OkProc:
        def wait(self, timeout=None):
            return 0

        def kill(self):
            killed["n"] += 1

    monkeypatch.setattr(sch.subprocess, "Popen", lambda *a, **k: OkProc())
    monkeypatch.setattr(sch.threading, "Thread",
                        lambda target=None, **k: type("T", (), {"start": lambda self: target()})())
    sch._run_worker({"action": "enrich", "agency_id": 1}, timeout=99)
    assert killed["n"] == 0                       # a job that finishes is never killed


def test_worker_runs_as_a_real_subprocess(tmp_path):
    # End-to-end: the `python -m chordential_oia.web._enrich_worker` entrypoint
    # actually starts, connects to CHORDENTIAL_DB, does work, commits, and exits 0.
    # Uses a website-less agency so no network is needed.
    import json
    import os
    import subprocess
    import sys
    from chordential_oia.web import db as dbm

    db_path = str(tmp_path / "w.db")
    conn = dbm.connect(db_path)
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "no.site", "company": "NoSite",
                                  "website": ""})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    conn.commit()

    env = dict(os.environ, CHORDENTIAL_DB=db_path, CHORDENTIAL_ENABLE_SCRAPE="1")
    spec = json.dumps({"action": "enrich", "agency_id": aid})
    r = subprocess.run([sys.executable, "-m", "chordential_oia.web._enrich_worker", spec],
                       env=env, timeout=60, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    state = dbm.get_agency_enrichment(dbm.connect(db_path), aid)
    assert state and state.get("status") in ("error", "blocked")   # it ran and committed


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
