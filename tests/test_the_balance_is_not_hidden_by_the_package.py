"""A dead end where the balance should have been.

Reported live (operator, 2026-08-21), from inside the client's own room: *"I clicked
reload to reload and settle my balance and it took me no where."*

Two faults, and they compounded.

**The payoff block was one `{% if %}/{% elif %}` ladder**, so the package's state could
swallow the money. A client whose package was stale — audio missing from the last build,
which is the state the ephemeral disk keeps producing — matched the first branch and got
"your package is being re-assembled" and **nothing else**. No Pay button, no download, no
next step, while a real balance sat outstanding. What you OWE and what you may TAKE are
independent facts, and the block was treating them as one.

**And the browser wrote a promise the server could not keep.** When the last deliverable
was approved, the JS replaced the payoff with "Reload to pick up your package and settle
the balance" — a sentence composed by a script that does not know either of those things.
Reloading landed on the branch above. The press "took me nowhere" because what it promised
was never the server's answer.

The rule: **money is answered first, files second, and neither hides the other.** A dead
end dressed as progress is the exact defect this block already existed to prevent.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def room(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "p.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "outbox", "signals", "room", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.invoicing import Invoice
    from chordential_oia.web import app as app_mod, db, production
    from chordential_oia.web.delivery_ops import scoped_signoff
    from chordential_oia.web.uploads import _persist_upload
    with TestClient(app_mod.app):
        pass
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        _persist_upload(conn, "m1.mp3", b"ID3x" * 200, "audio/mpeg")
        db.update_delivery(conn, pid, "versions", [{
            "n": 1, "label": "v1", "url": "/uploads/m1.mp3", "filename": "m1.mp3",
            "at": "x", "by": "Ada"}])
        production.set_creative_lock(conn, db, pid, version_n=1, by="Marta")
        # Every scoped lane filled and signed off — the state the operator was in.
        lanes, _r, _a = scoped_signoff(db.get_project(conn, pid),
                                       db.get_delivery(conn, pid))
        assets = []
        for i, lane in enumerate(lanes):
            if lane.get("from_version"):
                continue
            fn = f"z{i}.wav"
            _persist_upload(conn, fn, b"RIFFx" * 200, "audio/wav")
            assets.append({"label": lane["asset"], "url": f"/uploads/{fn}",
                           "filename": fn, "orig": f"lane{i}.wav", "kind": "audio"})
        db.update_delivery(conn, pid, "assets", assets)
        for a in assets:
            db.set_asset_approval(conn, pid, a["filename"], status="Approved",
                                  by="Marta", email="m@x.com", version="1")
        db.update_delivery(conn, pid, "state", "Delivered")
        iid = db.insert_invoice(conn, pid, None, Invoice(
            client="Larkspur", need="Sand Castle", kind="Final", amount=4200.0))
        db.update_invoice_status(conn, iid, "Issued")
        tok = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    return TestClient(app_mod.app), db, pid, tok


def _payoff(client, pid, tok):
    page = client.get(f"/room/{pid}", params={"k": tok}).text
    i = page.index('class="payoff"')
    return page[i:i + 1800]


def _stale_package(db, pid):
    """Unlocked, built, and missing its audio — what the ephemeral disk keeps producing."""
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "download_unlocked", True)
        db.update_delivery(conn, pid, "delivery_zip", {
            "filename": "pkg.zip", "url": "/uploads/pkg.zip",
            "referenced_count": 3, "asset_count": 0})
    finally:
        conn.close()


# ── the balance survives the package's state ────────────────────────────────────────
def test_a_stale_package_no_longer_swallows_the_balance(room):
    """The reported dead end, exactly."""
    c, db, pid, tok = room
    _stale_package(db, pid)
    block = _payoff(c, pid, tok)
    assert f"/project/{pid}/pay" in block, (
        "the client owes money and has no way to pay it — the package note took the page")
    assert "Pay $4200.00" in block
    assert "re-assembled" in block, "the honest package note was lost instead"


def test_a_healthy_package_still_offers_the_download(room):
    c, db, pid, tok = room
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "download_unlocked", True)
        db.update_delivery(conn, pid, "delivery_zip", {
            "filename": "pkg.zip", "url": "/uploads/pkg.zip",
            "referenced_count": 0, "asset_count": 6})
    finally:
        conn.close()
    block = _payoff(c, pid, tok)
    assert "Download everything" in block
    assert "Yours to keep" in block


def test_paid_in_full_shows_no_pay_button(room):
    """The other direction: nothing owed, nothing asked for."""
    c, db, pid, tok = room
    conn = db.connect()
    try:
        for inv in db.list_invoices(conn, pid):
            db.update_invoice_status(conn, inv["id"], "Paid")
        db.update_delivery(conn, pid, "download_unlocked", True)
        db.update_delivery(conn, pid, "delivery_zip", {
            "filename": "pkg.zip", "url": "/uploads/pkg.zip",
            "referenced_count": 0, "asset_count": 6})
    finally:
        conn.close()
    block = _payoff(c, pid, tok)
    assert f"/project/{pid}/pay" not in block
    assert "Download everything" in block


def test_an_unfinished_signoff_says_so_and_still_names_the_balance(room):
    c, db, pid, tok = room
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "asset_approvals", {})   # nothing signed off yet
    finally:
        conn.close()
    block = _payoff(c, pid, tok)
    assert "Approve every deliverable above" in block
    assert "4200.00" in block, "the client cannot see what it will cost"
    assert f"/project/{pid}/pay" not in block, (
        "asking for money before the work is signed off inverts the deal")


# ── and the browser stops writing promises for the server ───────────────────────────
def test_the_last_approval_does_not_promise_what_it_cannot_know(room):
    from pathlib import Path
    _c, _db, _pid, _tok = room
    from chordential_oia.web import app as app_mod
    tpl = (Path(app_mod.__file__).parent / "templates" / "creator_portal.html"
           ).read_text(encoding="utf-8")
    assert "Reload to pick up your package and settle the balance" not in tpl, (
        "the browser is again promising a package and a balance it cannot see")
    assert "location.reload()" in tpl, "the page no longer refreshes onto the real answer"


def test_the_payoff_answers_money_before_files():
    """Structural, because the ladder is what caused this: if the package branch is
    evaluated first again, a stale build hides the balance a second time."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod
    tpl = (Path(app_mod.__file__).parent / "templates" / "creator_portal.html"
           ).read_text(encoding="utf-8")
    block = tpl[tpl.index('<div class="payoff">'):]
    block = block[:block.index("</div>")]
    money = block.index("invoice_balance")
    files = block.index("download_unlocked")
    assert money < files, "the package's state is being asked about before the balance"
