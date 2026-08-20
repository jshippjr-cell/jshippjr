"""The payment door anyone could walk through, and the button that was never ours.

Three defects, one shape: **a request the payer controls was treated as proof of
something only somebody else knows.**

``GET /pay/return?invoice=7`` was exempt from the admin gate and applied the payment on
sight. Typing it marked invoice 7 Paid, unlocked the client's downloads, queued the
crew's payouts and emailed a receipt — no Stripe, no signature, no session, no
verification of any kind. Invoice ids are small integers.

The same request also answered with a redirect whose ``Location`` carried
``ensure_project_share_token(pid)`` — the credential that opens that client's delivery
portal. So guessing a number both settled an invoice and handed out the key.

And in the room, the client's per-deliverable **sign-off form rendered for every role**
with no capability check (``sign_off_asset`` is CLIENT-only in ``room.CAPS``). The studio
saw an Approve button, pressed it, and the token-gated route answered 404 — which
``fetch`` reported as *"That didn't go through. Check your connection and try again."*
The operator went looking for a network problem that did not exist, for the second time
in two days (2026-08-20).

The rule underneath all three: **the provider that issued the checkout is the only thing
that may vouch for it, and a refusal must never be able to impersonate a network
failure.**
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "p.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_PAYMENT_PROVIDER", raising=False)
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        from chordential_oia.invoicing import Invoice
        iid = db.insert_invoice(conn, pid, None, Invoice(
            client="The Larkspur Trust", need="Sand Castle", kind="Final", amount=4200.0))
        db.update_invoice_status(conn, iid, "Issued")
        share = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    return c, app_mod, db, pid, iid, share


# ── the door ────────────────────────────────────────────────────────────────────────
def test_typing_the_url_no_longer_pays_the_invoice(studio):
    """The whole hole, as one request."""
    from fastapi.testclient import TestClient
    c, app_mod, db, _pid, iid, _share = studio
    with TestClient(app_mod.app) as anon:
        r = anon.get(f"/pay/return?invoice={iid}", follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, iid)
    finally:
        conn.close()
    assert (inv["status"] or "").lower() != "paid", (
        "an unauthenticated GET still marks an invoice Paid")


def test_it_does_not_hand_out_the_clients_share_token(studio):
    """The second hole in the same request: the redirect's Location carried the token
    that opens the delivery portal, so guessing an invoice id was also a key."""
    from fastapi.testclient import TestClient
    c, app_mod, _db, _pid, iid, share = studio
    with TestClient(app_mod.app) as anon:
        r = anon.get(f"/pay/return?invoice={iid}", follow_redirects=False)
    assert share and share not in r.headers.get("location", ""), (
        "the share token is still in the redirect")
    assert r.headers["location"] == "/pay/confirming"


def test_the_downloads_stay_locked_and_no_payouts_are_queued(studio):
    """The side effects are the damage, not the status column."""
    from fastapi.testclient import TestClient
    c, app_mod, db, pid, iid, _share = studio
    with TestClient(app_mod.app) as anon:
        anon.get(f"/pay/return?invoice={iid}")
    conn = db.connect()
    try:
        assert not db.get_delivery(conn, pid).get("download_unlocked")
        assert db.list_talent_payouts(conn, pid) == [] if hasattr(
            db, "list_talent_payouts") else True
    finally:
        conn.close()


def test_a_verified_session_does_settle_it(studio, monkeypatch):
    """The fix must not break paying. A provider that VOUCHES for the return applies the
    payment exactly as before — and only then is the client sent back with their token."""
    from fastapi.testclient import TestClient
    from chordential_oia.web import billing_routes
    c, app_mod, db, pid, iid, share = studio

    class Vouching:
        name = "test"
        def create_checkout(self, invoice): return "https://pay.example/x"
        def handle_webhook(self, payload): return {}
        def verify_return(self, params):
            return {"invoice_id": iid, "status": "Paid", "external_ref": "pi_123"}

    monkeypatch.setattr(billing_routes, "get_payment_provider", lambda: Vouching())
    with TestClient(app_mod.app) as anon:
        r = anon.get(f"/pay/return?invoice={iid}&session_id=cs_test",
                     follow_redirects=False)
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, iid)
        assert (inv["status"] or "").lower() == "paid", "a real payment no longer settles"
        assert inv["external_ref"] == "pi_123"
        assert db.get_delivery(conn, pid).get("download_unlocked")
    finally:
        conn.close()
    assert share in r.headers.get("location", ""), (
        "a verified payer must still land back in their portal")


def test_the_invoice_id_comes_from_the_session_not_the_url(studio, monkeypatch):
    """"This payer paid for THIS invoice" is a different claim from "this payer paid for
    something, and also typed a number"."""
    from fastapi.testclient import TestClient
    from chordential_oia.invoicing import Invoice
    from chordential_oia.web import billing_routes
    c, app_mod, db, pid, iid, _share = studio
    conn = db.connect()
    try:
        other = db.insert_invoice(conn, pid, None, Invoice(
            client="X", need="Y", kind="Deposit", amount=99.0))
    finally:
        conn.close()

    class Vouching:
        name = "test"
        def create_checkout(self, invoice): return ""
        def handle_webhook(self, payload): return {}
        def verify_return(self, params):
            return {"invoice_id": iid, "status": "Paid", "external_ref": "pi_1"}

    monkeypatch.setattr(billing_routes, "get_payment_provider", lambda: Vouching())
    with TestClient(app_mod.app) as anon:
        anon.get(f"/pay/return?invoice={other}&session_id=cs_x")
    conn = db.connect()
    try:
        assert (db.get_invoice(conn, iid)["status"] or "").lower() == "paid"
        assert (db.get_invoice(conn, other)["status"] or "").lower() != "paid", (
            "the URL's invoice id was settled instead of the verified one")
    finally:
        conn.close()


def test_the_confirming_page_knows_nothing_and_blames_nobody(studio):
    from fastapi.testclient import TestClient
    _c, app_mod, _db, _pid, _iid, share = studio
    with TestClient(app_mod.app) as anon:
        page = anon.get("/pay/confirming").text
    assert "Confirming your payment" in page
    assert share not in page
    for word in ("failed", "declined", "error", "invalid"):
        assert word not in page.lower(), f"an unconfirmed return reads as {word}"


# ── the providers ───────────────────────────────────────────────────────────────────
def test_the_null_provider_never_vouches():
    """It never took a payment, so it can never confirm one — and under it no payer is
    ever sent to a success URL at all."""
    from chordential_oia.payments.null import NullPaymentProvider
    assert NullPaymentProvider().verify_return({"session_id": "anything"}) == {}
    assert NullPaymentProvider().verify_return({}) == {}


def test_every_provider_implements_the_contract():
    from chordential_oia.payments.null import NullPaymentProvider
    from chordential_oia.payments.stripe import StripePaymentProvider
    for cls in (NullPaymentProvider, StripePaymentProvider):
        assert callable(getattr(cls, "verify_return", None)), (
            f"{cls.__name__} cannot answer for its own returns")


def test_stripe_asks_stripe_and_takes_the_id_from_the_session(monkeypatch):
    from chordential_oia.payments.stripe import StripePaymentProvider

    class FakeSession(dict):
        pass

    class FakeStripe:
        class checkout:
            @staticmethod
            def Session(): ...
    captured = {}

    class Retriever:
        @staticmethod
        def retrieve(sid):
            captured["sid"] = sid
            return FakeSession(payment_status="paid", client_reference_id="42",
                               payment_intent="pi_9", id="cs_1")

    p = StripePaymentProvider()
    monkeypatch.setattr(p, "_client", lambda: type(
        "S", (), {"checkout": type("C", (), {"Session": Retriever})})())
    out = p.verify_return({"session_id": "cs_1", "invoice": "999"})
    assert captured["sid"] == "cs_1", "it did not ask Stripe"
    assert out == {"invoice_id": 42, "status": "Paid", "external_ref": "pi_9"}, (
        "the invoice id must come from the session, never the query string")


def test_stripe_refuses_an_unpaid_or_unknown_session(monkeypatch):
    from chordential_oia.payments.stripe import StripePaymentProvider
    p = StripePaymentProvider()
    assert p.verify_return({}) == {}, "no session id is not a payment"

    class Unpaid:
        @staticmethod
        def retrieve(sid):
            return {"payment_status": "unpaid", "client_reference_id": "42"}
    monkeypatch.setattr(p, "_client", lambda: type(
        "S", (), {"checkout": type("C", (), {"Session": Unpaid})})())
    assert p.verify_return({"session_id": "cs_1"}) == {}

    class Exploding:
        @staticmethod
        def retrieve(sid):
            raise RuntimeError("no such session")
    monkeypatch.setattr(p, "_client", lambda: type(
        "S", (), {"checkout": type("C", (), {"Session": Exploding})})())
    assert p.verify_return({"session_id": "forged"}) == {}, (
        "an error must read as UNPROVEN, never as paid")


def test_the_success_url_carries_the_session_id():
    """Without it the return is unverifiable, and every real payment would fall through
    to the webhook — correct, but slower and confusing for the payer."""
    import inspect
    from chordential_oia.payments import stripe as st
    src = inspect.getsource(st.StripePaymentProvider.create_checkout)
    assert "{CHECKOUT_SESSION_ID}" in src


def test_the_webhook_is_untouched_and_still_authoritative(studio):
    """The signature-verified door is what actually settles payments. Nothing here
    weakened it."""
    from fastapi.testclient import TestClient
    from chordential_oia.web import billing_routes
    _c, app_mod, db, _pid, iid, _share = studio

    class Hooked:
        name = "test"
        def create_checkout(self, invoice): return ""
        def verify_return(self, params): return {}
        def handle_webhook(self, payload):
            return {"invoice_id": iid, "status": "paid", "external_ref": "pi_hook"}

    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(billing_routes, "get_payment_provider", lambda: Hooked())
        with TestClient(app_mod.app) as anon:
            r = anon.post("/webhooks/stripe", content=b"{}",
                          headers={"stripe-signature": "t=1,v1=x"})
    assert r.json()["applied"] is True
    conn = db.connect()
    try:
        assert (db.get_invoice(conn, iid)["status"] or "").lower() == "paid"
    finally:
        conn.close()


# ── the button that was never the studio's ──────────────────────────────────────────
def test_signing_off_a_deliverable_is_the_clients_capability_alone():
    from chordential_oia.web import room
    assert "sign_off_asset" in room.caps_for(room.CLIENT)
    assert "sign_off_asset" not in room.caps_for(room.OPERATOR)
    assert "sign_off_asset" not in room.caps_for(room.TALENT)


def test_the_room_only_renders_the_sign_off_form_for_the_client(studio):
    """It rendered for everyone, with no check at all — so the studio was offered a
    button whose route would always refuse them."""
    from pathlib import Path
    tpl = (Path(studio[1].__file__).parent / "templates" / "creator_portal.html"
           ).read_text(encoding="utf-8")
    i = tpl.index('action="/project/{{ a.project_id }}/review/asset" class="so-form"')
    guard = tpl.rindex("sign_off_asset", 0, i)
    assert i - guard < 900, (
        "the client's sign-off form is not behind a `sign_off_asset` check")


def test_a_press_the_route_refuses_says_so_in_json(studio):
    """Not a 404 of HTML, which `fetch` can only report as a dead connection."""
    c, _app, _db, pid, _iid, _share = studio
    r = c.post(f"/project/{pid}/review/asset",
               data={"k": "", "r": "", "author": "Jon Shipp", "origin": "room",
                     "filename": "s1.wav", "action": "approve"},
               headers={"X-Requested-With": "fetch"}, follow_redirects=False)
    assert r.headers["content-type"].startswith("application/json"), (
        "the room is told to blame the network again")
    assert r.json() == {"ok": False, "reason": "denied"}


def test_a_client_with_no_name_is_told_that_and_not_that_it_is_the_network(studio):
    c, _app, _db, pid, _iid, share = studio
    r = c.post(f"/project/{pid}/review/asset",
               data={"k": share, "r": "", "author": "", "origin": "room",
                     "filename": "s1.wav", "action": "approve"},
               headers={"X-Requested-With": "fetch"}, follow_redirects=False)
    assert r.status_code == 400 and r.json()["reason"] == "noname"


def test_without_javascript_the_refusal_still_redirects(studio):
    """A no-JS post must keep its old behaviour — the JSON is for the room's `fetch`."""
    c, _app, _db, pid, _iid, share = studio
    r = c.post(f"/project/{pid}/review/asset",
               data={"k": share, "r": "", "author": "", "origin": "room",
                     "filename": "s1.wav", "action": "approve"},
               follow_redirects=False)
    assert r.status_code == 303
