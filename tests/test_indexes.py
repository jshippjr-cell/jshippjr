"""There were no indexes. None — `CREATE INDEX` appeared zero times across 53 tables.

Measured before this change, on a seeded database with `EXPLAIN QUERY PLAN`, **13 of
16 hot queries full-scanned their table**, including both client-facing token lookups.
The three that did not were covered by accident: SQLite builds an autoindex for a
UNIQUE constraint, so a couple of access paths were fast for a reason nobody chose.

SQLite over a local file hid all of it. A scan of a few hundred rows in page cache is
free, and the tables here are small. Postgres over a network is a different machine:
the same scan crosses a socket page by page, on a connection that was itself just
opened. That is why this is a cutover PRECONDITION rather than a tidy-up — the day the
database moves is the day the cost appears, and it appears everywhere at once.

These tests assert the access paths, not the index names. An index that exists but that
the planner declines to use is not a fix, and a test that only checks `pg_indexes` would
pass on one.
"""

import importlib
import os
import tempfile

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import db as db_mod  # noqa: E402

# Every one of these is a real access path in the product. The label is the operator's
# name for it, because that is what a regression here actually costs.
HOT_QUERIES = [
    ("the client's review portal", "SELECT * FROM projects WHERE share_token = 'x'"),
    ("the first-touch page", "SELECT * FROM opportunities WHERE share_token = 'x'"),
    ("a project's proposals", "SELECT * FROM proposals WHERE project_id = 1"),
    ("a project's assignments", "SELECT * FROM assignments WHERE project_id = 1"),
    ("a project's review notes", "SELECT * FROM review_comments WHERE project_id = 1"),
    ("a project's invoices", "SELECT * FROM invoices WHERE project_id = 1"),
    ("a project's milestones", "SELECT * FROM milestones WHERE project_id = 1"),
    ("an opportunity's project", "SELECT * FROM projects WHERE opp_id = 1"),
    ("an opportunity's outreach", "SELECT * FROM outreach_events WHERE opp_id = 1"),
    ("an agency's outreach", "SELECT * FROM agency_outreach WHERE agency_id = 1"),
    ("an agency's relationships", "SELECT * FROM relationships WHERE agency_id = 1"),
    ("the open pipeline", "SELECT * FROM opportunities WHERE status = 'Active'"),
    ("the unpaid invoices", "SELECT * FROM invoices WHERE status = 'sent'"),
    ("the signal queue", "SELECT * FROM signals WHERE status = 'new'"),
    ("the crawl backlog", "SELECT * FROM crawl_targets WHERE status = 'Approved'"),
    ("the talent review queue", "SELECT * FROM talent WHERE review_status = 'Pending'"),
]


@pytest.fixture()
def seeded(monkeypatch, tmp_path):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "idx.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app):
        pass                                   # lifespan builds + seeds the schema
    conn = db_mod.connect()
    yield conn
    conn.close()


def test_no_hot_query_reads_a_whole_table(seeded):
    """The measurement, as a test. Before: 13 of these 16 scanned."""
    scans = []
    for label, sql in HOT_QUERIES:
        plan = " | ".join(str(r[3]) for r in seeded.execute("EXPLAIN QUERY PLAN " + sql))
        if "SCAN" in plan:
            scans.append(f"{label}: {plan}")
    assert scans == [], (
        "these read every row of their table:\n  " + "\n  ".join(scans))


def test_every_declared_index_exists(seeded):
    """The list in `db.py` is the declaration; this is the proof it was applied.
    Creation is deliberately best-effort per index — one bad entry must not stop the
    other fifty — which is exactly the mechanism that could let one silently vanish."""
    made = {r["name"] for r in seeded.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'")}
    missing = sorted({n for n, _ in db_mod._INDEXES} - made)
    assert missing == [], f"declared but not created: {missing}"


def test_no_index_is_declared_twice(seeded):
    """A duplicate name is silently accepted by IF NOT EXISTS, so the second entry
    would look present while indexing something else entirely."""
    names = [n for n, _ in db_mod._INDEXES]
    assert len(names) == len(set(names)), \
        sorted({n for n in names if names.count(n) > 1})


def test_every_index_targets_a_real_table_and_column(seeded):
    """An index on a column that has been renamed is created, does nothing, and is
    never noticed — the failure mode of a declared list nobody re-reads."""
    import re
    bad = []
    for name, target in db_mod._INDEXES:
        table, cols = re.match(r"(\w+)\((.+)\)", target).groups()
        actual = {r[1] for r in seeded.execute(f"PRAGMA table_info({table})")}
        if not actual:
            bad.append(f"{name}: no table {table}")
            continue
        for col in (c.strip() for c in cols.split(",")):
            if col not in actual:
                bad.append(f"{name}: {table} has no column {col}")
    assert bad == [], "\n  ".join(bad)


def test_indexes_are_created_on_an_existing_database_too(tmp_path, monkeypatch):
    """The production database already exists. Indexes that only appear in the
    fresh-schema path would never reach it — which is the one database that matters."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "old.db"))
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.execute("DROP INDEX idx_projects_share_token")
    conn.commit()
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'idx_projects_share_token'").fetchone()
    db_mod._ensure_schema(conn)                # the migration path, as a redeploy runs it
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'idx_projects_share_token'").fetchone()
    conn.close()
