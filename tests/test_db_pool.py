"""Connections are borrowed, not rebuilt.

`connect()` is called **254 times across the web layer** — one per handler, several
per page — and each is closed immediately. On SQLite that is a file open and genuinely
cheap. On Postgres it is a TCP connect, a TLS handshake and an auth round trip to a
host across the network, before a single row is read. The cutover turns the cheapest
operation in the system into one of the most expensive without changing one line of
calling code.

Measured against a real Postgres 16 over loopback, 25 connect/close cycles:

    pooling OFF   25 distinct server backends   3.95 ms per connect
    pooling ON     2 distinct server backends   0.38 ms per connect

Loopback with no TLS is the *friendliest* possible case; Render to a managed
Postgres is another host with a handshake.

The pool sits BEHIND `connect()` so no call site changes, and SQLite is untouched —
its connections are cheap and sharing one across threads is a hazard, not a win.

The speed is the easy part. What these tests are really for is the rest: a borrowed
connection must not carry another request's open transaction, an exhausted pool must
not become a 500, and a missing `psycopg_pool` must degrade to today's behaviour and
*say so* — this repo has already lost uploads to a declared dependency production
never installed (ADR-0043, amended).
"""

import importlib
import os
import threading

import pytest

from chordential_oia.web import db as db_mod

PG_DSN = os.environ.get("CHORDENTIAL_TEST_PG", "").strip()
live = pytest.mark.skipif(not PG_DSN, reason="set CHORDENTIAL_TEST_PG to a Postgres DSN")


def _fresh_db() -> str:
    """A throwaway database on the test server, so pool state cannot leak between
    tests through a shared DSN."""
    import uuid
    import psycopg
    name = "pool_%s" % uuid.uuid4().hex[:10]
    with psycopg.connect(PG_DSN, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = PG_DSN.rpartition("/")
    return f"{base}/{name}"


# --------------------------------------------------------------------------- #
# Backend-agnostic: SQLite must be entirely unaffected
# --------------------------------------------------------------------------- #
def test_sqlite_is_left_alone(tmp_path, monkeypatch):
    """The whole risk budget of this change. SQLite connections are cheap, and a
    pooled one shared across threads is a hazard rather than an optimisation — so on
    SQLite there is no pool and `connect()` behaves exactly as it always has."""
    import sqlite3
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "x.db"))
    importlib.reload(db_mod)
    status = db_mod.pool_status()
    assert status["backend"] == "sqlite"
    assert status["applicable"] is False
    conn = db_mod.connect(str(tmp_path / "x.db"))
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_the_pool_can_be_switched_off(monkeypatch):
    """A kill switch, on the pattern every other seam here uses, so a pool bug can
    never be the thing that takes the database down with no way to override it."""
    monkeypatch.setenv("CHORDENTIAL_DB_POOL", "0")
    assert db_mod.pool_enabled() is False
    monkeypatch.setenv("CHORDENTIAL_DB_POOL", "1")
    assert db_mod.pool_enabled() is True


def test_pool_bounds_come_from_the_environment(monkeypatch):
    """Render's managed Postgres caps connections and the scheduler shares this pool
    with the web workers, so the ceiling has to be settable without a deploy."""
    monkeypatch.setenv("CHORDENTIAL_DB_POOL_MIN", "2")
    monkeypatch.setenv("CHORDENTIAL_DB_POOL_MAX", "7")
    assert db_mod._pool_size() == (2, 7)
    monkeypatch.setenv("CHORDENTIAL_DB_POOL_MAX", "not-a-number")
    assert db_mod._pool_size()[1] == 10, "a bad value must fall back, not crash the app"


def test_status_reports_a_missing_pool_package_honestly(monkeypatch):
    """The failure this repo has already paid for: a declared dependency that
    production never installed, while the boot line announced the feature was on.
    `available` must reflect the package, not the intention."""
    monkeypatch.setenv("CHORDENTIAL_DB", "postgresql://u@h/d")
    monkeypatch.setattr(db_mod, "_POOL_SPEC", False)
    status = db_mod.pool_status()
    assert status["applicable"] is True
    assert status["available"] is False
    assert status["active"] is False, "not installed must never read as active"


# --------------------------------------------------------------------------- #
# Live: the behaviour that only a real server can show
# --------------------------------------------------------------------------- #
@live
def test_connections_are_reused_not_rebuilt(monkeypatch):
    """Asked of the SERVER, not of our own bookkeeping: `pg_backend_pid()` is the
    process actually handling the query, so a pool that quietly reconnects every time
    cannot pass this by claiming otherwise."""
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    try:
        pids = set()
        for _ in range(20):
            c = db_mod.connect(dsn)
            pids.add(c.execute("SELECT pg_backend_pid() AS p").fetchone()["p"])
            c.close()
        assert len(pids) <= 3, f"20 calls used {len(pids)} server backends — not pooled"
        assert db_mod.pool_status(dsn)["active"] is True
    finally:
        db_mod.close_pool()


@live
def test_a_borrowed_connection_never_carries_the_last_ones_transaction(monkeypatch):
    """The correctness question that matters more than the speed.

    Today `close()` on an uncommitted connection discards the work — every caller
    commits explicitly. A pooled connection must reach its next borrower in exactly
    that state. If it were handed on mid-transaction, the next request would inherit
    an open snapshot and its locks, and would see writes that were never committed.
    """
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    try:
        c = db_mod.connect(dsn)
        db_mod.init_db(c)
        c.close()

        first = db_mod.connect(dsn)
        first.execute("INSERT INTO opportunities (client, need) VALUES (?, ?)",
                      ("Uncommitted Co", "never saved"))
        first.close()                       # no commit — exactly like an aborted request

        second = db_mod.connect(dsn)
        rows = second.execute(
            "SELECT COUNT(*) AS n FROM opportunities WHERE client = ?",
            ("Uncommitted Co",)).fetchone()["n"]
        # And the connection must be immediately usable, not stuck in a failed or
        # open transaction inherited from the borrower before it.
        assert second.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        second.close()
        assert rows == 0, "an uncommitted write survived into the next borrower"
    finally:
        db_mod.close_pool()


@live
def test_committed_work_still_persists(monkeypatch):
    """The control. A pool that rolled everything back would pass the test above
    and lose every write in the product."""
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    try:
        c = db_mod.connect(dsn)
        db_mod.init_db(c)
        c.close()
        w = db_mod.connect(dsn)
        w.execute("INSERT INTO opportunities (client, need) VALUES (?, ?)",
                  ("Committed Co", "saved"))
        w.commit()
        w.close()
        r = db_mod.connect(dsn)
        assert r.execute("SELECT COUNT(*) AS n FROM opportunities WHERE client = ?",
                         ("Committed Co",)).fetchone()["n"] == 1
        r.close()
    finally:
        db_mod.close_pool()


@live
def test_many_threads_can_borrow_at_once(monkeypatch):
    """Sync handlers run in a threadpool and the scheduler hands heavy work to
    `asyncio.to_thread`, so the pool is used concurrently by construction. A pool
    that is not thread-safe fails under load, which is the worst time to find out."""
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    try:
        c = db_mod.connect(dsn)
        db_mod.init_db(c)
        c.close()
        errors, seen = [], []

        def worker():
            try:
                for _ in range(10):
                    conn = db_mod.connect(dsn)
                    seen.append(conn.execute("SELECT 1 AS ok").fetchone()["ok"])
                    conn.close()
            except Exception as e:                       # noqa: BLE001
                errors.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)
        assert errors == [], errors
        assert len(seen) == 80
    finally:
        db_mod.close_pool()


@live
def test_a_wedged_pool_degrades_to_a_direct_connection(monkeypatch):
    """A pool that cannot hand out a connection must not become a 500 on the client's
    review portal. It degrades to exactly the behaviour of the day before it existed."""
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    try:
        class Wedged:
            def getconn(self, *a, **k):
                raise RuntimeError("pool exhausted")
        monkeypatch.setattr(db_mod, "_get_pool", lambda url: Wedged())
        conn = db_mod.connect(dsn)
        assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        conn.close()
    finally:
        db_mod.close_pool()


@live
def test_closing_the_pool_releases_the_servers_connections(monkeypatch):
    """A draining instance must let go, or it holds a slice of a capped connection
    limit that the incoming instance is at that moment trying to claim — which is
    precisely the overlap a blue-green cutover creates on purpose."""
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    import psycopg

    def backends():
        name = dsn.rsplit("/", 1)[1]
        with psycopg.connect(PG_DSN, autocommit=True) as c:
            return c.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (name,)
            ).fetchone()[0]

    conns = [db_mod.connect(dsn) for _ in range(4)]
    for c in conns:
        c.execute("SELECT 1")
    for c in conns:
        c.close()
    assert backends() >= 1
    db_mod.close_pool()
    assert backends() == 0, "the pool kept server connections open after close_pool()"


@live
def test_a_script_using_the_pool_exits_without_a_traceback(monkeypatch, tmp_path):
    """Observed on the live cutover, in the Render shell, immediately after
    `Migration complete.`:

        Exception ignored while calling deallocator <ConnectionPool.__del__ …>
        PythonFinalizationError: cannot join thread at interpreter shutdown

    Nothing was wrong and nothing was lost — `__del__` ran during interpreter
    finalization and tried to join the pool's worker thread, which Python 3.14
    refuses. But it printed a stack trace at the one moment an operator is deciding
    whether to trust a migration they cannot undo, and that is a real cost even
    though the bytes were fine. `atexit` closes the pool while joining is still
    legal, so `__del__` has nothing left to do.

    Asserted on a SUBPROCESS, because the failure only exists at interpreter
    shutdown and an in-process test cannot see it.
    """
    import subprocess
    import sys
    import textwrap

    dsn = _fresh_db()
    script = textwrap.dedent(f"""
        import os
        os.environ["CHORDENTIAL_DB"] = {dsn!r}
        from chordential_oia.web import db
        c = db.connect({dsn!r}); db.init_db(c); c.close()
        print("done")
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert "done" in r.stdout
    assert r.stderr.strip() == "", f"a script using the pool printed to stderr:\n{r.stderr}"
