"""Invoicing (Cycle 3.2) — deterministic, reconciles to the proposal.

Deposit + final invoices must sum to the proposal total; delivery completion
drafts the final invoice; Paid status persists with a timestamp.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.estimation import build_estimate
from chordential_oia.proposals import build_proposal
from chordential_oia.invoicing import build_invoice
from chordential_oia.web.evaluate import evaluate


def _sample_opp():
    return Opportunity(
        client="Acme Agency", need="Original :30 brand spot music",
        description="National campaign, original composition.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8000, budget_max=15000,
    )


def test_deposit_plus_final_reconcile_to_total():
    opp = _sample_opp()
    qual, _ = evaluate(opp)
    est = build_estimate(opp, qual.team_shape or qual.discipline.team_shape, qual.discipline)
    prop = build_proposal(opp, qual, est)
    deposit = build_invoice(prop, "Deposit")
    final = build_invoice(prop, "Final")
    assert deposit.amount == prop.deposit_amount
    assert final.amount == prop.balance_due
    assert round(deposit.amount + final.amount, 2) == round(prop.total_price, 2)


def test_invoice_render_text():
    opp = _sample_opp()
    qual, _ = evaluate(opp)
    est = build_estimate(opp, qual.team_shape or qual.discipline.team_shape, qual.discipline)
    prop = build_proposal(opp, qual, est)
    prop.client, prop.need = opp.client, opp.need
    text = build_invoice(prop, "Deposit").render_text()
    assert "INVOICE (Deposit)" in text and "Amount due" in text


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _project_with_proposal(client, db_mod):
    conn = db_mod.connect()
    opp_id = db_mod.insert_opportunity(conn, _sample_opp())
    conn.close()
    r = client.post(f"/opportunity/{opp_id}/project", follow_redirects=False)
    pid = int(r.headers["location"].split("/project/")[1])
    client.post(f"/project/{pid}/proposal")
    return pid


def test_create_invoices_and_reconcile(ctx):
    client, db_mod = ctx
    pid = _project_with_proposal(client, db_mod)
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    client.post(f"/project/{pid}/invoice", data={"kind": "Final"})
    conn = db_mod.connect()
    try:
        invs = db_mod.list_invoices(conn, pid)
        prop = db_mod.proposal_for_project(conn, pid)
    finally:
        conn.close()
    assert {i["kind"] for i in invs} == {"Deposit", "Final"}
    assert round(sum(i["amount"] for i in invs), 2) == round(prop["total_price"], 2)


def test_invoice_kind_not_duplicated(ctx):
    client, db_mod = ctx
    pid = _project_with_proposal(client, db_mod)
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    conn = db_mod.connect()
    try:
        n = len(db_mod.list_invoices(conn, pid))
    finally:
        conn.close()
    assert n == 1


def test_mark_paid_persists_timestamp(ctx):
    client, db_mod = ctx
    pid = _project_with_proposal(client, db_mod)
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    conn = db_mod.connect()
    iid = db_mod.list_invoices(conn, pid)[0]["id"]
    conn.close()
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"})
    conn = db_mod.connect()
    try:
        inv = db_mod.get_invoice(conn, iid)
    finally:
        conn.close()
    assert inv["status"] == "Paid"
    assert inv["paid_at"]


def test_all_milestones_done_drafts_final_invoice(ctx):
    client, db_mod = ctx
    pid = _project_with_proposal(client, db_mod)
    conn = db_mod.connect()
    milestones = db_mod.list_milestones(conn, pid)
    conn.close()
    assert milestones, "project should have seeded milestones"
    # Mark every milestone Done.
    for m in milestones:
        client.post(
            f"/project/{pid}/milestone/status",
            data={"milestone_id": m["id"], "status": "Done"},
        )
    conn = db_mod.connect()
    try:
        finals = [i for i in db_mod.list_invoices(conn, pid) if i["kind"] == "Final"]
    finally:
        conn.close()
    assert len(finals) == 1     # delivery completion drafted exactly one final invoice
