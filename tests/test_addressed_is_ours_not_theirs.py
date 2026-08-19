"""Marking a note ADDRESSED failed in the room, and the button was on the wrong screen.

Reported live, with a screenshot: *"what happens when a note is 'marked addressed' im
getting an error when i click it"* — the room answered "Couldn't update the note. Try
again." every time.

Two defects behind one press.

**The door was the composer's, not the room's.** The form posted to
``/creator/{token}/project/{id}/note/{id}/address``, and ``token`` is only ever set for a
creator. The studio's copy of the room and the client's therefore rendered
``/creator//project/…`` — an empty path segment — and every press missed. The state
belongs to the room, so the door is the room's: whichever credential got you in works
here, and ``room.CAPS`` decides whether your role may press it.

**And a client should never have seen it.** "Addressed" means *this note is dealt with in
the take I am about to submit* — our working state, deliberately not the client's
``resolved``, which they set after HEARING the take (EP P0-1). A button on the buyer's own
screen that closes a note nobody has worked yet is a round spent on nothing.

Third, found while proving the first: the composer's OWN portal never set ``room_token``
either, so the note bar there posted an empty creator token and every note a composer
wrote from their own page was dropped with "That note did not send."
"""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent
from chordential_oia.web import room as R

ROOM = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
        / "web" / "templates" / "creator_portal.html")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    # `db.DEFAULT_DB_PATH` is read at IMPORT time, so reloading only `app` leaves every
    # connection pointed at whatever database the first import saw — tests then share one
    # file and a count from a previous test leaks into this one. Reload db FIRST.
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db
    c = TestClient(app_mod.app)
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "AURORA", "Launch film", 1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Ada Cheng", email="ada@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    ttok = db.ensure_talent_portal_token(conn, tid)
    ktok = db.rotate_share_token(conn, project_id=pid)
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1", "url": "/uploads/a.mp3"}])
    db.update_delivery(conn, pid, "version_state", "v1")
    nid = db.add_review_comment(conn, pid, version="1", t_seconds=3, author="Marta",
                                email="m@a.com", body="brass too loud",
                                kind="comment", author_role="client")
    db.set_comment_disposition(conn, pid, nid, "revision")
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return c, db, pid, ttok, ktok, nid, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def _press(c, pid, nid, **cred):
    return c.post(f"/project/{pid}/review/address",
                  data=dict(comment_id=nid, **cred), follow_redirects=False)


# ── the door ────────────────────────────────────────────────────────────────────────
def test_no_room_form_ever_renders_an_empty_credential(studio):
    """The defect, exactly: `/creator//project/…`. `token` is only ever set for a
    creator, so every form in the room built from it broke for the studio and the
    client — Mark addressed, the talk-back reply, and the Capture shelf."""
    c, _db, pid, ttok, ktok, _nid, admin = studio
    for who, page in (("creator", c.get(f"/room/{pid}?t={ttok}").text),):
        assert "/creator//" not in page, f"the {who}'s room posts to an empty token"
        assert f"/project/{pid}/review/address" in page, (
            f"the {who}'s room has no address form")
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    assert "/creator//" not in page, "the studio's room posts to an empty token"
    assert f"/project/{pid}/review/address" in page


def test_the_studio_can_mark_a_note_addressed(studio):
    c, db, pid, _t, _k, nid, admin = studio
    c.cookies.set(*admin)
    assert _press(c, pid, nid).status_code == 303
    conn = db.connect()
    assert conn.execute(
        "SELECT composer_addressed FROM review_comments WHERE id=?",
        (nid,)).fetchone()[0] == 1
    conn.close()


def test_the_creator_can_mark_a_note_addressed(studio):
    c, _db, pid, ttok, _k, nid, _a = studio
    assert _press(c, pid, nid, t=ttok).status_code == 303


def test_a_client_may_not_press_ours(studio):
    """They hold `resolved`, which they set after hearing the take. Ours says the work
    is done — a buyer closing it would close a note nobody had worked."""
    c, db, pid, _t, ktok, nid, _a = studio
    assert _press(c, pid, nid, k=ktok).status_code == 404
    conn = db.connect()
    assert conn.execute(
        "SELECT composer_addressed FROM review_comments WHERE id=?",
        (nid,)).fetchone()[0] == 0
    conn.close()


def test_no_credential_is_not_the_studio(studio):
    """`/project/{id}/review/address` is gate-exempt so a creator can reach it. An
    exemption is only granted to a route that makes its own stricter check."""
    c, _db, pid, _t, _k, nid, _a = studio
    assert _press(c, pid, nid).status_code == 404


def test_a_note_from_another_project_is_refused(studio):
    c, db, pid, ttok, _k, _nid, _a = studio
    conn = db.connect()
    other = db.insert_project(conn, None, "Someone else", "Other", 1, 2, ["Composer"])
    stray = db.add_review_comment(conn, other, version="1", author="X", email="x@y.com",
                                  body="not yours", kind="comment")
    conn.close()
    assert _press(c, pid, stray, t=ttok).status_code == 404


# ── whose button it is ──────────────────────────────────────────────────────────────
def test_the_capability_is_ours_alone():
    assert R.can(R.TALENT, "address_note") and R.can(R.OPERATOR, "address_note")
    assert not R.can(R.CLIENT, "address_note")
    # And the talk-back channel is composer↔studio by definition.
    assert R.can(R.TALENT, "ask_studio")
    assert not R.can(R.CLIENT, "ask_studio")


def test_the_client_is_offered_neither(studio):
    c, _db, pid, _t, ktok, _nid, _a = studio
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "/review/address" not in page, (
        "the client is offered OUR working state — one press closes a note nobody "
        "has worked")
    assert 'class="nc-addr sr-ask"' not in page, (
        "the client is offered the composer's internal talk-back channel")
    assert '<form class="ask-form"' not in page, (
        "the client's room still carries the composer↔studio reply form")


# ── the third one, found while proving the first ────────────────────────────────────
def test_a_composer_can_leave_a_note_from_their_own_portal(studio):
    """The note bar posts `room_token`, and the composer's own page never set it — so
    every note written there posted an empty credential and was dropped."""
    c, _db, pid, ttok, _k, _nid, _a = studio
    page = c.get(f"/creator/{ttok}").text
    bar = page[page.index('class="notebar sr-notebar"'):][:900]
    creds = dict(re.findall(r'name="(k|r|creator_token)" value="([^"]*)"', bar))
    assert creds.get("creator_token") == ttok, (
        "the composer's own portal sends no credential with a note")
    r = c.post(f"/project/{pid}/review/comment",
               data={"creator_token": ttok, "t": "3", "body": "from the portal",
                     "origin": "room"}, follow_redirects=False)
    assert r.status_code == 303, "the note was dropped"


# ── the class of bug, not the instance ──────────────────────────────────────────────
def test_no_form_in_the_room_is_built_from_the_creator_token_alone(studio):
    """FOUR forms had the same defect, found one at a time: Mark addressed, the
    talk-back reply, the Capture shelf and the version uploader. Each was written on
    the composer's own portal, where `token` is always real, and each broke silently
    the day the room started serving three roles from one template.

    The rule: a form whose action embeds `/creator/{token}/` must be gated on a
    capability only a CREATOR holds, so the token is real wherever it renders. This
    checks the rendered page for every role — the one place the truth is visible.
    """
    c, _db, pid, ttok, ktok, _nid, admin = studio
    pages = {"creator": c.get(f"/room/{pid}?t={ttok}").text,
             "client": c.get(f"/room/{pid}?k={ktok}").text,
             "composer portal": c.get(f"/creator/{ttok}").text}
    c.cookies.set(*admin)
    pages["studio"] = c.get(f"/room/{pid}").text
    for who, page in pages.items():
        assert "/creator//" not in page, (
            f"the {who}'s room renders a form with an empty creator token; every "
            f"press of it fails")
