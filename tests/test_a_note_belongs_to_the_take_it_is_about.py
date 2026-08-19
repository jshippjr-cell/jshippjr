"""A note lands on the take you are listening to, and reads itself out as you pass it.

Two from the room (operator, 2026-08-19): *"notes should attach to the take thats
playing"*, and *"as the playhead passes over the note button a preview of the note should
pop up"*.

The first replaces an apology. A note was recorded against the version under REVIEW
whatever was loaded, and the room said so out loud — *"Note left at 0:21 — on the take
under review, not the one you're auditioning."* Announcing the wrong behaviour clearly is
not the same as getting it right: a note is about a piece of music, and the take is which
piece of music it is.

The take is sent by the room and **validated** by the server, because a version string
from a form is not a fact. What is accepted: any take in the ladder, plus the number the
PENDING take will get on publish — and that one only for a caller who may see it, so a
client cannot file a note against a take they are not allowed to hear. Anything else
falls back to the version under review, which is where notes have always gone.

A reply is the exception: it inherits its parent's take. A reply answers that note, and
moving it would split one conversation across two versions.
"""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent

ROOM = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
        / "web" / "templates" / "creator_portal.html")


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
    db.update_delivery(conn, pid, "versions", [
        {"n": 1, "label": "v1 Concept", "url": "/uploads/v1.mp3"},
        {"n": 2, "label": "v2 Direction-lock", "url": "/uploads/v2.mp3"}])
    db.update_delivery(conn, pid, "version_state", "v2 Direction-lock")
    uploads._store_pending_submission(conn, pid, b"x" * 32, "v3.mp3", "Ada Cheng")
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return c, db, pid, ttok, ktok, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def _note(c, db, pid, version, **cred):
    c.post(f"/project/{pid}/review/comment",
           data=dict(t="5", body="a note", origin="room", version=version, **cred),
           follow_redirects=False)
    conn = db.connect()
    row = conn.execute(
        "SELECT version FROM review_comments ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row["version"] if row else None


# ── the take you are listening to ───────────────────────────────────────────────────
def test_a_note_lands_on_the_take_that_is_playing(studio):
    c, db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    assert _note(c, db, pid, "1") == "1", (
        "a note on an earlier take still files against the version under review")
    assert _note(c, db, pid, "2") == "2"


def test_a_note_on_the_pending_take_waits_for_it(studio):
    """The take that is with the studio becomes v3 on publish, so its notes are
    already there when it arrives."""
    c, db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    assert _note(c, db, pid, "3") == "3"


def test_a_creator_can_note_their_own_pending_take(studio):
    c, db, pid, ttok, _k, _a = studio
    assert _note(c, db, pid, "3", creator_token=ttok) == "3"


def test_a_client_cannot_attach_to_a_take_they_may_not_hear(studio):
    """Published versions only (ADR-0068). A note filed against the pending take would
    be a note about music the taste gate has not let them hear."""
    c, db, pid, _t, ktok, _a = studio
    assert _note(c, db, pid, "3", k=ktok, author="Marta", email="m@a.com") == "2"
    assert _note(c, db, pid, "1", k=ktok, author="Marta", email="m@a.com") == "1", (
        "a client cannot note an earlier published take either")


def test_a_version_from_a_form_is_not_a_fact(studio):
    """Anyone with a share link can post a version string. A note filed against a take
    that does not exist is a note nobody will ever see again."""
    c, db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    for junk in ("9", "0", "-1", "'; DROP TABLE review_comments--", "abc", ""):
        assert _note(c, db, pid, junk) == "2", f"accepted {junk!r}"


def test_a_reply_inherits_the_take_its_parent_is_on(studio):
    c, db, pid, _t, _k, admin = studio
    conn = db.connect()
    parent = db.add_review_comment(conn, pid, version="1", t_seconds=3, author="M",
                                   email="m@a.com", body="on v1", kind="comment")
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/review/comment",
           data={"parent_id": str(parent), "body": "answering it", "origin": "room",
                 "version": "3"}, follow_redirects=False)
    conn = db.connect()
    row = conn.execute(
        "SELECT version FROM review_comments ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row["version"] == "1", (
        "a reply moved to the take being auditioned, splitting one conversation across "
        "two versions")


def test_the_room_sends_the_take_it_has_loaded(studio):
    c, _db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    assert 'name="version" class="nb-version"' in page, (
        "the note bar does not say which take it is about")
    src = ROOM.read_text(encoding="utf-8")
    fn = src[src.index("function showVersion("):]
    fn = fn[:fn.index("function loadTake(")]
    assert "nb-version" in fn, (
        "selecting a take does not move the note bar with it, so the field goes stale")


def test_the_room_no_longer_apologises_for_the_take(studio):
    """The old behaviour, said out loud. Its absence is the point."""
    src = ROOM.read_text(encoding="utf-8")
    assert "not the one you're auditioning" not in src


# ── the note under the playhead ─────────────────────────────────────────────────────
def test_a_note_reads_itself_out_as_the_playhead_arrives():
    src = ROOM.read_text(encoding="utf-8")
    assert "pin-peek" in src, "no preview of the note the playhead is on"
    fn = src[src.index("function paintPeek()"):]
    fn = fn[:fn.index("function hidePeek()")]
    assert "mPaused()" in fn, (
        "the peek shows while the room is parked, where a pin is a thing you click")
    assert "n.t_end" in fn, (
        "a range note gets the same 2.2s tail as a point note instead of the stretch "
        "it actually covers")
    assert "shownVersion" in fn, (
        "the peek can show a note belonging to a take that is not loaded")


def test_the_peek_has_something_to_say(studio):
    """The logic was right and the data was not there: the room's pins payload carried
    `id/t/kind/version` and no words, so the bubble rendered a 56px sliver reading
    "Note" with an empty body. Caught in a browser, not by a test of the JS — so the
    test now reads the PAYLOAD.
    """
    import json
    c, db, pid, _t, _k, admin = studio
    conn = db.connect()
    nid = db.add_review_comment(conn, pid, version="2", t_seconds=5,
                                author="Marta Ruiz", email="m@a.com",
                                body='she said "sit it back" here', kind="comment",
                                author_role="client")
    db.set_comment_disposition(conn, pid, nid, "revision")
    conn.close()
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    blob = re.search(r'class="sr-notes-data">\s*(\[.*?\])\s*</script>', page, re.S)
    assert blob, "no pins payload"
    pins = json.loads(blob.group(1))          # a quote in a note must not break the JSON
    mine = [n for n in pins if n["id"] == nid]
    assert mine, pins
    assert mine[0]["body"] == 'she said "sit it back" here', (
        "the peek has no words to show")
    assert mine[0]["author"] == "Marta Ruiz"


def test_the_peek_names_the_studio_to_a_client(studio):
    """The payload is subject to the same subtraction as everything else (ADR-0070)."""
    import json
    c, db, pid, ttok, ktok, _a = studio
    conn = db.connect()
    nid = db.add_review_comment(conn, pid, version="2", t_seconds=9, author="Ada Cheng",
                                email="ada@x.com", body="reworked the low brass",
                                kind="comment", author_role="talent")
    db.set_comment_disposition(conn, pid, nid, "revision")
    conn.close()
    page = c.get(f"/room/{pid}?k={ktok}").text
    blob = re.search(r'class="sr-notes-data">\s*(\[.*?\])\s*</script>', page, re.S)
    mine = [n for n in json.loads(blob.group(1)) if n["id"] == nid]
    assert mine and mine[0]["author"] == "Chordential", (
        "the peek names the freelancer to the buyer")


def test_the_peek_follows_the_playhead_not_the_mouse():
    src = ROOM.read_text(encoding="utf-8")
    upd = src[src.index("function update(){"):]
    upd = upd[:upd.index("audio.addEventListener")]
    assert "paintPeek()" in upd, (
        "the peek is not driven by the frame loop, so it lags the head it is about")


def test_the_arrival_curtain_does_not_clip_the_peek_away():
    """Found in a browser, not in a unit test: on the FIRST-ever visit to a room the
    peek rendered with `opacity: 1` and was invisible.

    `.sr-spine.drawing` performs the spine's draw-in with a `clip-path`, and the class
    was left on for the life of the page — so a clip equal to the spine's own box stayed
    applied. Nothing noticed until something needed to paint OUTSIDE that box. The peek
    sits above the notes lane, so it was erased on every first load and the feature
    simply did not exist for anyone opening a room for the first time.
    """
    src = ROOM.read_text(encoding="utf-8")
    assert ".sr-spine.drawn{" in src, (
        "there is no post-animation state, so the clip that drew the spine outlives it")
    js = src[src.index('spine.classList.add("drawing")'):]
    js = js[:js.index("function begin()")]
    assert 'removeEventListener' in js and 'animationend' in js, (
        "the drawing class is never handed off, so the clip stays for the life of the page")
    assert "setTimeout" in js, (
        "no fallback: a browser that does not fire animationend keeps the clip forever")
