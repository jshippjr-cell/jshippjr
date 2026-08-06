"""The dashboard asked the same questions over and over.

It composes several cards from the same rows, and each card was built by an aggregator
that fetched them for itself. `next_action.compute` and `queue.compute_queue` are each
correct alone, and each re-reads what the handler already read. Measured on the seeded
demo — FOUR projects — one render cost **71 queries**, of which `SELECT delivery_json
FROM projects WHERE id = ?` ran nine times and the invoice lookup once per project.

On SQLite over a local file that was invisible. On Postgres every one is a network round
trip, and the count grows with the number of projects:

    projects   batched   unbatched   saved
           4        51          71     28%
          12        99         215     53%
          38       255         683     62%

Two mechanisms, both scoped to one request and thrown away with it:

* a **memo** that answers a repeated SELECT from memory, and is invalidated by any
  write, so a handler that reads-writes-reads cannot be served a stale row;
* **priming**, which fetches in two batched queries what the loop would otherwise ask
  twice per project, and hands the answers to the memo before the loop runs — so the
  per-row code is untouched and simply never reaches the database.

The point of the second is that it leaves `next_action`, `compute_queue` and every
future caller alone. Threading batched data through all of them would be a much larger
change with the same result and more ways to be wrong.
"""

import collections
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import db as db_mod  # noqa: E402


@pytest.fixture()
def app_and_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app):
        pass                       # the lifespan is what builds and seeds the schema
    return app_mod


def _counting(db_module):
    """Count statements that actually reach the database, not calls to the memo."""
    n = collections.Counter()
    real = db_module.connect

    class C:
        def __init__(self, c): self._c = c
        def __getattr__(self, k): return getattr(self._c, k)
        def execute(self, sql, params=()):
            n["db"] += 1
            return self._c.execute(sql, params)

    db_module.connect = lambda *a, **k: C(real(*a, **k))
    return n, real


# --------------------------------------------------------------------------- #
# The memo
# --------------------------------------------------------------------------- #
def test_a_repeated_select_is_answered_from_memory(app_and_db):
    conn = db_mod.connect()
    memo = db_mod.read_memo(conn)
    a = memo.execute("SELECT id FROM opportunities ORDER BY id").fetchall()
    b = memo.execute("SELECT id FROM opportunities ORDER BY id").fetchall()
    assert [dict(r) for r in a] == [dict(r) for r in b]
    assert memo.hits == 1 and memo.misses == 1
    conn.close()


def test_a_memoised_cursor_can_be_read_twice(app_and_db):
    """A real cursor is consumed by the first `fetchall`. Handing the same exhausted
    cursor to the second caller would return nothing at all — which is worse than the
    duplicate query, because it is silently wrong."""
    conn = db_mod.connect()
    memo = db_mod.read_memo(conn)
    memo.execute("SELECT id FROM opportunities").fetchall()
    second = memo.execute("SELECT id FROM opportunities")
    assert len(second.fetchall()) > 0, "the memo served an exhausted cursor"
    assert second.fetchone() is not None
    conn.close()


def test_a_write_throws_the_memo_away(app_and_db):
    """The correctness question. A handler that reads, writes and reads again must see
    its own write — a cache that outlived the write would report the old row."""
    conn = db_mod.connect()
    memo = db_mod.read_memo(conn)
    before = memo.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"]
    memo.execute("INSERT INTO opportunities (client, need) VALUES (?,?)", ("New Co", "x"))
    memo.commit()
    after = memo.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"]
    assert after == before + 1, "the memo served a count from before the insert"
    conn.close()


def test_different_parameters_are_different_answers(app_and_db):
    """The memo keys on parameters too. Keying on the SQL alone would hand every
    project the first project's delivery blob — a data-corruption bug wearing a
    performance fix's clothes."""
    conn = db_mod.connect()
    memo = db_mod.read_memo(conn)
    rows = memo.execute("SELECT id FROM projects ORDER BY id").fetchall()
    if len(rows) < 2:
        pytest.skip("needs two seeded projects")
    a = memo.execute("SELECT id FROM projects WHERE id = ?", (rows[0]["id"],)).fetchone()
    b = memo.execute("SELECT id FROM projects WHERE id = ?", (rows[1]["id"],)).fetchone()
    assert a["id"] != b["id"]
    conn.close()


# --------------------------------------------------------------------------- #
# Priming
# --------------------------------------------------------------------------- #
def test_priming_means_the_per_row_helper_never_reaches_the_database(app_and_db):
    """The per-row code is deliberately unchanged — it just stops doing any I/O."""
    conn = db_mod.connect()
    ids = [r["id"] for r in conn.execute("SELECT id FROM projects ORDER BY id")]
    memo = db_mod.read_memo(conn)
    db_mod.prime_project_reads(memo, ids)
    hits_before = memo.hits
    for pid in ids:
        db_mod.get_delivery(memo, pid)          # the exact per-row call the loop makes
    assert memo.hits == hits_before + len(ids), (
        "get_delivery went back to the database for a row that was primed")
    conn.close()


def test_priming_a_project_with_no_row_still_prevents_the_query(app_and_db):
    """Otherwise a missing project is the one that still N+1s, which is exactly the
    case nobody notices until the data is uneven."""
    conn = db_mod.connect()
    memo = db_mod.read_memo(conn)
    db_mod.prime_project_reads(memo, [999999])
    hits = memo.hits
    assert db_mod.get_delivery(memo, 999999) == {}
    assert memo.hits == hits + 1, "a missing project fell through to the database"
    conn.close()


def test_priming_is_a_no_op_on_a_plain_connection(app_and_db):
    """It must be safe to call from any handler, memo or not."""
    conn = db_mod.connect()
    assert db_mod.prime_project_reads(conn, [1, 2, 3]) == 0
    conn.close()


# --------------------------------------------------------------------------- #
# The page itself
# --------------------------------------------------------------------------- #
def test_the_dashboard_renders_exactly_the_same_page(app_and_db):
    """The only result that would make this worth reverting: a faster dashboard that
    shows something different. Rendered with and without both mechanisms, byte for
    byte."""
    app_mod = app_and_db
    with TestClient(app_mod.app) as c:
        fast = c.get("/dashboard").text
        orig_memo, orig_prime = db_mod.read_memo, db_mod.prime_project_reads
        db_mod.read_memo = lambda conn: conn
        db_mod.prime_project_reads = lambda *a, **k: 0
        try:
            plain = c.get("/dashboard").text
        finally:
            db_mod.read_memo, db_mod.prime_project_reads = orig_memo, orig_prime
    assert fast == plain, "the batched dashboard renders a different page"


def test_the_query_count_no_longer_tracks_the_project_count_one_for_one(app_and_db):
    """The regression this exists to prevent: someone adds a per-project read to an
    aggregator and the dashboard silently goes back to hundreds of round trips.

    Asserted as a RATIO against the unbatched cost on the same data, so the test does
    not have to be rewritten every time the page gains a card.
    """
    app_mod = app_and_db
    conn = db_mod.connect()
    for i in range(12):
        conn.execute("INSERT INTO opportunities (client, need, status, qualified) "
                     "VALUES (?,?,?,1)", (f"C{i}", f"Campaign {i}", "Won"))
        oid = conn.execute("SELECT id FROM opportunities ORDER BY id DESC "
                           "LIMIT 1").fetchone()["id"]
        conn.execute("INSERT INTO projects (opp_id, client, need, status) VALUES (?,?,?,?)",
                     (oid, f"C{i}", f"Campaign {i}", "Active"))
    conn.commit()
    conn.close()

    n, real = _counting(db_mod)
    try:
        with TestClient(app_mod.app) as c:
            n.clear(); c.get("/dashboard"); batched = n["db"]
            orig_memo, orig_prime = db_mod.read_memo, db_mod.prime_project_reads
            db_mod.read_memo = lambda conn: conn
            db_mod.prime_project_reads = lambda *a, **k: 0
            try:
                n.clear(); c.get("/dashboard"); unbatched = n["db"]
            finally:
                db_mod.read_memo, db_mod.prime_project_reads = orig_memo, orig_prime
    finally:
        db_mod.connect = real
    assert batched < unbatched * 0.75, (
        f"batched={batched} unbatched={unbatched} — the saving has been lost")
