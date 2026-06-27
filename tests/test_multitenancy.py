"""Multi-tenancy + UUID foundation (ADR-0008).

Chordential is single-tenant in practice today, but every business row carries a
``tenant_id`` and every primary entity a stable ``uuid`` from the start, so adding
teams/clients later is a migration rather than a database redesign. These tests
pin that foundation: the default tenant is seeded idempotently, entities get valid
unique UUIDs on insert, every row is tenant-scoped, and the migration is additive
(it doesn't break existing inserts/reads).
"""

import importlib
import re

import pytest

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@pytest.fixture()
def db_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.close()
    return db_mod


# --- The tenant root ------------------------------------------------------- #
def test_default_tenant_seeded_once_and_idempotent(db_mod):
    conn = db_mod.connect()
    try:
        db_mod.init_db(conn)          # run migrations again — must not duplicate
        db_mod.init_db(conn)
        tenants = db_mod.list_tenants(conn)
    finally:
        conn.close()
    assert len(tenants) == 1
    assert tenants[0]["id"] == db_mod.DEFAULT_TENANT_ID
    assert tenants[0]["slug"] == "default"


def test_current_tenant_id_is_the_seam(db_mod):
    # Today it always resolves to the default tenant; the Auth layer overrides later.
    assert db_mod.current_tenant_id() == db_mod.DEFAULT_TENANT_ID
    assert UUID_RE.match(db_mod.new_uuid())          # real uuid4s for app-side minting


# --- Every primary entity gets a valid, unique UUID + the tenant ----------- #
def test_entity_inserts_get_uuid_and_tenant(db_mod):
    conn = db_mod.connect()
    try:
        ids = {
            "agencies": db_mod.insert_agency(conn, "Northwind Studio", city="Austin"),
            "inbound_leads": db_mod.insert_inbound_lead(
                conn, contact_name="Jane", company="Acme"),
            "agency_runs": db_mod.start_agency_run(
                conn, "clutch", "https://x", 1, True),
            "crawl_targets": db_mod.insert_crawl_target(
                conn, "talent", "L", "q", "https://ex.com", "vicontrol", "why"),
        }
        for table, rid in ids.items():
            row = conn.execute(
                f"SELECT uuid, tenant_id FROM {table} WHERE id=?", (rid,)
            ).fetchone()
            assert UUID_RE.match(row["uuid"] or ""), f"{table}: bad uuid {row['uuid']!r}"
            assert row["tenant_id"] == db_mod.DEFAULT_TENANT_ID
    finally:
        conn.close()


def test_uuids_are_unique_across_rows(db_mod):
    conn = db_mod.connect()
    try:
        a = db_mod.insert_agency(conn, "Alpha Co")
        b = db_mod.insert_agency(conn, "Beta Co")
        ua = conn.execute("SELECT uuid FROM agencies WHERE id=?", (a,)).fetchone()["uuid"]
        ub = conn.execute("SELECT uuid FROM agencies WHERE id=?", (b,)).fetchone()["uuid"]
    finally:
        conn.close()
    assert ua and ub and ua != ub


# --- Tenant scoping reaches child/event tables too ------------------------- #
def test_child_tables_are_tenant_scoped_via_default(db_mod):
    conn = db_mod.connect()
    try:
        aid = db_mod.insert_agency(conn, "Gamma Co")  # parent
        # add_outreach_event needs an opp id; use a child we can insert directly:
        # outreach_events carries tenant_id via its column DEFAULT even though its
        # insert helper was never modified.
        conn.execute(
            "INSERT INTO outreach_events (opp_id, created_at, channel, direction, note) "
            "VALUES (?,?,?,?,?)", (aid, "now", "email", "out", "hi"))
        conn.commit()
        row = conn.execute(
            "SELECT tenant_id FROM outreach_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row["tenant_id"] == db_mod.DEFAULT_TENANT_ID


# --- The migration is additive: an OLD db (pre-tenancy) upgrades cleanly ---- #
def test_legacy_db_backfills_tenant_and_uuid(db_mod, tmp_path):
    import sqlite3
    # Simulate a pre-ADR-0008 database: an agencies table with rows but no
    # tenant_id / uuid columns. _ensure_tenancy must add + backfill them.
    legacy = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(legacy)
    raw.execute(
        "CREATE TABLE agencies (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "company TEXT, company_key TEXT, status TEXT)")
    raw.execute("INSERT INTO agencies (company, status) VALUES ('Old Co','New')")
    raw.commit(); raw.close()

    conn = sqlite3.connect(legacy)
    conn.row_factory = sqlite3.Row
    db_mod._ensure_tenancy(conn)        # the additive migration alone
    row = conn.execute("SELECT uuid, tenant_id FROM agencies WHERE company='Old Co'").fetchone()
    conn.close()
    assert row["tenant_id"] == db_mod.DEFAULT_TENANT_ID   # backfilled existing row
    assert UUID_RE.match(row["uuid"] or "")               # backfilled a uuid too
