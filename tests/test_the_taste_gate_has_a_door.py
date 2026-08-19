"""The gate that keeps unvetted work off the client's page had no door in the room.

Reported live (operator, 2026-08-19): *"I don't see a way for me to push a version out to
the client after review, nor how to deny it and send it back to the composer, am i
missing something?"*

Not missing it — it was somewhere else. **Publish to client** lived on the delivery
console, so the operator auditioned a take in the room, against picture, with the notes on
the lane, and then had to leave the room to act on what they had just heard. A judgement
made in one place and recorded in another is a judgement people stop making.

And the second half did not exist at all. The console's other button was **Discard**: it
cleared the submission, wrote a line into the project's own updates, and told the composer
NOTHING. Their take simply stopped existing — no reason, no request, no email. The one
action in this system whose entire point is a judgement was the one that never reached the
person being judged.

So: the gate has a door where the listening happens, and denying a take is a **send-back**
that carries a reason to the people who made it. It costs no client revision round —
nobody outside the studio has heard it.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent
from chordential_oia.web import room as R


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db, uploads
    c = TestClient(app_mod.app)
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "AURORA", "Launch film", 1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Ada Cheng", email="ada@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    ttok = db.ensure_talent_portal_token(conn, tid)
    ktok = db.rotate_share_token(conn, project_id=pid)
    uploads._store_pending_submission(conn, pid, b"x" * 32, "v1.mp3", "Ada Cheng")
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return (c, db, uploads, pid, ttok, ktok,
            (ADMIN_COOKIE, admin_cookie_value("letmein")))


# ── the door is where the listening is ──────────────────────────────────────────────
def test_the_studios_room_carries_the_gate(studio):
    c, _db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    assert f"/project/{pid}/delivery/publish" in page, (
        "no way to publish from the room the take was judged in")
    assert 'value="send_back"' in page, "no way to deny it"
    assert 'name="note"' in page, (
        "send-back with no reason is the Discard button under a new name")


def test_nobody_else_is_offered_it(studio):
    """A client publishing to themselves makes the taste gate decorative; a composer
    publishing their own take is not a review."""
    c, _db, _u, pid, ttok, ktok, _a = studio
    for who, page in (("client", c.get(f"/room/{pid}?k={ktok}").text),
                      ("creator", c.get(f"/room/{pid}?t={ttok}").text)):
        assert "/delivery/publish" not in page, f"the {who} is offered the taste gate"


def test_only_the_studio_holds_publish():
    assert R.can(R.OPERATOR, "publish")
    assert not R.can(R.TALENT, "publish")
    assert not R.can(R.CLIENT, "publish")


def test_the_gate_states_what_each_press_commits(studio):
    c, _db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    gate = page[page.index('class="gate"'):]
    gate = gate[:gate.index("</div>", gate.index("gate-row"))].lower()
    assert "emails them" in gate, "publishing does not say the client is told"
    assert "revision round" in gate, (
        "sending a take back does not say whether it costs the client a round")


# ── publishing ──────────────────────────────────────────────────────────────────────
def test_publishing_from_the_room_returns_to_the_room(studio):
    c, db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/delivery/publish",
               data={"action": "publish", "origin": "room"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"/room/{pid}")
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    assert [v["n"] for v in d["versions"]] == [1]
    assert not d.get("pending_version")


def test_the_console_still_returns_to_the_console(studio):
    """`origin` is additive; the console's own forms do not send it."""
    c, _db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/delivery/publish", data={"action": "publish"},
               follow_redirects=False)
    assert r.headers["location"] == f"/project/{pid}/delivery#versions"


# ── sending it back ─────────────────────────────────────────────────────────────────
def test_sending_a_take_back_reaches_the_person_who_made_it(studio):
    c, db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/publish",
           data={"action": "send_back", "note": "the low brass is fighting the VO",
                 "origin": "room"}, follow_redirects=False)
    conn = db.connect()
    try:
        assert not db.get_delivery(conn, pid).get("pending_version")
        talent = [e for e in db.list_project_events(conn, pid, role="talent")
                  if e["kind"] == "sent_back"]
        assert talent, "the composer is never told their take was sent back"
        assert "low brass" in talent[0]["body"], (
            "the reason is not carried, so it is a discard with a nicer name")
    finally:
        conn.close()


def test_the_client_is_never_told_a_take_was_sent_back(studio):
    """They never heard it. A buyer watching us reject our own work reads as a studio
    in trouble, and it is not their business either way."""
    c, db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/publish",
           data={"action": "send_back", "note": "not there yet", "origin": "room"},
           follow_redirects=False)
    conn = db.connect()
    client = [e for e in db.list_project_events(conn, pid, role="client")
              if e["kind"] == "sent_back"]
    conn.close()
    assert not client


def test_sending_back_does_not_spend_a_clients_round(studio):
    c, db, _u, pid, _t, _k, admin = studio
    conn = db.connect()
    before = int(db.get_delivery(conn, pid).get("revisions_used") or 0)
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/publish",
           data={"action": "send_back", "note": "another pass please", "origin": "room"},
           follow_redirects=False)
    conn = db.connect()
    after = int(db.get_delivery(conn, pid).get("revisions_used") or 0)
    conn.close()
    assert after == before, (
        "the studio's own second thoughts were charged to the client's budget")


def test_a_silent_discard_is_gone(studio):
    """The old action still resolves — but it can no longer vanish a take in silence."""
    c, db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/publish", data={"action": "discard"},
           follow_redirects=False)
    conn = db.connect()
    talent = [e for e in db.list_project_events(conn, pid, role="talent")
              if e["kind"] == "sent_back"]
    conn.close()
    assert talent, "discard still drops a composer's take without telling them"


def test_the_console_asks_for_a_reason_too():
    console = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
               / "web" / "templates" / "delivery_console.html").read_text(encoding="utf-8")
    assert 'value="send_back"' in console and 'name="note"' in console, (
        "the console can still discard a take without saying why")
    assert ">Discard<" not in console


def test_the_gate_no_ops_when_there_is_nothing_waiting(studio):
    c, db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/publish", data={"action": "publish"},
           follow_redirects=False)
    r = c.post(f"/project/{pid}/delivery/publish",
               data={"action": "send_back", "note": "x", "origin": "room"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/room/{pid}")
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    assert [v["n"] for v in d["versions"]] == [1], (
        "a second press unpublished the version it had just published")


# ── and one thing the console did not need ──────────────────────────────────────────
def test_the_console_shows_presence_without_replaying_the_notes(studio):
    """*"The comments up at the top of the delivery section is not needed"* — four rows
    of note text above the title, restating what the notes queue, the review tape and
    the room all show below it, and pushing the command centre off the first screen.
    Presence stays: who else is in the room right now is the one thing no other block on
    that page answers."""
    c, _db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    page = c.get(f"/project/{pid}/delivery").text
    assert 'id="session-room"' in page, "the console left the live layer entirely"
    assert 'data-feed="0"' in page, "the console still replays the notes above the title"
    js = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
          / "web" / "static" / "session-room.js").read_text(encoding="utf-8")
    assert 'root.dataset.feed' in js, "the feed is not opt-out, so removing it takes the room's with it"
    assert "if (!feed) return;" in js, (
        "a presence-only mount still tries to write events into a list it does not have")


def test_the_room_keeps_its_feed(studio):
    """The room is where an arrival or an approval landing live is worth seeing."""
    c, _db, _u, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    assert 'id="session-room"' in page and 'data-feed="0"' not in page
