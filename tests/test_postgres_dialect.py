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

A fourth arrived on 2026-08-28, the same way and long after the cutover:

4. **`INSERT OR REPLACE` / `INSERT OR IGNORE` are SQLite-only.** Not in the shim's list
   and not addable to it — the faithful translation depends on which unique key you meant
   to conflict on. So `/queue/dismiss` answered 500 on every press, and creating a
   project's payouts raised, while the whole SQLite suite stayed green. Banned at the
   source now (see `tests/test_taking_a_card_off_the_queue.py`) and exercised live below.

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


@live
def test_the_scheduler_lease_elects_one_instance_on_real_postgres(monkeypatch):
    """The lease exists FOR the cutover, so SQLite passing it proves the wrong thing.

    Its correctness rests on two things the dialect shim has to get right: `rowcount`
    on an UPDATE (how the winner is decided) and a failed INSERT leaving the
    transaction usable (how the loser is told). Postgres aborts a transaction on a
    constraint violation — a missing rollback would turn every subsequent statement
    on that connection into `InFailedSqlTransaction`, and the loser would take the
    whole instance down instead of standing by.
    """
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)

    conn = db_mod.connect()
    db_mod.init_db(conn)
    try:
        assert db_mod.acquire_lease(conn, "scheduler", "instance-A", 90) is True
        assert db_mod.acquire_lease(conn, "scheduler", "instance-B", 90) is False
        # The loser's connection must still be usable — this is the assertion that
        # would have caught a missing rollback.
        assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        assert db_mod.acquire_lease(conn, "scheduler", "instance-A", 90) is True

        conn.execute("UPDATE scheduler_lease SET expires_at = ? WHERE name = ?",
                     ("2000-01-01T00:00:00Z", "scheduler"))
        conn.commit()
        assert db_mod.acquire_lease(conn, "scheduler", "instance-B", 90) is True
        assert db_mod.lease_holder(conn, "scheduler")["owner"] == "instance-B"

        db_mod.release_lease(conn, "scheduler", "instance-B")
        assert db_mod.lease_holder(conn, "scheduler") is None
    finally:
        conn.close()


@live
def test_the_indexes_exist_and_are_usable_on_real_postgres(monkeypatch):
    """SQLite's `EXPLAIN QUERY PLAN` proves the access path on SQLite. Postgres is the
    backend the indexes exist FOR, and `CREATE INDEX IF NOT EXISTS` going through the
    dialect shim is not something to assume.

    `enable_seqscan = off` is deliberate: on a seeded table of a few dozen rows Postgres
    will correctly prefer a sequential scan no matter what indexes exist, so asking
    "which plan is cheapest today" would tell us nothing. Forcing the planner's hand
    answers the question actually being asked — is the index there, and can it be used.
    """
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)

    conn = db_mod.connect()
    db_mod.init_db(conn)
    try:
        made = {r["indexname"] for r in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx_%'")}
        missing = sorted({n for n, _ in db_mod._INDEXES} - made)
        assert missing == [], f"declared but not created on Postgres: {missing}"

        conn.execute("SET enable_seqscan = off")
        conn.commit()
        for sql in ("SELECT * FROM projects WHERE share_token = 'x'",
                    "SELECT * FROM opportunities WHERE status = 'Active'",
                    "SELECT * FROM review_comments WHERE project_id = 1"):
            plan = " ".join(str(r[0]) for r in conn.execute("EXPLAIN " + sql))
            assert "idx_" in plan, f"planner cannot use an index for: {sql}\n{plan}"
    finally:
        conn.close()


@live
def test_the_json_merge_is_atomic_on_real_postgres(monkeypatch):
    """The one-key merge is dialect-specific — `jsonb || jsonb` on Postgres, `json_set`
    on SQLite — and it goes through the translation shim on the way. SQLite passing
    says nothing about the backend production actually runs on.
    """
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    import importlib
    import threading
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)

    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.execute("INSERT INTO projects (client, need) VALUES ('Acme', 'Anthem')")
    conn.commit()
    pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    conn.close()
    try:
        # shapes round-trip
        c = db_mod.connect()
        shapes = {"versions": [{"n": 1}, {"n": 2}], "state": "Delivered",
                  "revisions_used": 2, "license_confirmed": True}
        for k, v in shapes.items():
            db_mod.update_delivery(c, pid, k, v)
        got = db_mod.get_delivery(c, pid)
        assert all(got[k] == v for k, v in shapes.items()), got
        # removal takes exactly one key
        db_mod.update_delivery(c, pid, "versions", None)
        got = db_mod.get_delivery(c, pid)
        assert "versions" not in got and got["state"] == "Delivered"
        c.close()

        # and concurrent merges of different keys do not erase each other
        losses = []
        for r in range(10):
            a, b = f"approval_{r}", f"version_{r}"
            start = threading.Barrier(2)

            def writer(key, value):
                cc = db_mod.connect()
                start.wait(timeout=10)
                db_mod.update_delivery(cc, pid, key, value)
                cc.close()

            ts = [threading.Thread(target=writer, args=(a, {"by": "Priya"})),
                  threading.Thread(target=writer, args=(b, [{"n": r}]))]
            for t in ts: t.start()
            for t in ts: t.join(timeout=30)
            cc = db_mod.connect()
            final = db_mod.get_delivery(cc, pid)
            cc.close()
            if a not in final or b not in final:
                losses.append(r)
        assert losses == [], f"rounds that lost a write on Postgres: {losses}"
    finally:
        db_mod.close_pool()


@live
def test_a_large_take_survives_a_deploy_on_real_postgres(monkeypatch, tmp_path):
    """The operator's actual constraint, against the database production actually runs.

    *"i dont want to take the steps to setup more storage i want to use the storage i
    have and not lose files"* — and the storage they have is this. The mirror was already
    doing the job for small files; the 64 MB ceiling (ADR-0026, reasoning about SQLite)
    was what dropped everything bigger onto a disk Render replaces.

    Deliberately sized ABOVE the old ceiling. Under the previous policy this file was
    accepted, stored once, and returned 404 after the next deploy.
    """
    import importlib
    import shutil
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CHORDENTIAL_DB", _fresh_db())
    up = tmp_path / "up"
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(up))
    monkeypatch.delenv("CHORDENTIAL_MIRROR_MB", raising=False)
    monkeypatch.delenv("CHORDENTIAL_STORAGE", raising=False)
    for m in ("db", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod, db as db_mod, uploads

    conn = db_mod.connect()
    db_mod.init_db(conn)
    try:
        assert db_mod.is_postgres(conn), "this test is meaningless off Postgres"
        cap = uploads.mirror_cap(conn)
        assert cap > uploads.SQLITE_MIRROR_BYTES, (
            "Postgres is still being held to the SQLite ceiling")
        payload = b"ID3" + os.urandom(70 * 1024 * 1024)   # over the OLD 64 MB limit
        stored = uploads._persist_upload(conn, "big-take.mp3", payload, "audio/mpeg")
        assert stored.ok and stored.durable, stored
    finally:
        conn.close()

    shutil.rmtree(up)                     # Render replaces the container
    up.mkdir(parents=True, exist_ok=True)

    with TestClient(app_mod.app) as c:
        r = c.get("/uploads/big-take.mp3")
    assert r.status_code == 200, "a 70 MB take is still lost on deploy"
    assert r.content == payload, "it came back corrupted"


@live
def test_the_mirror_reports_failure_instead_of_raising_on_real_postgres(monkeypatch, tmp_path):
    """`save_media_blob` caught `sqlite3.Error`, which on Postgres catches NOTHING —
    psycopg raises its own hierarchy. A mirror failure in production would have escaped
    into the upload route as a 500 rather than degrading, and the connection would have
    been left poisoned for the rest of the request."""
    import importlib

    monkeypatch.setenv("CHORDENTIAL_DB", _fresh_db())
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    for m in ("db", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import db as db_mod

    conn = db_mod.connect()
    db_mod.init_db(conn)
    try:
        # Dropping the table is a stand-in for any driver error at all; the point is
        # that it comes back as False rather than as an exception through the route.
        assert db_mod.save_media_blob(conn, "ok.mp3", b"bytes", "audio/mpeg") is True
        conn.execute("DROP TABLE media_blob")
        conn.commit()
        assert db_mod.save_media_blob(conn, "gone.mp3", b"bytes", "audio/mpeg") is False
        # …and the connection is still usable, because the failure rolled back.
        assert conn.execute("SELECT 1 AS n").fetchone()["n"] == 1
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Defect 4 (2026-08-28): SQLite-only INSERT syntax, found in production
# --------------------------------------------------------------------------- #
@live
def test_the_upserts_run_on_real_postgres(monkeypatch):
    """`INSERT OR REPLACE` / `INSERT OR IGNORE` are SQLite-only, and `_pg_translate`
    does not rewrite them — a faithful translation has to know WHICH unique key you
    meant to conflict on, which a regex cannot.

    Both statements therefore raised on Postgres, which is production, while the whole
    SQLite suite stayed green. The operator found the first one by pressing Dismiss and
    getting an Internal Server Error; the second was in the money path — creating a
    project's payouts — and had never been pressed on Postgres at all.

    A static tripwire bans the syntax at the source
    (`tests/test_taking_a_card_off_the_queue.py`). This is the other half: the portable
    replacements actually behaving, on a real server, including the second press that is
    the whole reason the conflict clause is there.
    """
    import importlib
    dsn = _fresh_db()
    monkeypatch.setenv("CHORDENTIAL_DB", dsn)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)

    # 1. the press that answered 500
    db_mod.dismiss_queue_card(conn, "opp:review:42")
    db_mod.dismiss_queue_card(conn, "opp:review:42")     # the upsert, not a PK violation
    assert db_mod.dismissed_queue_keys(conn) == {"opp:review:42"}
    db_mod.restore_queue_card(conn, "opp:review:42")
    assert db_mod.dismissed_queue_keys(conn) == set()

    # 2. the same trap, in the money path
    tid = conn.execute("INSERT INTO talent (name, email, created_at) VALUES (?,?,?)",
                       ("Maya Okafor", "maya@example.com", "2026-08-28")).lastrowid
    pid = conn.execute(
        "INSERT INTO projects (need, client, status, created_at) VALUES (?,?,?,?)",
        ("Score", "Pike and Rowan", "Active", "2026-08-28")).lastrowid
    conn.execute(
        "INSERT INTO assignments (project_id, talent_id, role, created_at) VALUES (?,?,?,?)",
        (pid, tid, "Composer", "2026-08-28"))
    conn.commit()
    assert db_mod.ensure_project_payouts(conn, pid) == 1
    assert db_mod.ensure_project_payouts(conn, pid) == 0, (
        "the conflict clause did not suppress the duplicate the UNIQUE key forbids")
    conn.close()
