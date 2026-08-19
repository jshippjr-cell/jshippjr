"""The room had one voice, and it was the composer's.

Reported live, from a client's own room (operator, 2026-08-19):

  *"I entered the room as a client and the note at the bottom left of the video is 'the
  room is current. write' that is not how we speak to our clients. im sure that was not
  meant for the client it was meant for the composer, but even that is not a nice message
  to send to someone who is working for you."*

Both halves land. The first is a leak of exactly the kind ADR-0068 exists to stop, one
layer up from data: the buyer was being handed a line addressed to someone else, and it
told them to write music. The second is the sharper one — it was an imperative, to a
person doing the work, from the people paying them. A studio talks to the writers it
hires the way it wants to be talked to.

It was never one line. The whole template was written in the composer's voice and then
started serving three roles: a client on their OWN cut was offered "⇓ DOWNLOAD FOR YOUR
DAW", told a room was "waiting for your music", shown "Your takes", and given the
composer's working-state vocabulary in a sheet titled "Client feedback" about their own
notes.
"""
import html
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def studio(tmp_path, monkeypatch):
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
    pid = db.insert_project(conn, None, "The Larkspur Trust",
                            "Three-minute fundraising film", 1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Ada Cheng", email="ada@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    ttok = db.ensure_talent_portal_token(conn, tid)
    ktok = db.rotate_share_token(conn, project_id=pid)
    db.update_delivery(conn, pid, "picture", {"url": "/uploads/c1.mp4", "n": 1,
                                              "orig": "852233954.MP4",
                                              "at": "2026-08-01T00:00:00+00:00"})
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1 Concept", "url": "/uploads/v1.mp3"}])
    db.update_delivery(conn, pid, "version_state", "v1 Concept")
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return c, db, pid, ttok, ktok, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def _words(page: str) -> str:
    """What a person actually READS: markup, script and comments removed."""
    body = page[page.index("<body>"):]
    body = re.sub(r"(?s)<script.*?</script>", " ", body)
    body = re.sub(r"(?s)<style.*?</style>", " ", body)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(body))


# ── nothing addressed to someone else ───────────────────────────────────────────────
COMPOSER_VOICE = [
    "the room is current. write",
    "for your daw",
    "waiting for your music",
    "waiting for your first",
    "your takes",
    "your working state",
    "yours to write",
    "drop your take",
    "upload your take",
    "your role:",
]


def test_the_client_is_never_handed_a_line_written_for_the_composer(studio):
    c, _db, pid, _t, ktok, _a = studio
    words = _words(c.get(f"/room/{pid}?k={ktok}").text).lower()
    found = [p for p in COMPOSER_VOICE if p in words]
    assert not found, f"the client's room still says {found}"


def test_the_client_is_told_what_is_there_and_what_they_can_do(studio):
    c, _db, pid, _t, ktok, _a = studio
    words = _words(c.get(f"/room/{pid}?k={ktok}").text)
    assert "leave a note at any moment" in words, (
        "the room does not tell the buyer the one thing it is for")
    assert "DOWNLOAD YOUR CUT" in words, "the cut is still offered in DAW language"


def test_the_composer_is_not_given_an_order(studio):
    """*"even that is not a nice message to send to someone who is working for you."*"""
    c, _db, pid, ttok, _k, _a = studio
    words = _words(c.get(f"/room/{pid}?t={ttok}").text)
    assert "The room is current. Write." not in words
    assert "up to date" in words.lower(), (
        "the composer is told nothing at all now, which is its own kind of rude")


def test_the_composer_keeps_the_language_of_their_own_craft(studio):
    """Softening the tone must not take the room's usefulness with it: the composer's
    room is still the one that downloads a cut for a DAW and holds their takes."""
    c, _db, pid, ttok, _k, _a = studio
    words = _words(c.get(f"/room/{pid}?t={ttok}").text)
    assert "DOWNLOAD FOR YOUR DAW" in words
    assert "Your takes" in words


def test_the_studio_gets_the_state_not_a_pep_talk(studio):
    c, _db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    words = _words(c.get(f"/room/{pid}").text)
    assert "Up to date." in words or "on the timeline" in words, words[:400]
    assert "Write." not in words


# ── the drop target is furniture for a hand that may upload ─────────────────────────
def test_the_clients_page_does_not_carry_the_upload_target(studio):
    """The JS already refused to raise it without an upload form, so it never showed —
    but "Drop your take · LANDS WITH THE STUDIO FIRST" was sitting in the buyer's page
    waiting for one line of CSS to go wrong. Absent, not hidden (ADR-0068)."""
    c, _db, pid, ttok, ktok, _a = studio
    assert 'id="dropveil"' not in c.get(f"/room/{pid}?k={ktok}").text
    assert 'id="dropveil"' in c.get(f"/room/{pid}?t={ttok}").text


def test_a_room_with_no_drop_target_survives_a_stray_drag():
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    assert "function dvClass(on){ if (dv)" in src, (
        "the drag handlers touch the veil unguarded; a client dragging a file onto their "
        "own room throws")
    # exactly one touch of the element, and it is the guarded one
    assert src.count("dv.classList") == 1, (
        "an unguarded touch of the veil is back — every path must go through dvClass()")


# ── the sheets are named for who opens them ─────────────────────────────────────────
def test_the_sheets_are_titled_for_the_person_reading_them(studio):
    c, _db, pid, ttok, ktok, _a = studio
    client = _words(c.get(f"/room/{pid}?k={ktok}").text)
    talent = _words(c.get(f"/room/{pid}?t={ttok}").text)
    assert "Notes on this take" in client and "Client feedback" not in client, (
        "the client's own notes are filed under 'Client feedback'")
    assert "Client feedback" in talent, (
        "the composer lost the label that says whose notes these are")
    assert "The takes" in client and "Your takes" not in client
