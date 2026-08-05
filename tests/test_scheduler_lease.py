"""One scheduler at a time, across instances.

Every coordination primitive in `scheduler.py` is in-process — a `threading.Lock`
and module-level monotonic timers — on the documented assumption of a single
instance. The blue-green cutover breaks that assumption **deliberately**: for the
minutes the old and new services overlap, both run `run_loop`, so outreach sends
twice, meeting bots are polled twice, and two enrichment batches contend for one
CPU. None of it raises. A second copy of an email is not an error anywhere in this
system, which is exactly why it needs a test rather than an eye.

The primitive is a lease row, not `pg_try_advisory_lock`. Advisory locks are held
by a SESSION, and this codebase opens a connection per call and closes it, so such
a lock would release microseconds after it was taken; holding one would need a
dedicated long-lived connection and would still leave SQLite — what production runs
today, and every test here — with nothing.
"""

import asyncio

import pytest

from chordential_oia.web import db
from chordential_oia.web import scheduler as sch


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "lease.db"))
    import importlib
    importlib.reload(db)
    c = db.connect()
    db.init_db(c)
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# The lease itself
# --------------------------------------------------------------------------- #
def test_two_instances_cannot_both_hold_it(conn):
    """The whole point. Both processes are healthy, both want it, one gets it."""
    assert db.acquire_lease(conn, "scheduler", "instance-A", 90) is True
    assert db.acquire_lease(conn, "scheduler", "instance-B", 90) is False
    assert db.lease_holder(conn, "scheduler")["owner"] == "instance-A"


def test_the_holder_renews_rather_than_locking_itself_out(conn):
    """Renewal runs every tick; a holder that could not re-acquire its own lease
    would stop the engines after one TTL and never restart them."""
    assert db.acquire_lease(conn, "scheduler", "instance-A", 90) is True
    assert db.acquire_lease(conn, "scheduler", "instance-A", 90) is True
    assert db.acquire_lease(conn, "scheduler", "instance-A", 90) is True


def test_an_expired_lease_is_taken_over_without_intervention(conn):
    """An instance that is SIGKILLed cannot release anything. If expiry did not
    hand the engines on, one hard crash would stop them until someone noticed —
    and 'the engines quietly stopped' is not a thing anyone notices."""
    assert db.acquire_lease(conn, "scheduler", "dead-instance", 90) is True
    conn.execute("UPDATE scheduler_lease SET expires_at = ? WHERE name = ?",
                 ("2000-01-01T00:00:00Z", "scheduler"))
    conn.commit()
    assert db.acquire_lease(conn, "scheduler", "new-instance", 90) is True
    assert db.lease_holder(conn, "scheduler")["owner"] == "new-instance"


def test_releasing_hands_over_in_seconds_not_a_ttl(conn):
    """Shutdown releases, so the incoming instance starts working immediately
    instead of spending the whole handover with the engines stopped."""
    assert db.acquire_lease(conn, "scheduler", "outgoing", 90) is True
    assert db.acquire_lease(conn, "scheduler", "incoming", 90) is False
    db.release_lease(conn, "scheduler", "outgoing")
    assert db.lease_holder(conn, "scheduler") is None
    assert db.acquire_lease(conn, "scheduler", "incoming", 90) is True


def test_only_the_holder_can_release(conn):
    """A draining instance must not be able to release a lease it already lost —
    that would hand the engines to a third party mid-cycle."""
    db.acquire_lease(conn, "scheduler", "holder", 90)
    db.release_lease(conn, "scheduler", "someone-else")
    assert db.lease_holder(conn, "scheduler")["owner"] == "holder"


def test_the_holder_is_visible(conn):
    """"This instance is not running the engines" has to be a state you can SEE.
    An invisible one is how a silent stop goes unnoticed for a week."""
    db.acquire_lease(conn, "scheduler", "instance-A", 90)
    holder = db.lease_holder(conn, "scheduler")
    assert holder["owner"] == "instance-A"
    assert holder["expired"] is False
    assert holder["acquired_at"]


def test_expiry_is_compared_as_a_fixed_width_timestamp(conn):
    """The comparison is string-wise in SQL, so the format must be fixed width.
    `datetime.isoformat()` drops the microseconds when they are exactly zero, and a
    lease written on that one-in-a-million tick would sort wrongly against every
    other — an expiry that never expires, or expires at once."""
    db.acquire_lease(conn, "scheduler", "instance-A", 90)
    stamp = conn.execute(
        "SELECT expires_at FROM scheduler_lease").fetchone()["expires_at"]
    assert len(stamp) == 20 and stamp.endswith("Z"), stamp


# --------------------------------------------------------------------------- #
# The loop honours it
# --------------------------------------------------------------------------- #
def _ticking_loop(monkeypatch, ticks=4):
    """Run `run_loop` for a few base ticks, then cancel it."""
    real_sleep = asyncio.sleep
    n = {"t": 0}

    async def fake_sleep(_seconds):
        n["t"] += 1
        if n["t"] > ticks:
            raise asyncio.CancelledError
        await real_sleep(0)
    monkeypatch.setattr(sch.asyncio, "sleep", fake_sleep)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await sch.run_loop()
    asyncio.run(run())


def _only_enrichment(monkeypatch, calls):
    monkeypatch.setattr(sch, "autonomous_engines_on", lambda: True)
    monkeypatch.setattr(sch, "enrich_enabled", lambda: True)
    for off in ("dm_enabled", "autofetch_enabled", "signals_active",
                "reddit_enabled", "triage_enabled", "reenrich_enabled",
                "intel_enabled", "signals_engine_enabled", "score_enabled"):
        monkeypatch.setattr(sch, off, lambda: False)
    monkeypatch.setattr(sch, "_enrich_interval_seconds", lambda: 0)
    monkeypatch.setattr(sch, "run_enrich_cycle",
                        lambda: calls.__setitem__("n", calls["n"] + 1) or 0)


def test_the_loop_runs_nothing_without_the_lease(monkeypatch):
    """The instance that loses the election does no work at all — not a reduced
    amount, none. Anything less and the cutover still sends everything twice."""
    calls = {"n": 0}
    _only_enrichment(monkeypatch, calls)
    monkeypatch.setattr(sch, "_claim_lease", lambda: False)
    _ticking_loop(monkeypatch)
    assert calls["n"] == 0


def test_the_loop_runs_when_it_holds_the_lease(monkeypatch):
    """The control. Without this the test above passes on a loop that is simply
    broken, which is the failure mode of every gate ever added to a scheduler."""
    calls = {"n": 0}
    _only_enrichment(monkeypatch, calls)
    monkeypatch.setattr(sch, "_claim_lease", lambda: True)
    _ticking_loop(monkeypatch)
    assert calls["n"] >= 2


def test_a_database_it_cannot_reach_means_do_not_run(monkeypatch):
    """The safe direction. A lease that cannot be checked is not a lease held: two
    instances both running everything is worse than neither running for one tick,
    and the DB being unreachable is not a moment to start sending outreach."""
    def boom(*_a, **_k):
        raise RuntimeError("no database")
    monkeypatch.setattr(sch.db, "connect", boom)
    monkeypatch.setenv("CHORDENTIAL_SCHEDULER_LEASE", "1")
    assert sch._claim_lease() is False


def test_the_lease_can_be_switched_off(monkeypatch):
    """A kill switch, on the pattern every other seam here uses — so a lease bug
    can never be the thing that stops the engines with no way to override it."""
    monkeypatch.setenv("CHORDENTIAL_SCHEDULER_LEASE", "0")
    assert sch.lease_enabled() is False
    assert sch._claim_lease() is True
    assert sch.lease_status()["enabled"] is False
