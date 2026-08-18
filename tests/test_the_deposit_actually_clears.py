"""The deposit, through Stripe, from the client's own workspace.

Stripe has been configured and tested — but against the FINAL invoice from the delivery
portal, which is the path that existed. The deposit button on the client's workspace only
became reachable when countersigning started writing the project's proposal (ADR-0067),
and a Pay button is not finished when it renders: it is finished when the money lands and
the thing it was blocking moves.

So this walks the whole deposit: the client presses Pay on her workspace, Stripe returns a
hosted Checkout URL, the webhook reports the capture, and Kickoff stops asking. The
`stripe` SDK is faked into `sys.modules` — the sandbox has no package and no network — so
what is exercised is the real provider, the real routes and the real reconciliation.
"""
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


def _fake_stripe():
    created = {}

    class Session:
        @staticmethod
        def create(**kwargs):
            created.clear()
            created.update(kwargs)
            return types.SimpleNamespace(
                id="cs_test_deposit",
                url="https://checkout.stripe.com/c/pay/cs_test_deposit")

    class Webhook:
        @staticmethod
        def construct_event(body, sig, secret):
            raw = body.decode() if isinstance(body, (bytes, bytearray)) else body
            return json.loads(raw)

    mod = types.ModuleType("stripe")
    mod.api_key = None
    mod.checkout = types.SimpleNamespace(Session=Session)
    mod.Webhook = Webhook
    mod._created = created
    return mod


@pytest.fixture()
def paying(tmp_path, monkeypatch):
    """A studio with Stripe switched on, exactly as production has it."""
    stripe_mod = _fake_stripe()
    monkeypatch.setitem(sys.modules, "stripe", stripe_mod)
    monkeypatch.setenv("CHORDENTIAL_PAYMENT_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "pay.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as jon:
        jon.post("/admin/login", data={"email": "", "password": "passphrase"},
                 follow_redirects=False)
        yield jon, app_mod, stripe_mod


def _closed_deal(jon, app_mod):
    """Client signs, operator countersigns — the state the deposit exists in."""
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    db = app_mod.db
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn = db.connect()
    try:
        opp_id = None
        for r in conn.execute("SELECT id FROM opportunities ORDER BY id").fetchall():
            if not db.list_meetings(conn, r["id"]):
                db.create_meeting(conn, opp_id=r["id"], start_at=past, status="ingested")
            conn.execute("UPDATE meetings SET start_at=?, status='ingested' WHERE opp_id=?",
                         (past, r["id"]))
            conn.commit()
            _r, _o, _e, doc, _d = agreement_doc_for(conn, r["id"])
            if getattr(getattr(doc, "agreement", None), "price_low", None):
                opp_id = r["id"]
                break
        if opp_id is None:
            pytest.skip("no signable demo deal")
        token = db.ensure_share_token(conn, opp_id)
    finally:
        conn.close()
    from fastapi.testclient import TestClient
    client = TestClient(app_mod.app)
    client.post(f"/workspace/{token}/sign",
                data={"typed_name": "Marta Reyes", "signer_email": "marta@example.com",
                      "consent": "1"}, follow_redirects=False)
    jon.post(f"/opportunity/{opp_id}/countersign",
             data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        pid = app_mod.db.project_for_opp(conn, opp_id)["id"]
        ptok = app_mod.db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    return client, token, pid, ptok


# ── the provider is really selected ─────────────────────────────────────────────────
def test_stripe_is_the_provider_when_configured(paying):
    from chordential_oia.payments import get_payment_provider
    assert get_payment_provider().name == "stripe"


# ── pressing Pay reaches a real hosted checkout ─────────────────────────────────────
def test_the_deposit_button_opens_a_hosted_checkout(paying):
    jon, app_mod, stripe_mod = paying
    client, _token, pid, ptok = _closed_deal(jon, app_mod)

    r = client.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("https://checkout.stripe.com/"), (
        f"the client was not sent to Stripe: {r.headers['location']}")

    sent = stripe_mod._created
    assert sent["mode"] == "payment"
    # The DEPOSIT, not the full fee — this is the number the client signed.
    conn = app_mod.db.connect()
    try:
        prop = app_mod.db.proposal_for_project(conn, pid)
        invoice = next(i for i in app_mod.db.list_invoices(conn, pid)
                       if i["kind"] == "Deposit")
    finally:
        conn.close()
    assert sent["line_items"][0]["price_data"]["unit_amount"] == int(
        round(prop["deposit_amount"] * 100)), "Stripe was asked for the wrong amount"
    assert sent["client_reference_id"] == str(invoice["id"]), (
        "no invoice id on the session — the webhook cannot reconcile it")
    assert "/pay/return" in sent["success_url"]


def test_the_invoice_is_marked_issued_and_holds_the_checkout_url(paying):
    jon, app_mod, _stripe = paying
    client, _token, pid, ptok = _closed_deal(jon, app_mod)
    client.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        inv = next(i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == "Deposit")
    finally:
        conn.close()
    assert inv["status"] == "Issued"
    assert (inv["external_ref"] or "").startswith("https://checkout.stripe.com/")


# ── the money lands, and the thing it was blocking moves ────────────────────────────
def _webhook(jon, invoice_id):
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_deposit", "payment_status": "paid",
                            "client_reference_id": str(invoice_id),
                            "payment_intent": "pi_test_deposit"}},
    }
    return jon.post("/webhooks/stripe", content=json.dumps(event).encode(),
                    headers={"stripe-signature": "t=1,v1=x"})


def test_the_capture_clears_the_kickoff_ask(paying):
    """The whole point. A paid deposit that leaves the client still being asked for it
    is worse than no button — she has paid and the page says she hasn't."""
    jon, app_mod, _stripe = paying
    client, token, pid, ptok = _closed_deal(jon, app_mod)

    before = client.get(f"/workspace/{token}").text
    assert "Send your deposit" in before
    assert "Pay deposit" in before

    client.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        inv = next(i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == "Deposit")
    finally:
        conn.close()
    assert _webhook(jon, inv["id"]).status_code == 200

    conn = app_mod.db.connect()
    try:
        paid = next(i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == "Deposit")
    finally:
        conn.close()
    assert (paid["status"] or "").lower() in ("paid", "settled")

    after = client.get(f"/workspace/{token}").text
    assert "Send your deposit" not in after, "it still asked for a deposit already paid"
    assert "Pay deposit" not in after, "it still offered to charge her again"
    assert "Deposit received" in after or "Everything is ready" in after


def test_paying_twice_is_refused_rather_than_charged_twice(paying):
    jon, app_mod, _stripe = paying
    client, _token, pid, ptok = _closed_deal(jon, app_mod)
    client.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        inv = next(i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == "Deposit")
    finally:
        conn.close()
    _webhook(jon, inv["id"])
    again = client.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                        follow_redirects=False)
    assert "pay=already" in again.headers.get("location", ""), (
        "a settled deposit opened a second checkout")


def test_the_webhook_is_idempotent(paying):
    """Stripe retries. Twice-delivered must not mean twice-recorded."""
    jon, app_mod, _stripe = paying
    client, _token, pid, ptok = _closed_deal(jon, app_mod)
    client.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        inv = next(i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == "Deposit")
    finally:
        conn.close()
    assert _webhook(jon, inv["id"]).status_code == 200
    assert _webhook(jon, inv["id"]).status_code == 200
    conn = app_mod.db.connect()
    try:
        deposits = [i for i in app_mod.db.list_invoices(conn, pid) if i["kind"] == "Deposit"]
    finally:
        conn.close()
    assert len(deposits) == 1
    assert (deposits[0]["status"] or "").lower() in ("paid", "settled")


# ── the payer never meets the login ─────────────────────────────────────────────────
def test_the_payer_is_never_asked_to_log_in(paying):
    """She is a buyer with a link, not a user. The pay route and Stripe's return page
    are both hers."""
    from fastapi.testclient import TestClient
    jon, app_mod, _stripe = paying
    _client, _token, pid, ptok = _closed_deal(jon, app_mod)
    with TestClient(app_mod.app) as buyer:          # a fresh client == no admin cookie
        r = buyer.post(f"/project/{pid}/pay", data={"k": ptok, "kind": "deposit"},
                       follow_redirects=False)
        assert "/admin/login" not in r.headers.get("location", "")
        assert r.headers["location"].startswith("https://checkout.stripe.com/")
        back = buyer.get("/pay/return?invoice=1", follow_redirects=False)
        assert back.status_code in (200, 303)
        if back.status_code == 303:
            assert "/admin/login" not in back.headers.get("location", "")
