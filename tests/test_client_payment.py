"""Client-facing payment: token-gated checkout + the signature-verified Stripe webhook.

The buyer pays the deposit (workspace) and the final invoice (delivery portal) through the
provider seam. Access is by the client's own share token — it must work even with the admin
gate ON. The webhook is the authoritative, idempotent payment confirmation.
"""
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.models import (  # noqa: E402
    Opportunity, BuyerType, MusicRequirement)
from chordential_oia.proposals import Proposal  # noqa: E402


def _app(tmp_path, monkeypatch, admin=True):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    if admin:
        monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")  # gate ON
    for m in ("db", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _seed(app_mod, kind="Final"):
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="X", need="Campaign", description="x", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0))
    pid = app_mod.db.insert_project(conn, oid, "X", "Campaign", 0, 0, ["Composer"])
    ptok = app_mod.db.ensure_project_share_token(conn, pid)
    app_mod.db.insert_proposal(conn, pid, oid, Proposal(
        client="X", need="Campaign", discipline="Composition", lines=[], total_price=30000.0,
        deposit_pct=0.5, deposit_amount=15000.0, balance_due=15000.0, terms=[]))
    app_mod.db.insert_invoice(conn, pid, None, app_mod._invoice_from_proposal_row(
        app_mod.db.get_project(conn, pid), app_mod.db.proposal_for_project(conn, pid), kind))
    inv = next(i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == kind)
    conn.close()
    return oid, pid, ptok, inv["id"]


def test_client_pay_route_is_exempt_from_admin_gate(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch, admin=True)
    _oid, pid, ptok, _inv = _seed(app_mod)
    with TestClient(app_mod.app) as c:
        r = c.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "final"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" not in (r.headers.get("location") or "")   # not bounced to login


def test_stripe_webhook_marks_paid_unlocks_and_is_idempotent(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch, admin=True)
    _oid, pid, ptok, inv_id = _seed(app_mod, kind="Final")

    class FakeProvider:
        def handle_webhook(self, payload):
            return {"invoice_id": inv_id, "status": "Paid", "external_ref": "pi_123"}

    monkeypatch.setattr(app_mod, "get_payment_provider", lambda: FakeProvider())
    with TestClient(app_mod.app) as c:
        w1 = c.post("/webhooks/stripe", content=b"{}",
                    headers={"Stripe-Signature": "t=1,v1=x"})
        assert w1.status_code == 200 and w1.json()["applied"] is True
        w2 = c.post("/webhooks/stripe", content=b"{}",
                    headers={"Stripe-Signature": "t=1,v1=x"})
        assert w2.json()["applied"] is False        # idempotent — already paid

    conn = app_mod.db.connect()
    iv = app_mod.db.get_invoice(conn, inv_id)
    d = app_mod.db.get_delivery(conn, pid)
    conn.close()
    assert (iv["status"] or "").lower() == "paid"
    assert iv["external_ref"] == "pi_123"
    assert d.get("download_unlocked")               # final payment unlocks the client download


def test_webhook_rejects_a_bad_signature(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch, admin=True)

    class RaisingProvider:
        def handle_webhook(self, payload):
            raise ValueError("bad signature")

    monkeypatch.setattr(app_mod, "get_payment_provider", lambda: RaisingProvider())
    with TestClient(app_mod.app) as c:
        r = c.post("/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "bad"})
    assert r.status_code == 400
