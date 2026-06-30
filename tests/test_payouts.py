"""Payout ledger — pay the crew (Owed → Paid, off-platform, W-9-gated).

Owed rows are generated when a client invoice is marked Paid; Jon pays off-platform
and marks each Paid, which requires a W-9 on file. Generation is idempotent.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _paid_project(db_mod, rate=1200, rate_unit="project"):
    """Create a composer + project + assignment + an Issued Final invoice; return
    (talent_id, project_id, invoice_id)."""
    from chordential_oia.talent import Talent, ReviewStatus
    from chordential_oia.models import MusicDiscipline
    conn = db_mod.connect()
    try:
        tid = db_mod.insert_talent(conn, Talent(
            name="Mara Velez", disciplines=[MusicDiscipline.COMPOSITION],
            review_status=ReviewStatus.APPROVED, rate=rate, rate_unit=rate_unit,
        ))
        pid = db_mod.insert_project(conn, None, "AURORA", "Brand anthem", 0, 5000,
                                    ["Composer"], "2026-08-01")
        db_mod.add_assignment(conn, pid, "Composer", tid)
        cur = conn.execute(
            "INSERT INTO invoices (project_id, kind, status, amount, created_at) "
            "VALUES (?,?,?,?,?)", (pid, "Final", "Issued", 5000, "2026-06-30"))
        iid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return tid, pid, iid


def test_payout_generated_on_invoice_paid(ctx):
    client, db_mod = ctx
    tid, pid, iid = _paid_project(db_mod)
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})
    conn = db_mod.connect()
    try:
        pos = db_mod.list_payouts(conn)
    finally:
        conn.close()
    assert len(pos) == 1
    assert pos[0]["amount"] == 1200.0       # seeded from the project-flat rate
    assert pos[0]["status"] == "Owed"


def test_generation_is_idempotent(ctx):
    client, db_mod = ctx
    tid, pid, iid = _paid_project(db_mod)
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})  # again
    conn = db_mod.connect()
    try:
        assert len(db_mod.list_payouts(conn)) == 1   # not duplicated
    finally:
        conn.close()


def test_pay_blocked_without_w9(ctx):
    client, db_mod = ctx
    tid, pid, iid = _paid_project(db_mod)
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})
    conn = db_mod.connect()
    poid = db_mod.list_payouts(conn)[0]["id"]
    conn.close()
    r = client.post(f"/payouts/{poid}/pay", data={"reference": "Zelle 1"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "err=w9" in r.headers["location"]
    conn = db_mod.connect()
    try:
        assert db_mod.get_payout(conn, poid)["status"] == "Owed"  # still owed
    finally:
        conn.close()


def test_pay_succeeds_with_w9(ctx):
    client, db_mod = ctx
    tid, pid, iid = _paid_project(db_mod)
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})
    conn = db_mod.connect()
    poid = db_mod.list_payouts(conn)[0]["id"]
    conn.close()
    client.post(f"/talent/{tid}/w9", data={"received": "1"})
    client.post(f"/payouts/{poid}/pay", data={"reference": "Zelle 1"})
    conn = db_mod.connect()
    try:
        po = db_mod.get_payout(conn, poid)
    finally:
        conn.close()
    assert po["status"] == "Paid"
    assert po["reference"] == "Zelle 1"
    assert po["paid_at"]


def test_edit_and_unpay(ctx):
    client, db_mod = ctx
    tid, pid, iid = _paid_project(db_mod, rate=100, rate_unit="hourly")
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})
    conn = db_mod.connect()
    poid = db_mod.list_payouts(conn)[0]["id"]
    conn.close()
    # Edit hours/amount on the Owed payout.
    client.post(f"/payouts/{poid}", data={"qty": "8", "amount": "800", "reference": ""})
    conn = db_mod.connect()
    assert db_mod.get_payout(conn, poid)["amount"] == 800.0
    conn.close()
    # Pay then undo.
    client.post(f"/talent/{tid}/w9", data={"received": "1"})
    client.post(f"/payouts/{poid}/pay", data={"reference": "ACH"})
    client.post(f"/payouts/{poid}/unpay")
    conn = db_mod.connect()
    try:
        po = db_mod.get_payout(conn, poid)
    finally:
        conn.close()
    assert po["status"] == "Owed"
    assert po["paid_at"] is None


def test_ledger_page_renders(ctx):
    client, _ = ctx
    r = client.get("/payouts")
    assert r.status_code == 200
    assert "Payout Ledger" in r.text
