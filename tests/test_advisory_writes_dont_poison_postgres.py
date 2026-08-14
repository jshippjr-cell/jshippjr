"""`except Exception: pass` around a database call is a live grenade on Postgres.

SQLite shrugs a failed statement off. Postgres puts the whole transaction into an
aborted state, and every command after it raises InFailedSqlTransaction until someone
rolls back. So a swallowed failure in some optional bookkeeping does not stay optional —
it takes down the write the caller actually cared about, with an error that names neither
the bookkeeping nor the caller.

That is precisely how a discovery transcript came back from Recall and then failed to
file, live, on 2026-08-13:

    The transcript came back but filing it failed: InFailedSqlTransaction: current
    transaction is aborted, commands ignored until end of transaction block

Three advisory blocks run before the capture is inserted. Any one of them failing
quietly poisoned the insert. The suite could not see it, because every test runs on
SQLite, where all three are harmless.

So these tests emulate Postgres's contract rather than trusting the dialect: once a
statement fails, everything raises until a rollback.
"""
import pytest


class _AbortedTransaction(Exception):
    """Stands in for psycopg.errors.InFailedSqlTransaction."""


class _PostgresLike:
    """A connection with Postgres's abort semantics and savepoint support."""

    def __init__(self):
        self.aborted = False
        self.savepoints = []
        self.log = []

    def execute(self, sql, params=()):
        s = sql.strip().upper()
        if s.startswith("SAVEPOINT"):
            self.savepoints.append(sql.split()[-1])
            self.log.append(sql)
            return self
        if s.startswith("ROLLBACK TO SAVEPOINT"):
            self.aborted = False              # this is what un-poisons it
            self.log.append(sql)
            return self
        if s.startswith("RELEASE SAVEPOINT"):
            self.log.append(sql)
            return self
        if self.aborted:
            raise _AbortedTransaction(
                "current transaction is aborted, commands ignored until end of "
                "transaction block")
        if "BOOM" in s:                        # the advisory statement that fails
            self.aborted = True
            raise RuntimeError("relation does not exist")
        self.log.append(sql)
        return self

    def commit(self):
        if self.aborted:
            raise _AbortedTransaction("cannot commit an aborted transaction")

    def rollback(self):
        self.aborted = False


def test_the_bare_swallow_is_the_bug(monkeypatch):
    """Establish the failure first, so the fix is measured against something real."""
    conn = _PostgresLike()
    try:                                       # the old pattern, verbatim
        conn.execute("INSERT INTO boom VALUES (1)")
    except Exception:                          # noqa: BLE001
        pass
    with pytest.raises(_AbortedTransaction):
        conn.execute("INSERT INTO captures VALUES (1)")


def test_best_effort_lets_the_real_write_through():
    """The fix: advisory work is undone, and the caller's write still lands."""
    from chordential_oia.web import db
    conn = _PostgresLike()
    with db.best_effort(conn, "spend"):
        conn.execute("INSERT INTO boom VALUES (1)")
    conn.execute("INSERT INTO captures VALUES (1)")     # must NOT raise
    assert any("ROLLBACK TO SAVEPOINT" in s for s in conn.log)


def test_it_keeps_what_the_caller_did_before():
    """A savepoint, not a rollback: earlier work in the same transaction survives."""
    from chordential_oia.web import db
    conn = _PostgresLike()
    conn.execute("INSERT INTO meetings VALUES (1)")
    with db.best_effort(conn):
        conn.execute("INSERT INTO boom VALUES (1)")
    conn.execute("INSERT INTO captures VALUES (2)")
    assert "INSERT INTO meetings VALUES (1)" in conn.log


def test_a_successful_block_does_NOT_release_its_savepoint():
    """It used to, and that was the bug that reached a client.

    Almost every db helper here COMMITS internally, and a COMMIT discards every savepoint
    in the transaction — so the RELEASE hit one that no longer existed, raised, and
    aborted the transaction. Live: `POST /meet/<token>/pick -> 500,
    InvalidSavepointSpecification: savepoint "be_1" does not exist`, on the link a client
    clicks to accept a meeting time.

    Releasing bought nothing: the next COMMIT releases it anyway."""
    from chordential_oia.web import db
    conn = _PostgresLike()
    with db.best_effort(conn):
        conn.execute("INSERT INTO ai_spend VALUES (1)")
    assert not any("RELEASE SAVEPOINT" in s for s in conn.log)
    conn.execute("INSERT INTO captures VALUES (1)")      # still usable


def test_nested_blocks_do_not_collide():
    from chordential_oia.web import db
    conn = _PostgresLike()
    with db.best_effort(conn, "a"):
        with db.best_effort(conn, "b"):
            conn.execute("INSERT INTO boom VALUES (1)")
        conn.execute("INSERT INTO ok VALUES (1)")
    conn.execute("INSERT INTO captures VALUES (1)")
    names = [s.split()[-1] for s in conn.log if s.upper().startswith("SAVEPOINT")]
    assert len(names) == len(set(names)), "each savepoint needs its own name"


def test_a_connection_without_savepoints_still_swallows():
    """SQLite in autocommit, or anything else that refuses SAVEPOINT: the block must
    still not raise — it just loses the transactional nicety."""
    from chordential_oia.web import db

    class _NoSavepoints:
        def execute(self, sql, params=()):
            if sql.strip().upper().startswith(("SAVEPOINT", "ROLLBACK TO", "RELEASE")):
                raise RuntimeError("savepoints not supported here")
            raise RuntimeError("the advisory work failed")

    with db.best_effort(_NoSavepoints()):
        _NoSavepoints().execute("INSERT INTO whatever VALUES (1)")


def test_the_transcript_ingest_path_uses_it():
    """The three advisory blocks that run before a capture is inserted are the ones that
    took the transcript down. If any goes back to a bare swallow, this fails."""
    import inspect

    from chordential_oia.web import campaign_intake
    src = inspect.getsource(campaign_intake._apply_capture)
    assert src.count("db.best_effort(") >= 3, src
    for orphan in ("except Exception:  # noqa: BLE001 — learning is advisory",
                   "except Exception:  # noqa: BLE001 — the engine is an upgrade",
                   "except Exception:  # noqa: BLE001 — accounting never blocks"):
        assert orphan not in src, f"bare swallow is back: {orphan}"
