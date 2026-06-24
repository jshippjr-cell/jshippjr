"""Postgres parity check — exercise the db shim against a real Postgres.

Run a fresh schema on Postgres and drive a representative set of db functions
(insert + lastrowid, upserts/ON CONFLICT, LIKE search, GROUP_CONCAT, positional
row access, idempotent _ensure_schema). Proves the SQLite→Postgres shim works.

Usage:  CHORDENTIAL_DB=postgresql://postgres@localhost:5433/chordtest \
        python scripts/pg_parity_check.py
"""
import os
import sys

URL = os.environ["CHORDENTIAL_DB"]
assert URL.startswith(("postgres://", "postgresql://")), "point CHORDENTIAL_DB at Postgres"

import psycopg
from chordential_oia.web import db
from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

# Fresh schema each run.
with psycopg.connect(URL.replace("postgres://", "postgresql://", 1), autocommit=True) as c:
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

ok, fail = [], []
def check(name, fn):
    try:
        fn(); ok.append(name); print(f"  ok   {name}")
    except Exception as e:
        fail.append(name); print(f"  FAIL {name}: {type(e).__name__}: {e}")

conn = db.connect(URL)

check("init_db (schema create)", lambda: db.init_db(conn))
check("_ensure_schema idempotent re-run", lambda: db._ensure_schema(conn))

state = {}
def _insert():
    state["oid"] = db.insert_opportunity(conn, Opportunity(
        client="Acme Co", need="Original spot music for our launch",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8000, budget_max=15000))
    conn.commit()
    assert isinstance(state["oid"], int) and state["oid"] > 0, state.get("oid")
check("insert_opportunity → lastrowid (RETURNING id)", _insert)

check("get_opportunity (row['col'] access)",
      lambda: (db.get_opportunity(conn, state["oid"])["client"] == "Acme Co") or (_ for _ in ()).throw(AssertionError("client mismatch")))
check("list_opportunities (read many)", lambda: db.list_opportunities(conn))

def _count_positional():
    n = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]   # positional row[0]
    assert n == 1, n
check("COUNT(*).fetchone()[0] (positional row)", _count_positional)

def _like():
    rows = db.list_opportunities(conn, q="launch")  # exercises LIKE ?
    assert any(r["id"] == state["oid"] for r in rows), "LIKE search missed it"
check("LIKE search (% in params)", _like)

# Upsert paths (ON CONFLICT). brief_progress uses ON CONFLICT(opp_id, step_key).
def _upsert_brief():
    db.set_brief_step(conn, state["oid"], "first_touch", True)
    db.set_brief_step(conn, state["oid"], "first_touch", True)  # conflict → update
    conn.commit()
    assert "first_touch" in db.brief_done_keys(conn, state["oid"])
check("ON CONFLICT upsert (brief_progress)", _upsert_brief)

# source_meta upsert: ON CONFLICT(source_key).
def _upsert_cost():
    db.set_source_cost(conn, "mandy", 29.0, "test")
    db.set_source_cost(conn, "mandy", 39.0, "test2")  # conflict → update
    conn.commit()
    assert db.get_source_costs(conn)["mandy"]["monthly_cost"] == 39.0
check("ON CONFLICT upsert (source_meta cost)", _upsert_cost)

# A signal insert (lastrowid) + indicator filter (IFNULL).
def _signal():
    sid = db.insert_signal(conn, source="reddit", source_weight=5, title="Composer needed",
                           external_ref="ext-1")
    conn.commit()
    assert isinstance(sid, int) and sid > 0
    assert any(r["external_ref"] == "ext-1" for r in db.list_signals(conn))
check("insert_signal + list_signals (IFNULL filter)", _signal)

conn.close()
print(f"\n{len(ok)} ok, {len(fail)} failed")
sys.exit(1 if fail else 0)
