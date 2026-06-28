"""SQLite is opened in WAL mode so a page read never blocks behind a background
write. Without this, one background write transaction stalls every reader until it
finishes — which on a busy instance presents as the whole site hanging (the live
'spin wheel'). Regression test for that.
"""

import threading
import time

from chordential_oia.web import db as dbm


def test_connection_uses_wal(tmp_path):
    conn = dbm.connect(str(tmp_path / "w.db"))
    dbm.init_db(conn)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_read_does_not_block_behind_open_write(tmp_path):
    path = str(tmp_path / "w.db")
    conn = dbm.connect(path)
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "s", {"dedup_key": "a", "company": "A", "website": "https://a.com"})
    conn.commit()

    writer = dbm.connect(path)
    writer.execute("BEGIN")
    writer.execute("UPDATE agencies SET company='A2' WHERE dedup_key='a'")  # holds write lock
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
