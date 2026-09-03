"""After signing, the client was shown a finished room and asked for nothing.

Reported live, from inside the composer's portal: *"we never presented the client with a
way for them to upload their content into the portal. After the proposal was signed, it
never took them to the platform to pay their deposit."*

Three faults, one root. A deal closed the ADR-0065 way — the client signs the Discovery
Summary, the operator countersigns — took a different route through the app than a deal
closed the older Commercial-Review way, and every client-facing obligation hung off the
older route:

1. **No proposal row.** Only `_ensure_proposal_from_review` ever wrote one, so
   `proposal_for_project` returned None, `kickoff._deposit_state` read the owed amount as
   0 and reported "no deposit required", and the workspace's Pay button never rendered —
   while the acceptance text the client had just signed promised a deposit invoice.
2. **No Kickoff.** `compute_phase` needs `commercial_approved`, which only a Commercial
   Review could set, so a signed deal skipped KICKOFF into PRODUCTION. Kickoff is where
   the client's remaining actions live, so they never reached the list at all.
3. **Nobody asked for the picture.** The composer's session room renders "picture arrives
   with the client's cut" and waits; the delivery portal has had the Drop that receives it
   all along. No surface ever requested it.

The tests below walk the client's actual path: sign, countersign, open the workspace, and
follow the buttons it offers to the file landing in the composer's room.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "todo.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"email": "", "password": "passphrase"},
               follow_redirects=False)
        yield c, app_mod


def _signable_deal(app_mod):
    """A deal whose discovery call has happened and which carries a price — the two
    things ADR-0065 requires before anything is signable."""
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    db = app_mod.db
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn = db.connect()
    try:
        for r in conn.execute("SELECT id FROM opportunities ORDER BY id").fetchall():
            if not db.list_meetings(conn, r["id"]):
                db.create_meeting(conn, opp_id=r["id"], start_at=past, status="ingested")
            conn.execute(
                "UPDATE meetings SET start_at=?, status='ingested' WHERE opp_id=?",
                (past, r["id"]))
            conn.commit()
            _r, _o, _e, doc, _d = agreement_doc_for(conn, r["id"])
            agr = getattr(doc, "agreement", None)
            if agr is not None and getattr(agr, "price_low", None):
                return r["id"], db.ensure_share_token(conn, r["id"]), agr
    finally:
        conn.close()
    pytest.skip("no signable demo deal")


def _close(c, app_mod):
    opp_id, token, agr = _signable_deal(app_mod)
    c.post(f"/workspace/{token}/sign",
           data={"typed_name": "Marta Reyes", "signer_email": "marta@example.com",
                 "consent": "1"}, follow_redirects=False)
    c.post(f"/opportunity/{opp_id}/countersign",
           data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    return opp_id, token, agr


# ── 1. the money exists where every downstream surface looks for it ──────────────────
def test_countersigning_writes_the_proposal_the_deposit_is_read_from(studio):
    c, app_mod = studio
    opp_id, _token, _agr = _close(c, app_mod)
    db = app_mod.db
    conn = db.connect()
    try:
        project = db.project_for_opp(conn, opp_id)
        assert project is not None, "countersigning is the award; it must create a project"
        prop = db.proposal_for_project(conn, project["id"])
    finally:
        conn.close()
    assert prop is not None, (
        "no proposal row — the deposit is invisible to the workspace, /pay and Kickoff")
    assert prop["deposit_amount"] > 0


def test_the_invoice_cannot_quote_a_number_they_did_not_sign(studio):
    """The proposal is built from the SIGNED agreement's band, not a fresh quote."""
    c, app_mod = studio
    opp_id, _token, agr = _close(c, app_mod)
    db = app_mod.db
    conn = db.connect()
    try:
        project = db.project_for_opp(conn, opp_id)
        prop = db.proposal_for_project(conn, project["id"])
    finally:
        conn.close()
    signed_mid = round(((agr.price_low or 0) + (agr.price_high or agr.price_low or 0)) / 2)
    assert abs(prop["total_price"] - signed_mid) < 1, (
        f"invoiced {prop['total_price']} against a signed band of "
        f"{agr.price_low}–{agr.price_high}")
    # And the deposit sentence in the document they signed names the same figure.
    assert f"${prop['deposit_amount']:,.0f}" in agr.deposit


def test_it_is_idempotent(studio):
    """A second countersign attempt (or a retry) must not stack a second proposal."""
    from chordential_oia.web.opportunity_ops import _ensure_proposal_for_project
    c, app_mod = studio
    opp_id, _token, _agr = _close(c, app_mod)
    db = app_mod.db
    conn = db.connect()
    try:
        pid = db.project_for_opp(conn, opp_id)["id"]
        assert _ensure_proposal_for_project(conn, opp_id, pid) is None
        n = conn.execute("SELECT COUNT(*) c FROM proposals WHERE project_id=?",
                         (pid,)).fetchone()["c"]
    finally:
        conn.close()
    assert n == 1


# ── 2. a signed deal reaches Kickoff, where the client's actions live ────────────────
def test_a_countersigned_deal_is_commercially_approved(studio):
    from chordential_oia.web import workspace
    from chordential_oia.web.workspace_routes import _workspace_signals
    c, app_mod = studio
    opp_id, _token, _agr = _close(c, app_mod)
    db = app_mod.db
    conn = db.connect()
    try:
        opp = db.get_opportunity(conn, opp_id)
        project = db.project_for_opp(conn, opp_id)
        signals = _workspace_signals(conn, opp, project)
    finally:
        conn.close()
    assert signals["commercial_approved"] is True, (
        "both parties are bound; there is no weaker sense of 'approved' left")
    assert workspace.compute_phase(signals) == workspace.KICKOFF, (
        "a signed deal skipped Kickoff, which is the only place the client is asked "
        "for anything")


# ── 3. THE ROOM asks for both, and both are actionable ──────────────────────────────
#
# These asked the WORKSPACE, which no longer receives a client after the countersignature
# (2026-08-27). The assertions are unchanged: what a client is asked for did not change,
# only where they are standing when asked.
def _client_room(c, token):
    """Follow the client's own link the way a client does."""
    return c.get(f"/workspace/{token}", follow_redirects=True).text


def test_the_room_asks_for_the_deposit_and_the_picture(studio):
    c, app_mod = studio
    _opp_id, token, _agr = _close(c, app_mod)
    page = _client_room(c, token)
    assert "Everything is ready" not in page, (
        "it said everything was ready with an unpaid deposit and no footage")
    assert "Pay deposit" in page
    assert "Send your deposit" in page
    assert "Send us the cut" in page


def test_the_ask_carries_a_door(studio):
    """A list item saying 'send us the cut' with no way to send it is the same failure
    as not asking — and from 2026-08-30 the door is not a LINK, it is the Drop itself.

    *"all the old workspace and portal should go away keep the client in the room"*
    (operator). This was the last thing a buyer had to leave the room for, and it is the
    most useful thing they can do while a composer is being assigned.
    """
    c, app_mod = studio
    _opp_id, token, _agr = _close(c, app_mod)
    page = _client_room(c, token)
    assert 'id="cut-form"' in page, "the picture request rendered with no way to send one"
    assert "Drop your cut here" in page
    assert "/delivery-portal" not in page, "it still walks the buyer out of the room"
    # …and the fps/timecode fields came WITH it, because it is the same partial the
    # delivery portal renders rather than a thinner rebuild.
    assert 'name="fps"' in page and 'name="tc_start"' in page


def test_the_client_walks_it_without_ever_logging_in(studio):
    """End to end on the client's own path: follow the button, drop the cut, and watch
    the ask clear. A fresh client == no admin cookie, which is the state a real buyer
    is always in."""
    import re

    from fastapi.testclient import TestClient
    c, app_mod = studio
    _opp_id, token, _agr = _close(c, app_mod)
    conn = app_mod.db.connect()
    try:
        opp = app_mod.db.opportunity_by_share_token(conn, token)
        pid = app_mod.db.project_for_opp(conn, opp["id"])["id"]
    finally:
        conn.close()
    room_url = f"/room/{pid}?k={token}"

    with TestClient(app_mod.app) as buyer:
        page = buyer.get(room_url)
        assert page.status_code == 200
        assert "Password or passphrase" not in page.text
        # The Drop is IN the room now — no second surface to walk out to.
        assert "Drop your cut here" in page.text
        m = re.search(r'action="([^"]*review/assets)"', page.text)
        assert m, "the Drop rendered with no form action"
        assert f"/project/{pid}/" in m.group(1)
        r = buyer.post(f"/project/{pid}/review/picture",
                       data={"k": token, "author": "Marta Reyes"},
                       files={"file": ("cut.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 400,
                                       "video/mp4")}, follow_redirects=False)
        assert r.status_code == 303

    conn = app_mod.db.connect()
    try:
        delivery = app_mod.db.get_delivery(conn, pid)
    finally:
        conn.close()
    assert (delivery or {}).get("picture", {}).get("orig") == "cut.mp4", (
        "the cut never reached the composer's room")
    after = c.get(f"/workspace/{token}").text
    assert "Send us the cut" not in after, "it kept asking for a picture it already had"
    # The ROOM confirms by showing the cut rather than printing a receipt — the client's
    # own footage is on the poster the moment it lands.


def test_the_picture_is_not_gated_on_the_deposit(studio):
    """Sending the cut early costs the client nothing and is the most useful thing they
    can do while the composer is being assigned."""
    c, app_mod = studio
    _opp_id, token, _agr = _close(c, app_mod)
    page = _client_room(c, token)
    assert "Send your deposit" in page and "Send us the cut" in page, (
        "both asks must stand at once — the picture must not wait on the money")


def test_the_countersign_mail_names_both(studio, monkeypatch):
    from chordential_oia import mailer
    sent = []
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, subject, body, **kw: sent.append((to, subject, body)))
    c, app_mod = studio
    _close(c, app_mod)
    client_mail = [s for s in sent if "Countersigned" in s[1]]
    assert client_mail, "the client was never told it was countersigned"
    body = client_mail[0][2]
    assert "deposit" in body and "cut" in body
    # *"any new links sent out after a countersign should send them to 'the room'"*
    # (operator, 2026-08-27). `/workspace/…` would redirect here, but the link is the
    # promise — it should not need repairing by a 303 the client watches happen.
    assert "/room/" in body, "no door back to the place both things happen"
    assert "/workspace/" not in body


def test_client_url_is_the_room_after_award_and_carries_its_flag(studio):
    """ONE derivation of "where does the client live" (`room.client_url`).

    Before a project exists there is no room to send anyone to — a room IS a project —
    so the workspace is the honest answer and the Commercial Review lives there. After
    award it is the room, and the flag has to survive: the receipt banner and the
    "payments aren't switched on" notice both ride a query string, and the workspace
    redirect drops one, so a hand-written `/workspace/…?paid=1` would have looked
    correct and shown the client nothing.
    """
    from chordential_oia.web import room
    c, app_mod = studio
    db = app_mod.db
    opp_id, token, _agr = _signable_deal(app_mod)
    conn = db.connect()
    try:
        assert db.project_for_opp(conn, opp_id) is None
        assert room.client_url(conn, db, opp_id) == f"/workspace/{token}"
    finally:
        conn.close()
    _close(c, app_mod)                                   # sign + countersign → project
    conn = db.connect()
    try:
        pid = db.project_for_opp(conn, opp_id)["id"]
        assert room.client_url(conn, db, opp_id) == f"/room/{pid}?k={token}"
        assert room.client_url(conn, db, opp_id, flag="paid=1") == \
            f"/room/{pid}?k={token}&paid=1"
        assert room.client_url(conn, db, opp_id, base="https://chordential.com/") == \
            f"https://chordential.com/room/{pid}?k={token}"
    finally:
        conn.close()
