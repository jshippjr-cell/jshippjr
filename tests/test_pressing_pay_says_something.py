"""A payment that cannot start has to say so.

Reported live (operator, 2026-08-19): *"after approving all the deliverable i want the
pay remaining balance to unlock download to pop up. right now it pops up in the client
delivery workspace, and when it click it it does nothing."*

Two defects, and the second is the one that matters.

**`/pay` required a PROPOSAL even when the invoice already existed.** The proposal is
only needed to raise an invoice that has not been raised yet — and the final invoice is
issued at ship time by `_ensure_final_invoice_issued`. So a delivery that had reached the
paywall the normal way bounced straight off that line.

**And it bounced in silence.** Four flags leave that route and exactly one of them,
`unavailable`, was rendered anywhere. The other three reloaded the page with nothing on
it changed. On a payment button, silence reads as broken — which is what it was.
"""
import pytest
from fastapi.testclient import TestClient

from chordential_oia.invoicing import Invoice
from chordential_oia.web.billing import PAY_NOTICES, pay_notice


@pytest.fixture()
def portal(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db
    c = TestClient(app_mod.app)
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])
    ktok = db.rotate_share_token(conn, project_id=pid)
    conn.close()
    return c, db, pid, ktok


# ── the invoice is enough ───────────────────────────────────────────────────────────
def test_pay_works_when_the_invoice_already_exists(portal):
    """The exact silent case: an issued final invoice and no proposal row. It used to
    return `pay=error`, which nothing rendered."""
    c, db, pid, ktok = portal
    conn = db.connect()
    iid = db.insert_invoice(conn, pid, None, Invoice(client="The Larkspur Trust",
                                                     need="Sand Castle", kind="Final",
                                                     amount=4200.0))
    db.update_invoice_status(conn, iid, "Issued")
    conn.close()
    r = c.post(f"/project/{pid}/pay", data={"k": ktok, "kind": "final"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "pay=error" not in r.headers["location"], (
        "an existing invoice still needs a proposal to be paid")
    # No payment provider is configured in a test, so the honest end of the road is
    # 'unavailable' — which IS rendered.
    assert "pay=unavailable" in r.headers["location"]


def test_no_invoice_and_no_proposal_says_which(portal):
    """Distinguishable from a crash: we could not raise it, and the studio has been told."""
    c, _db, pid, ktok = portal
    r = c.post(f"/project/{pid}/pay", data={"k": ktok, "kind": "final"},
               follow_redirects=False)
    assert "pay=noinvoice" in r.headers["location"]


def test_a_settled_invoice_says_so(portal):
    c, db, pid, ktok = portal
    conn = db.connect()
    iid = db.insert_invoice(conn, pid, None, Invoice(client="L", need="Sand Castle",
                                                     kind="Final", amount=10.0))
    db.update_invoice_status(conn, iid, "Paid")
    conn.close()
    r = c.post(f"/project/{pid}/pay", data={"k": ktok, "kind": "final"},
               follow_redirects=False)
    assert "pay=already" in r.headers["location"]


# ── and every bounce is rendered ────────────────────────────────────────────────────
@pytest.mark.parametrize("flag", sorted(PAY_NOTICES))
def test_every_flag_has_a_sentence(flag):
    assert pay_notice(flag), flag
    assert not pay_notice("something-else"), "an unknown flag must say nothing, not guess"


def test_the_room_renders_it(portal):
    c, db, pid, ktok = portal
    conn = db.connect()
    from chordential_oia.web import production
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1 FINAL", "url": "/u/v.wav"}])
    production.set_creative_lock(conn, db, pid, version_n=1, by="Marta")
    conn.close()
    page = c.get(f"/room/{pid}?k={ktok}&pay=noinvoice").text
    # Jinja escapes the apostrophe, so compare on a fragment that has none.
    assert "raise this invoice automatically" in page, "the room swallows the reason"
    assert 'class="pay-notice"' in page


@pytest.mark.parametrize("template,flag", [
    ("delivery_portal.html", "noinvoice"),
    ("workspace.html", "error"),
])
def test_the_other_two_surfaces_render_it(template, flag):
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "templates" / template).read_text(encoding="utf-8")
    assert "pay_notice(request.query_params.get('pay'))" in src, (
        f"{template} still renders only one of the four bounces")


def test_a_payment_pressed_in_the_room_comes_back_to_the_room(portal):
    c, db, pid, ktok = portal
    conn = db.connect()
    iid = db.insert_invoice(conn, pid, None, Invoice(client="L", need="Sand Castle",
                                                     kind="Final", amount=10.0))
    db.update_invoice_status(conn, iid, "Issued")
    conn.close()
    r = c.post(f"/project/{pid}/pay",
               data={"k": ktok, "kind": "final", "origin": "room"},
               follow_redirects=False)
    assert r.headers["location"].startswith(f"/room/{pid}?k={ktok}"), r.headers["location"]


def test_the_portals_own_button_still_returns_to_the_portal(portal):
    c, db, pid, ktok = portal
    conn = db.connect()
    iid = db.insert_invoice(conn, pid, None, Invoice(client="L", need="S",
                                                     kind="Final", amount=10.0))
    db.update_invoice_status(conn, iid, "Issued")
    conn.close()
    r = c.post(f"/project/{pid}/pay", data={"k": ktok, "kind": "final"},
               follow_redirects=False)
    assert "/delivery-portal" in r.headers["location"]
