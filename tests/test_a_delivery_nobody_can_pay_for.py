"""Everything signed off, and no way to pay — a dead end dressed as progress.

Reported live (operator, 2026-08-19): *"everything was approved by the client but nothing
came up for the client to pay remaining balance."*

Reproduced exactly, and the chain works right up to the last link: creative lock ✓, every
scoped deliverable uploaded ✓, all fifteen files signed off ✓, `_ready_to_deliver` True,
state **Delivered**, package assembled. And then nothing, because **every invoice path in
the system derives its amount from a stored proposal and returns silently when there is
none** — `_ensure_final_invoice_issued`, `project_create_invoice`, `client_pay`. A project
that reached delivery any other way (a deal entered by hand, a signature path that never
wrote one) locks its download behind a balance that cannot be raised, and tells the client
their files are "being assembled" forever.

Two things follow. The state has to be VISIBLE — to the client in words that are true, to
the operator with something to press. And the way out cannot infer a price: what the work
is worth is the operator's decision, which is where "the machine proposes, Jon disposes"
matters most.
"""
import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.invoicing import Invoice
from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent
from chordential_oia.web.billing import (
    INVOICE_BLOCK_CLIENT, INVOICE_BLOCK_OPERATOR, final_invoice_block,
)


@pytest.fixture()
def delivered(tmp_path, monkeypatch):
    """A project taken all the way to Delivered, with NO proposal — the reported state."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db, production
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    admin = (ADMIN_COOKIE, admin_cookie_value("letmein"))
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Ada Cheng", email="ada@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    ttok = db.ensure_talent_portal_token(conn, tid)
    ktok = db.rotate_share_token(conn, project_id=pid)
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v2 FINAL", "url": "/u/v.wav"}])
    db.update_delivery(conn, pid, "version_state", "v2 FINAL")
    production.set_creative_lock(conn, pid and db, pid, version_n=2, by="Marta Ruiz")
    conn.close()

    lanes = {"Instrumental / TV mix": ["tv.wav"],
             ":30 / :15 / :06 cutdowns": ["c15.wav", "c30.wav"],
             "9:16 vertical cuts (loudness-prepped)": ["v916.wav"],
             "Mix-ready stem package": [f"stem{i}.wav" for i in range(4)]}
    for label, names in lanes.items():
        c.post(f"/creator/{ttok}/project/{pid}/deliverable", data={"label": label},
               files=[("file", (n, io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                                "audio/wav")) for n in names],
               headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    for a in pend:
        c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": a["filename"], "action": "publish"},
               follow_redirects=False)
    c.cookies.clear()
    for _ in range(10):                       # the client signs off every lane
        page = c.get(f"/room/{pid}?k={ktok}").text
        if 'class="so-form"' not in page:
            break
        seg = page[page.index('class="so-form"'):]
        keys = re.findall(r'name="filename" value="([^"]+)"', seg[:seg.index("</form>")])
        c.post(f"/project/{pid}/review/asset",
               data={"k": ktok, "author": "Marta Ruiz", "email": "m@a.com",
                     "origin": "room", "action": "approve", "filename": keys},
               follow_redirects=False)
    return c, db, pid, ktok, admin


# ── the state is real, and it was invisible ─────────────────────────────────────────
def test_the_delivery_really_did_finish(delivered):
    """Not a broken flow — a finished one with no way to bill it."""
    c, db, pid, _k, _a = delivered
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    roll = db.asset_approval_rollup(d)
    conn.close()
    assert d.get("state") == "Delivered"
    assert roll["approved"] == roll["total"] > 0


def test_no_proposal_means_no_invoice_at_all(delivered):
    c, db, pid, _k, _a = delivered
    conn = db.connect()
    try:
        assert db.proposal_for_project(conn, pid) is None
        assert db.list_invoices(conn, pid) == []
        assert db.invoice_balance(conn, pid)["outstanding"] == 0
        assert final_invoice_block(conn, pid) == "noproposal"
    finally:
        conn.close()


def test_the_client_is_not_told_a_comfortable_lie(delivered):
    """"Your package is being assembled" was said to a client whose package WAS
    assembled and whose download was locked behind a balance nobody could raise."""
    c, _db, pid, ktok, _a = delivered
    payoff = re.search(r'class="payoff">(.*?)</div>',
                       c.get(f"/room/{pid}?k={ktok}").text, re.S).group(1)
    assert "being assembled" not in payoff, payoff
    assert "preparing your invoice" in payoff


def test_the_operator_is_told_the_client_cannot_pay(delivered):
    c, _db, pid, _k, admin = delivered
    c.cookies.set(*admin)
    console = c.get(f"/project/{pid}/delivery").text
    assert "CANNOT PAY" in console or "cannot pay" in console.lower(), (
        "the console is silent about a delivery nobody can be billed for")
    assert "/invoice/balance" in console, "no way out is offered"


# ── the way out ─────────────────────────────────────────────────────────────────────
def test_the_operator_can_raise_the_balance_by_hand(delivered):
    c, db, pid, ktok, admin = delivered
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/invoice/balance",
               data={"amount": "4,200.00", "note": "Balance on delivery"},
               follow_redirects=False)
    assert r.status_code == 303 and "invoice=raised" in r.headers["location"]
    conn = db.connect()
    invs = db.list_invoices(conn, pid)
    bal = db.invoice_balance(conn, pid)
    conn.close()
    assert [(i["kind"], i["status"], i["amount"]) for i in invs] == [("Final", "Issued", 4200.0)]
    assert bal["outstanding"] == 4200.0


def test_raising_it_puts_the_pay_button_in_front_of_the_client(delivered):
    c, _db, pid, ktok, admin = delivered
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/invoice/balance", data={"amount": "4200"},
           follow_redirects=False)
    c.cookies.clear()
    payoff = re.search(r'class="payoff">(.*?)</div>',
                       c.get(f"/room/{pid}?k={ktok}").text, re.S).group(1)
    assert "Pay $4200.00 to unlock your files" in payoff, payoff


def test_no_amount_is_ever_inferred(delivered):
    """What the work is worth is the operator's decision. A blank or nonsense amount
    raises nothing at all rather than guessing from the budget or the estimate."""
    c, db, pid, _k, admin = delivered
    c.cookies.set(*admin)
    for bad in ("", "0", "-5", "lots"):
        r = c.post(f"/project/{pid}/invoice/balance", data={"amount": bad},
                   follow_redirects=False)
        assert "invoice=amount" in r.headers["location"], bad
    conn = db.connect()
    assert db.list_invoices(conn, pid) == []
    conn.close()


def test_raising_it_twice_does_not_double_bill(delivered):
    c, db, pid, _k, admin = delivered
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/invoice/balance", data={"amount": "4200"}, follow_redirects=False)
    c.post(f"/project/{pid}/invoice/balance", data={"amount": "9999"}, follow_redirects=False)
    conn = db.connect()
    invs = db.list_invoices(conn, pid)
    conn.close()
    assert len(invs) == 1 and invs[0]["amount"] == 4200.0, (
        "a second press raised a second balance")


# ── the block reasons ───────────────────────────────────────────────────────────────
def test_a_draft_invoice_is_its_own_block(delivered):
    """Raised but never issued is not owed — and looks identical to no invoice at all
    from the client's side."""
    c, db, pid, _k, _a = delivered
    conn = db.connect()
    db.insert_invoice(conn, pid, None, Invoice(client="L", need="Sand Castle",
                                               kind="Final", amount=100.0))
    assert final_invoice_block(conn, pid) == "draft"
    conn.close()


def test_an_issued_invoice_is_no_block(delivered):
    c, db, pid, _k, _a = delivered
    conn = db.connect()
    iid = db.insert_invoice(conn, pid, None, Invoice(client="L", need="S",
                                                     kind="Final", amount=100.0))
    db.update_invoice_status(conn, iid, "Issued")
    assert final_invoice_block(conn, pid) == ""
    conn.close()


@pytest.mark.parametrize("why", sorted(INVOICE_BLOCK_CLIENT))
def test_every_reason_has_words_for_both_sides(why):
    assert INVOICE_BLOCK_CLIENT[why] and INVOICE_BLOCK_OPERATOR[why]
    assert "proposal" not in INVOICE_BLOCK_CLIENT[why].lower(), (
        "the client is told our plumbing instead of what happens next")
