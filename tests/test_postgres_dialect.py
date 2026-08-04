"""The Postgres path, exercised against a real Postgres.

The cutover code shipped a **regex SQL dialect shim** that had never been run against a
Postgres server — psycopg wasn't even installed. Standing one up found three defects,
each of which would have failed *during* the cutover, after the SQLite disk was already
being decommissioned:

1. **`BLOB` is not a Postgres type.** `media_blob` — the DB mirror of every uploaded
   master — could not be `CREATE`d at all. The app would not boot.
2. **`COLLATE NOCASE` does not exist in Postgres.** `ORDER BY company COLLATE NOCASE`
   is a hard error, so the agencies list, the decision-maker list and the roster all
   500'd.
3. **The migration script crashed mid-copy.** It called
   `pg_get_serial_sequence(t, 'id')` for every table; `media_blob` is keyed by `name`
   and has no `id`, so it raised `UndefinedColumn` — *after* several tables had already
   been written, on production data.

ADR-0045. The translator tests below are pure functions and run everywhere. The live
tests need a server and skip without one:

    CHORDENTIAL_TEST_PG=postgresql://user@host:port/dbname python -m pytest tests/test_postgres_dialect.py

Skipping is not passing. A green run with no DSN says nothing about Postgres — which is
exactly how the shim reached production untested in the first place.
"""

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from chordential_oia.web.db import _pg_translate

PG_DSN = os.environ.get("CHORDENTIAL_TEST_PG", "").strip()
live = pytest.mark.skipif(not PG_DSN, reason="set CHORDENTIAL_TEST_PG to a Postgres DSN")


# --------------------------------------------------------------------------- #
# The translator — pure, runs everywhere
# --------------------------------------------------------------------------- #
def test_blob_becomes_bytea():
    """The defect that stopped the app booting: media_blob could not be created.

    The word also appears in the TABLE's name, so assert on the column type — the
    first version of this test checked `"BLOB" not in out` and failed on
    `media_blob` itself."""
    out = _pg_translate("CREATE TABLE media_blob (name TEXT PRIMARY KEY, content BLOB)")
    assert "content BYTEA" in out
    assert "content BLOB" not in out
    assert "media_blob" in out, "the table name must not be rewritten"


def test_collate_nocase_becomes_lower():
    """The defect that 500'd the agencies list."""
    assert "LOWER(company)" in _pg_translate("SELECT * FROM a ORDER BY company COLLATE NOCASE")
    assert "NOCASE" not in _pg_translate("SELECT * FROM a ORDER BY name COLLATE NOCASE").upper()


def test_autoincrement_becomes_serial():
    out = _pg_translate("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT)")
    assert "SERIAL PRIMARY KEY" in out
    assert "AUTOINCREMENT" not in out.upper()


def test_two_arg_max_is_greatest_but_the_aggregate_is_left_alone():
    """SQLite overloads MAX: two args is a scalar, one is an aggregate. Translating
    the aggregate would silently change every rollup."""
    assert "GREATEST(a, b)" in _pg_translate("SELECT MAX(a, b) FROM t")
    assert "LEAST(a, b)" in _pg_translate("SELECT MIN(a, b) FROM t")
    assert _pg_translate("SELECT MAX(id) FROM t") == "SELECT MAX(id) FROM t"


def test_sqlite_only_functions_are_mapped():
    assert "COALESCE(" in _pg_translate("SELECT IFNULL(a, 0) FROM t")
    assert "string_agg(" in _pg_translate("SELECT GROUP_CONCAT(name) FROM t")


def test_pragma_becomes_information_schema():
    """`_ensure_schema` introspects columns to run its idempotent migrations; PRAGMA
    is SQLite-only, so without this every ALTER-TABLE migration would misfire."""
    out = _pg_translate("PRAGMA table_info(opportunities)")
    assert "information_schema.columns" in out
    assert "'opportunities'" in out


def test_placeholders_are_converted():
    assert _pg_translate("SELECT * FROM t WHERE a = ? AND b = ?") == \
        "SELECT * FROM t WHERE a = %s AND b = %s"


# --------------------------------------------------------------------------- #
# Against a real server
# --------------------------------------------------------------------------- #
def _fresh_db():
    """A throwaway database on the configured server; returns its DSN."""
    import psycopg
    name = "chordtest_" + uuid.uuid4().hex[:10]
    admin = psycopg.connect(PG_DSN, autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    base, _, _old = PG_DSN.rpartition("/")
    return f"{base}/{name}"


@live
def test_the_schema_builds_on_real_postgres(monkeypatch):
    """Defect 1's regression test. `init_db` raised UndefinedObject on `BLOB`."""
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert "media_blob" in tables, "the client-media mirror table was not created"
    assert "opportunities" in tables and "projects" in tables
    conn.close()


@live
def test_the_console_serves_on_real_postgres(monkeypatch, tmp_path):
    """Defect 2's regression test — /agencies is the one COLLATE NOCASE killed."""
    from fastapi.testclient import TestClient
    import importlib

    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)

    with TestClient(app_mod.app) as c:
        for path in ("/dashboard", "/queue", "/inbox", "/revenue", "/agencies",
                     "/projects", "/talent", "/relationships", "/"):
            assert c.get(path, follow_redirects=False).status_code == 200, path


@live
def test_a_master_survives_the_migration_byte_for_byte(monkeypatch, tmp_path):
    """Defect 3's regression test, and the one that matters most: the migration must
    complete AND the binary must arrive intact. A partial copy on cutover day, with
    the disk being decommissioned, is the worst outcome this project has."""
    import hashlib
    import importlib
    from fastapi.testclient import TestClient

    # a realistic SQLite source with an uploaded master in the mirror
    src = tmp_path / "src.db"
    monkeypatch.setenv("CHORDENTIAL_DB", str(src))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    payload = b"ID3" + bytes(range(256)) * 40
    with TestClient(app_mod.app) as c:
        conn = db_mod.connect()
        pid = conn.execute(
            "SELECT id FROM projects WHERE share_token != '' LIMIT 1").fetchone()["id"]
        conn.close()
        c.post(f"/project/{pid}/delivery/version",
               files={"file": ("master.mp3", payload, "audio/mpeg")})

    raw = sqlite3.connect(str(src)); raw.row_factory = sqlite3.Row
    before = {r["name"]: (bytes(r["content"]), hashlib.sha256(bytes(r["content"])).hexdigest())
              for r in raw.execute("SELECT name, content FROM media_blob")}
    want_counts = {t: raw.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in ("opportunities", "projects", "talent", "media_blob")}
    raw.close()
    assert before, "no media was mirrored — the test would prove nothing"

    dsn = _fresh_db()
    script = Path(__file__).resolve().parents[1] / "scripts" / "migrate_sqlite_to_postgres.py"
    proc = subprocess.run([sys.executable, str(script), str(src), dsn],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, f"the migration crashed:\n{proc.stdout}\n{proc.stderr}"
    assert "MISMATCH" not in proc.stdout, proc.stdout

    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    importlib.reload(db_mod)
    conn = db_mod.connect()
    try:
        for t, want in want_counts.items():
            got = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            assert got == want, f"{t}: sqlite={want} postgres={got}"
        for name, (data, sha) in before.items():
            blob = db_mod.get_media_blob(conn, name)
            assert blob is not None, f"{name} did not survive the migration"
            assert hashlib.sha256(blob[0]).hexdigest() == sha, f"{name} arrived corrupted"
    finally:
        conn.close()


@live
def test_writes_work_on_real_postgres(monkeypatch, tmp_path):
    """The shim fakes `lastrowid` with RETURNING id. Reads passing says nothing about
    inserts, and an insert that silently returns the wrong id corrupts relationships."""
    import importlib
    from fastapi.testclient import TestClient

    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)

    with TestClient(app_mod.app) as c:
        conn = db_mod.connect()
        oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
        conn.close()
        assert c.post(f"/opportunity/{oid}/status",
                      data={"status": "Won", "outcome_value": "12000"},
                      follow_redirects=False).status_code == 303
        conn = db_mod.connect()
        row = conn.execute("SELECT status, outcome_value FROM opportunities "
                           "WHERE id = %s" % oid).fetchone()
        conn.close()
    assert row["status"] == "Won"
    assert float(row["outcome_value"]) == 12000.0
