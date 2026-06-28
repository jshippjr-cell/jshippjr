"""SQLite journal mode. WAL lets a read proceed past an open write, but it relies
on shared-memory + POSIX locking that are unreliable on network-attached storage
(a Render persistent disk), where it can hang every DB open — the whole site down
while /healthz (no DB) still passes. So WAL is OPT-IN; the default is the rollback
journal that ran reliably in prod. These tests pin that contract, including the
recovery path: a DB left in WAL must revert to rollback when reopened by default.
"""

import os
import threading
import time

from chordential_oia.web import db as dbm


def test_default_is_rollback_journal_not_wal(tmp_path, monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_SQLITE_WAL", raising=False)
    conn = dbm.connect(str(tmp_path / "w.db"))
    dbm.init_db(conn)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
    assert mode != "wal"                          # default is NOT wal on a mounted disk


def test_wal_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_SQLITE_WAL", "1")
    conn = dbm.connect(str(tmp_path / "w.db"))
    dbm.init_db(conn)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_reopening_reverts_persisted_wal_to_rollback(tmp_path, monkeypatch):
    # journal_mode persists in the DB file. A DB that was once opened in WAL (and so
    # has -wal/-shm files on the disk) must come back as rollback when reopened with
    # WAL off — this is what lets a stuck-in-WAL prod DB recover after we ship the
    # default-off change, and it cleans up the stale sidecar files.
    path = str(tmp_path / "w.db")
    monkeypatch.setenv("CHORDENTIAL_SQLITE_WAL", "1")
    conn = dbm.connect(path)
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "a", "company": "A",
                                  "website": "https://a.com"})
    conn.commit()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()

    monkeypatch.delenv("CHORDENTIAL_SQLITE_WAL", raising=False)
    conn2 = dbm.connect(path)
    assert conn2.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal"
    assert conn2.execute("SELECT COUNT(*) FROM agencies").fetchone()[0] == 1  # data intact
    conn2.close()
    assert not os.path.exists(path + "-wal")      # stale sidecar cleaned up


def test_read_returns_during_an_open_write(tmp_path, monkeypatch):
    # In the default rollback journal an uncommitted writer holds only a RESERVED
    # lock, so a concurrent reader still returns promptly (it sees the old row).
    monkeypatch.delenv("CHORDENTIAL_SQLITE_WAL", raising=False)
    path = str(tmp_path / "w.db")
    conn = dbm.connect(path)
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "a", "company": "A", "website": "https://a.com"})
    conn.commit()

    writer = dbm.connect(path)
    writer.execute("BEGIN")
    writer.execute("UPDATE agencies SET company='A2' WHERE dedup_key='a'")  # RESERVED lock
    try:
        result = {}

        def read():
            r = dbm.connect(path)
            t0 = time.time()
            result["n"] = r.execute("SELECT COUNT(*) FROM agencies").fetchone()[0]
            result["secs"] = time.time() - t0
            r.close()

        th = threading.Thread(target=read)
        th.start()
        th.join(timeout=3)
        assert not th.is_alive()                 # the reader returned (didn't hang)
        assert result["n"] == 1 and result["secs"] < 1.0
    finally:
        writer.rollback()
        writer.close()
