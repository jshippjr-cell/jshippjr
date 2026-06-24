"""Boot the whole app on Postgres and exercise it end-to-end.

Resets the Postgres schema, then runs the FastAPI lifespan (init_db + full demo
seed = hundreds of inserts/queries) on Postgres and hits key routes + a write
flow. The strongest single proof that the SQLite→Postgres shim holds for the
real app, not just isolated functions.
"""
import os

PG = "postgresql://postgres@localhost:5433/chordtest"
os.environ["CHORDENTIAL_DB"] = PG
os.environ["CHORDENTIAL_SEED_DEMO"] = "1"   # heavy seed path = lots of DB work
os.environ.pop("CHORDENTIAL_ADMIN_TOKEN", None)

import psycopg
with psycopg.connect(PG, autocommit=True) as c:
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

from fastapi.testclient import TestClient
from chordential_oia.web.app import app
from chordential_oia.web import db
from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

fails = []
with TestClient(app) as client:                      # lifespan: init_db + seed on PG
    for path in ["/", "/dashboard", "/signals", "/samples", "/sources",
                 "/lanes", "/inbox", "/talent", "/projects", "/buyers"]:
        r = client.get(path)
        flag = "ok  " if r.status_code == 200 else "FAIL"
        if r.status_code != 200:
            fails.append((path, r.status_code))
        print(f"  {flag} GET {path} -> {r.status_code}")

    # Write flow: opportunity -> project -> proposal -> deposit invoice (exercises
    # inserts/lastrowid, proposal math, invoice reconcile — all on Postgres).
    conn = db.connect()
    oid = db.insert_opportunity(conn, Opportunity(
        client="Smoke Agency", need="Original anthem for launch",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=9000, budget_max=15000))
    conn.commit(); conn.close()
    loc = client.post(f"/opportunity/{oid}/project", follow_redirects=False).headers["location"]
    pid = int(loc.split("/project/")[1])
    client.post(f"/project/{pid}/proposal")
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    conn = db.connect()
    invs = db.list_invoices(conn, pid)
    proj = client.get(f"/project/{pid}").status_code        # GROUP_CONCAT crew query
    conn.close()
    print(f"  {'ok  ' if invs else 'FAIL'} write flow: opp {oid} -> project {pid} -> {len(invs)} invoice(s)")
    print(f"  {'ok  ' if proj==200 else 'FAIL'} GET /project/{pid} (crew GROUP_CONCAT) -> {proj}")
    if not invs or proj != 200:
        fails.append(("write-flow", invs and proj))

print(f"\n{'ALL OK' if not fails else 'FAILURES: ' + str(fails)}")
raise SystemExit(1 if fails else 0)
