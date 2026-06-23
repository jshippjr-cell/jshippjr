"""Phase 1 Stripe wire-up — Checkout creation + webhook reconciliation.

The sandbox has no `stripe` package, so a fake module is injected into
`sys.modules`. This exercises the real provider logic (session args, amount in
cents, invoice-id reconciliation, idempotency) without the SDK or network.
"""

import importlib
import json
import sys
import types

import pytest


def _fake_stripe():
    """A minimal stand-in for the stripe SDK capturing the session kwargs."""
    created = {}

    class Session:
        @staticmethod
        def create(**kwargs):
            created.clear()
            created.update(kwargs)
            return types.SimpleNamespace(id="cs_test_123",
                                         url="https://checkout.stripe.com/c/pay/cs_test_123")

    class Webhook:
        @staticmethod
        def construct_event(body, sig, secret):  # signature "verified" by presence
            raw = body.decode() if isinstance(body, (bytes, bytearray)) else body
            return json.loads(raw)

    mod = types.ModuleType("stripe")
    mod.api_key = None
    mod.checkout = types.SimpleNamespace(Session=Session)
    mod.Webhook = Webhook
    mod._created = created
    return mod


@pytest.fixture()
def fake_stripe(monkeypatch):
    mod = _fake_stripe()
    monkeypatch.setitem(sys.modules, "stripe", mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)  # json-parse fallback
    return mod


def _provider():
    from chordential_oia.payments.stripe import StripePaymentProvider
    return StripePaymentProvider()


def test_create_checkout_builds_session_and_returns_url(fake_stripe):
    inv = {"id": 7, "project_id": 3, "kind": "Deposit", "amount": 1250.0,
           "note": "Deposit (50%) to begin work."}
    url = _provider().create_checkout(inv)
    assert url == "https://checkout.stripe.com/c/pay/cs_test_123"
    c = fake_stripe._created
    assert c["mode"] == "payment"
    assert c["client_reference_id"] == "7"
    assert c["metadata"] == {"invoice_id": "7", "kind": "Deposit"}
    li = c["line_items"][0]["price_data"]
    assert li["currency"] == "usd" and li["unit_amount"] == 125000  # dollars -> cents
    # Payer lands on a PUBLIC page, never the admin-gated project route.
    assert c["success_url"] == "https://chordential.com/?paid=7"
    assert c["cancel_url"] == "https://chordential.com/?canceled=7"


def test_handle_webhook_maps_paid_session_to_invoice(fake_stripe):
    event = {"type": "checkout.session.completed", "data": {"object": {
        "payment_status": "paid", "client_reference_id": "7",
        "payment_intent": "pi_1", "id": "cs_1"}}}
    out = _provider().handle_webhook({"body": json.dumps(event), "signature": ""})
    assert out == {"invoice_id": 7, "status": "Paid", "external_ref": "pi_1"}


def test_handle_webhook_ignores_unpaid_and_irrelevant(fake_stripe):
    unpaid = {"type": "checkout.session.completed", "data": {"object": {
        "payment_status": "unpaid", "client_reference_id": "7"}}}
    assert _provider().handle_webhook({"body": json.dumps(unpaid), "signature": ""}) == {}
    other = {"type": "customer.created", "data": {"object": {}}}
    assert _provider().handle_webhook({"body": json.dumps(other), "signature": ""}) == {}


# --------------------------------------------------------------------------- #
# Route integration: a paid webhook flips the invoice to Paid (idempotently).
# --------------------------------------------------------------------------- #
@pytest.fixture()
def stripe_app(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe())
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_PAYMENT_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from fastapi.testclient import TestClient
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _make_deposit_invoice(client, db_mod):
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    conn = db_mod.connect()
    opp_id = db_mod.insert_opportunity(conn, Opportunity(
        client="Acme", need="Original spot music",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8000, budget_max=15000,
    ))
    conn.close()
    pid = int(client.post(f"/opportunity/{opp_id}/project",
                          follow_redirects=False).headers["location"].split("/project/")[1])
    client.post(f"/project/{pid}/proposal")
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    conn = db_mod.connect()
    iid = db_mod.list_invoices(conn, pid)[0]["id"]
    conn.close()
    return iid


def test_webhook_route_marks_invoice_paid_idempotently(stripe_app):
    client, db_mod = stripe_app
    iid = _make_deposit_invoice(client, db_mod)
    event = {"type": "checkout.session.completed", "data": {"object": {
        "payment_status": "paid", "client_reference_id": str(iid),
        "payment_intent": "pi_live_1", "id": "cs_live_1"}}}
    r = client.post("/webhooks/stripe", content=json.dumps(event),
                    headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 200
    conn = db_mod.connect()
    inv = db_mod.get_invoice(conn, iid); conn.close()
    assert inv["status"] == "Paid"
    assert inv["external_ref"] == "pi_live_1"
    assert inv["paid_at"]

    # Re-delivery of the same event is a safe no-op.
    paid_at = inv["paid_at"]
    r2 = client.post("/webhooks/stripe", content=json.dumps(event),
                     headers={"stripe-signature": "t=1,v1=x"})
    assert r2.status_code == 200
    conn = db_mod.connect()
    inv2 = db_mod.get_invoice(conn, iid); conn.close()
    assert inv2["status"] == "Paid" and inv2["paid_at"] == paid_at
