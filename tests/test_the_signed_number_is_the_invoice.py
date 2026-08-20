"""The money was agreed at the signature. The system just could not read it.

Reported live (operator, 2026-08-19): *"im confused where do i go to send the invoice, i
thought that was already agreed upon when i got the signature. where do i go to input
final invoice numbers?"*

They were right, and my previous answer — type the amount by hand — was answering the
wrong question. The signed Discovery Summary carries the fee, the deposit and "balance
due on delivery"; ADR-0067 writes those into the project's `proposals` row when the
studio countersigns. But only since the day that code landed. A deal countersigned before
it has the signature, the countersignature and the document, and no row for any money
surface to read — so `final_invoice_block` called it unbillable and asked for a number
the client had already agreed to.

`billing._heal_proposal` writes the row from the SIGNED band, through the same
`_ensure_proposal_for_project` the countersign path uses. Nothing decides a price: it
reads the document the client actually signed, and refuses if that document is not priced
— which is when the hand-raise control is the honest answer rather than the lazy one.
"""
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    import importlib
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app) as c:
        db = app_mod.db
        conn = db.connect()
        row = conn.execute(
            "SELECT id AS pid, opp_id FROM projects WHERE opp_id IS NOT NULL"
            " ORDER BY id LIMIT 1").fetchone()
        pid, opp_id = row["pid"], row["opp_id"]
        # the deal HAS had its discovery call — which is what prices the summary
        db.create_meeting(conn, opp_id=opp_id, start_at="2026-08-01T10:00:00+00:00",
                          status="ingested")
        # …and was countersigned BEFORE ADR-0067 wrote the proposals row
        conn.execute("DELETE FROM proposals WHERE project_id = ?", (pid,))
        conn.commit()
        conn.close()
        yield c, db, pid, opp_id, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def test_the_signed_document_carries_the_money(seeded):
    """The premise. If this fails the rest is meaningless."""
    _c, db, _pid, opp_id, _a = seeded
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    conn = db.connect()
    try:
        _r, _o, _e, doc, deposit = agreement_doc_for(conn, opp_id)
    finally:
        conn.close()
    agr = getattr(doc, "agreement", None)
    assert agr is not None and agr.price_low, "the signed summary quotes nothing"
    assert deposit > 0


def test_a_deal_signed_before_the_fix_is_not_called_unbillable(seeded):
    _c, db, pid, _o, _a = seeded
    from chordential_oia.web.billing import final_invoice_block
    from chordential_oia.web.opportunity_ops import _ensure_proposal_for_project
    conn = db.connect()
    try:
        assert db.proposal_for_project(conn, pid) is None      # the reported state
        # The healer is INJECTED — `billing` sits below `opportunity_ops` in the helper
        # DAG (ADR-0044) and may not reach up for it. Every route surface passes it.
        assert final_invoice_block(conn, pid, heal=_ensure_proposal_for_project) == "", (
            "asks the operator to type a number the client already signed")
        assert db.proposal_for_project(conn, pid) is not None, "the heal did not persist"
    finally:
        conn.close()


def test_the_invoice_comes_out_at_the_signed_number(seeded):
    _c, db, pid, opp_id, _a = seeded
    from chordential_oia.web.billing import _ensure_final_invoice_issued
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    conn = db.connect()
    try:
        from chordential_oia.web.opportunity_ops import _ensure_proposal_for_project
        _r, _o, _e, _doc, deposit = agreement_doc_for(conn, opp_id)
        _ensure_final_invoice_issued(conn, pid, heal=_ensure_proposal_for_project)
        invs = db.list_invoices(conn, pid)
        assert [(i["kind"], i["status"]) for i in invs] == [("Final", "Issued")]
        assert invs[0]["amount"] == deposit, (
            "the invoice names a number that is not the signed balance")
    finally:
        conn.close()


def test_an_unpriced_deal_still_refuses_to_invent_one(seeded):
    """The heal reads the signed document; it does not guess. A deal with no priced
    summary stays blocked, which is when typing the amount is the honest answer."""
    _c, db, pid, opp_id, _a = seeded
    from chordential_oia.web.billing import final_invoice_block
    conn = db.connect()
    try:
        conn.execute("DELETE FROM meetings WHERE opp_id = ?", (opp_id,))  # no call → no price
        conn.execute("DELETE FROM proposals WHERE project_id = ?", (pid,))
        conn.commit()
        from chordential_oia.web.opportunity_ops import _ensure_proposal_for_project
        assert final_invoice_block(
            conn, pid, heal=_ensure_proposal_for_project) == "noproposal"
        assert db.proposal_for_project(conn, pid) is None
    finally:
        conn.close()


# ── and it has to reach the dashboard ───────────────────────────────────────────────
def test_a_delivery_nobody_can_bill_raises_the_badge(tmp_path, monkeypatch):
    """*"that did not show up in my dashboard to do with a red badge"* — it does now."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "b.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])
    assert db.pending_submission_count(conn) == 0
    db.update_delivery(conn, pid, "state", "Delivered")
    assert db.pending_submission_count(conn) == 1, "no badge for an unbillable delivery"
    from chordential_oia.web.queue import compute_queue
    cards = compute_queue(conn, db)
    conn.close()
    hit = [x for x in cards if "cannot pay" in (x["title"] or "").lower()]
    assert hit, "the queue never mentions it"
    assert f"/project/{pid}/delivery" in hit[0]["url"]
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("letmein"))
    page = c.get("/dashboard").text
    m = re.search(r'id="queue-badge"[^>]*style="display:([a-z-]+)[^>]*>([^<]*)<', page)
    assert m and m.group(1) == "inline-block" and m.group(2).strip() == "1"


# ── the page that lands folded ──────────────────────────────────────────────────────
def test_campaign_intelligence_lands_folded(seeded):
    """*"way too much scrolling, when the page land all the sections should [be]
    collapsed"*. Opening the filled sections meant arriving a screen and a half deep with
    everything unrolled; the count in each summary is what you read at a glance."""
    c, db, _pid, opp_id, admin = seeded
    c.cookies.set(*admin)
    page = c.get(f"/opportunity/{opp_id}").text
    assert page.count('class="ci-section ci-acc"') >= 4, "the sections are not accordions"
    assert not re.findall(r'class="ci-section ci-acc"[^>]*\sopen', page), (
        "a section is open on arrival")


def test_the_last_two_sections_fold_too(seeded):
    """"Anything else that matters" and "The producer's read" were plain divs — the two
    longest things on the page."""
    c, _db, _pid, opp_id, admin = seeded
    c.cookies.set(*admin)
    page = c.get(f"/opportunity/{opp_id}").text
    for label in ("Anything else that matters", "producer"):
        i = page.find(label)
        if i < 0:
            continue
        assert "<details" in page[max(0, i - 300):i], f"{label!r} is not in an accordion"


def test_a_delivered_room_raises_its_own_balance(seeded):
    """The whole point, through the door the client uses. `_maybe_finalize_delivery`
    cannot heal — `delivery_ops` sits below `opportunity_ops` in the helper DAG — so a
    deal that shipped before ADR-0067 only ever becomes payable here."""
    c, db, pid, _o, _a = seeded
    from chordential_oia.web import production
    conn = db.connect()
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v2 FINAL", "url": "/u/v.wav"}])
    production.set_creative_lock(conn, db, pid, version_n=2, by="Marta Ruiz")
    db.update_delivery(conn, pid, "state", "Delivered")
    ktok = db.rotate_share_token(conn, project_id=pid)
    conn.close()
    page = c.get(f"/room/{pid}?k={ktok}").text          # the client simply opens it
    conn = db.connect()
    invs = db.list_invoices(conn, pid)
    outstanding = db.invoice_balance(conn, pid)["outstanding"]
    conn.close()
    assert [(i["kind"], i["status"]) for i in invs] == [("Final", "Issued")], invs
    assert outstanding > 0
    assert f"${outstanding:,.2f}" in page or f"{outstanding:.2f}" in page, (
        "the balance was raised and the room does not name it")


def test_pressing_pay_issues_what_it_raises(seeded):
    """A lazily-created invoice arrived as a Draft, which `invoice_balance` correctly
    treats as not-yet-owed — so pressing Pay created a balance of zero."""
    c, db, pid, _o, _a = seeded
    conn = db.connect()
    ktok = db.rotate_share_token(conn, project_id=pid)
    conn.close()
    c.post(f"/project/{pid}/pay", data={"k": ktok, "kind": "final", "origin": "room"},
           follow_redirects=False)
    conn = db.connect()
    invs = db.list_invoices(conn, pid)
    conn.close()
    assert invs and (invs[0]["status"] or "") == "Issued", (
        f"the invoice the client is trying to pay is {invs[0]['status'] if invs else 'absent'}")
