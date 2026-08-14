"""A best-effort block must survive the wrapped code committing.

`db.best_effort` wraps advisory work in a SAVEPOINT so a failure cannot poison the
caller's transaction on Postgres. The first version then RELEASEd the savepoint on
success — and almost every db helper in this codebase COMMITS internally. A COMMIT
discards every savepoint in the transaction, so the RELEASE hit a savepoint that no
longer existed, raised, and aborted the transaction: precisely the poisoning the helper
exists to prevent.

Live cost, caught against a real Postgres 16:

    POST /meet/<token>/pick  ->  500
    InvalidSavepointSpecification: savepoint "be_1" does not exist

That is the link a CLIENT clicks to accept a meeting time. It is the conversion path.

SQLite cannot see any of this — it has no aborted-transaction state — so these run
against a real server and SKIP without one. Skipping is not passing.
"""
import os

import pytest

PG = os.environ.get("CHORDENTIAL_TEST_PG", "")
pytestmark = pytest.mark.skipif(not PG, reason="needs CHORDENTIAL_TEST_PG (a real server)")


@pytest.fixture()
def conn(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", PG)
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


def test_an_inner_commit_does_not_break_the_block(conn):
    """The exact shape of the bug: advisory work that commits."""
    from chordential_oia.web import db
    with db.best_effort(conn, "commits"):
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS t_be (n int)")
        conn.commit()                      # destroys the savepoint
    # anything after this used to raise InFailedSqlTransaction
    conn.execute("SELECT 1").fetchone()


def test_a_failure_after_an_inner_commit_still_leaves_a_usable_connection(conn):
    """Both halves at once: the wrapped code commits AND then fails."""
    from chordential_oia.web import db
    with db.best_effort(conn, "commits_then_fails"):
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS t_be2 (n int)")
        conn.commit()
        conn.execute("SELECT * FROM a_table_that_does_not_exist")
    conn.execute("SELECT 1").fetchone()    # must not raise


def test_a_plain_failure_is_still_rolled_back_to_the_savepoint(conn):
    """The original guarantee has to survive the fix."""
    from chordential_oia.web import db
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS t_keep (n int)")
    conn.execute("INSERT INTO t_keep VALUES (1)")
    with db.best_effort(conn, "fails"):
        conn.execute("SELECT * FROM nope_not_here")
    row = conn.execute("SELECT COUNT(*) AS c FROM t_keep").fetchone()
    assert row["c"] == 1, "work done before the advisory block must survive it"


def test_the_client_can_accept_a_meeting_time_after_the_proposal_was_sent(conn, monkeypatch):
    """The end-to-end that broke: send the options, then a client picks one."""
    import importlib

    from fastapi.testclient import TestClient

    from chordential_oia.models import Opportunity
    from chordential_oia.web import db
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)

    opp_id = db.insert_opportunity(conn, Opportunity(
        client="Vance Athletic", need="Spring launch", description=""))
    pid = db.create_meeting_proposal(
        conn, opp_id=opp_id, token="tok_accept",
        slots=["2026-09-20T15:00:00+00:00", "2026-09-21T16:00:00+00:00"],
        meeting_type="zoom", duration_min=30, client_name="Jon",
        client_email="jon@example.com", message="", join_url="")

    with TestClient(app_mod.app, raise_server_exceptions=False) as c:
        assert c.post(f"/opportunity/{opp_id}/proposal/{pid}/send",
                      data={}).status_code < 400
        r = c.post("/meet/tok_accept/pick", data={"pick": "1"}, follow_redirects=False)
        assert r.status_code == 303, f"a client accepting a time answered {r.status_code}"
        assert c.get("/meet/tok_accept").status_code == 200
