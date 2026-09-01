"""A composer submits v2, and everything about the room still says v1.

Four reports from one round of live testing (operator, 2026-08-19):

  *"acting as the client, inside the portal i made some notes and then clicked to
  request changes and it took me out to the client workspace, im not entirely sure that
  necessary."*

  *"after uploading V2 from the composer side, the alert went out to approve which is
  great, no badge showed up in the dashboard letting me know something new happened."*

  *"when i logged into 'the room' V1 was loaded, and the notes from V1 was there, V2
  should be loaded and labelled as v2 with a fresh pane for new notes to be input."*

  *"I click v to bring up the takes view, it requires me to click play in order for v2 to
  be loaded, and it instantly starts playing v2, it should just load the track and the
  notes along with it."*

Underneath them is one idea the room had not been built on: **a take and its notes are
one thing**. Notes were filtered to the version under review and rendered once, so there
was nothing for selecting a take to select. Once a note knows which take it was written
against, the newest take can lead, an unheard take can open on an empty pane, and a
click can mean *load this* rather than *play this now*.

The verdict and the badge are the same idea one layer out: the room is where the work is
heard, so it is where the verdict is given and where "something arrived" has to be
legible.
"""
import json
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
                       [{"n": 1, "label": "v1 Concept", "url": "/uploads/v1.mp3"}])
    db.update_delivery(conn, pid, "version_state", "v1 Concept")
    nid = db.add_review_comment(conn, pid, version="1", t_seconds=7, author="Marta",
                                email="m@a.com", body="brass on v1", kind="comment",
                                author_role="client")
    db.set_comment_disposition(conn, pid, nid, "revision")
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return c, db, pid, ttok, ktok, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def _chips(page):
    return [(("on" in cls.split()), ver, re.sub(r"<[^>]+>", "", label).strip())
            for cls, ver, label in re.findall(
                r'<button class="take-chip([^"]*)"[^>]*data-version="([^"]*)"[^>]*>(.*?)</button>',
                page, re.S)]


def _submit_v2(db, pid):
    from chordential_oia.web import uploads
    conn = db.connect()
    uploads._store_pending_submission(conn, pid, b"x" * 64, "v2.mp3", "Ada Cheng")
    conn.close()


# ── 1. the verdict does not relocate the client ─────────────────────────────────────
def test_requesting_changes_from_the_room_stays_in_the_room(studio):
    c, _db, pid, _t, ktok, _a = studio
    r = c.post(f"/project/{pid}/review/changes",
               data={"k": ktok, "author": "Marta Ruiz", "email": "m@a.com",
                     "body": "more ambient lead vocals", "origin": "room"},
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"/room/{pid}?k={ktok}"), r.headers["location"]


def test_approving_from_the_room_stays_in_the_room(studio):
    c, _db, pid, _t, ktok, _a = studio
    r = c.post(f"/project/{pid}/review/approve",
               data={"k": ktok, "author": "Marta Ruiz", "email": "m@a.com",
                     "origin": "room"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"/room/{pid}?k={ktok}")


def test_the_delivery_portal_still_returns_to_itself(studio):
    """`origin` is additive. The portal's own forms do not send it and must not move."""
    c, _db, pid, _t, ktok, _a = studio
    r = c.post(f"/project/{pid}/review/changes",
               data={"k": ktok, "author": "M", "email": "m@a.com", "body": "x"},
               follow_redirects=False)
    assert "/delivery-portal" in r.headers["location"]


def test_the_rooms_verdict_forms_declare_their_origin(studio):
    c, _db, pid, _t, ktok, _a = studio
    page = c.get(f"/room/{pid}?k={ktok}").text
    verdict = page[page.index('class="verdict"'):]
    verdict = verdict[:verdict.index("</div>", verdict.index("review/changes"))]
    assert verdict.count('name="origin" value="room"') == 2, (
        "a verdict form does not say it came from the room, so pressing it ejects the "
        "client to the delivery portal")


# ── 2. something arrived ────────────────────────────────────────────────────────────
def _badge(page):
    m = re.search(r'id="queue-badge"[^>]*style="display:([a-z-]+)[^>]*>([^<]*)<', page)
    return None if not m else (m.group(1), m.group(2).strip())


def test_a_submission_raises_a_badge_where_the_operator_is_standing(studio):
    c, db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    assert _badge(c.get("/dashboard").text) == ("none", ""), "a badge with nothing waiting"
    _submit_v2(db, pid)
    assert _badge(c.get("/dashboard").text) == ("inline-block", "1"), (
        "a composer submitted a take and no page said so")


def test_the_badge_clears_when_the_take_is_published(studio):
    c, db, pid, _t, _k, admin = studio
    c.cookies.set(*admin)
    _submit_v2(db, pid)
    from chordential_oia.web.project_routes import _publish_pending_submission
    conn = db.connect()
    _publish_pending_submission(conn, pid)
    conn.close()
    assert _badge(c.get("/dashboard").text) == ("none", ""), (
        "the badge outlives the thing it is about")


def test_the_count_is_of_submissions_not_projects(studio):
    c, db, pid, _t, _k, _a = studio
    conn = db.connect()
    other = db.insert_project(conn, None, "Someone", "Other", 1, 2, ["Composer"])
    conn.close()
    _submit_v2(db, pid)
    _submit_v2(db, other)
    conn = db.connect()
    assert db.pending_submission_count(conn) == 2
    conn.close()


# ── 3. the newest take leads ────────────────────────────────────────────────────────
def test_the_room_opens_on_the_take_that_just_arrived(studio):
    c, db, pid, _t, _k, admin = studio
    _submit_v2(db, pid)
    c.cookies.set(*admin)
    chips = _chips(c.get(f"/room/{pid}").text)
    assert len(chips) == 2, chips
    on = [ch for ch in chips if ch[0]]
    assert len(on) == 1 and on[0][1] == "", (
        "the room still opens on the last published take while a newer one sits in it")
    assert on[0][2].startswith("v2"), (
        f"the newest take is not labelled with the version it will get: {on[0][2]!r}")


def test_the_client_never_gets_the_unpublished_take(studio):
    """Published versions only (ADR-0068) — the taste gate is the whole point."""
    c, db, pid, _t, ktok, _a = studio
    _submit_v2(db, pid)
    chips = _chips(c.get(f"/room/{pid}?k={ktok}").text)
    assert [ch[1] for ch in chips] == ["1"], chips
    assert chips[0][0], "the client's only take is not the one loaded"


# ── 4. a take and its notes are one thing ───────────────────────────────────────────
def test_every_note_names_the_take_it_was_written_against(studio):
    c, db, pid, _t, _k, admin = studio
    _submit_v2(db, pid)
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    blob = re.search(r'class="sr-notes-data">\s*(\[.*?\])\s*</script>', page, re.S)
    assert blob, "no pins data"
    pins = json.loads(blob.group(1))
    assert pins and all("version" in n for n in pins), (
        "a pin does not know its take, so it cannot be hidden when another is selected")
    assert re.search(r'data-note="\d+" data-version="1"', page), (
        "the note cards carry no version")


def test_the_room_shows_only_the_selected_takes_notes():
    src = ROOM.read_text(encoding="utf-8")
    assert "function showVersion(" in src, "nothing switches the note set with the take"
    fn = src[src.index("function showVersion("):]
    fn = fn[:fn.index("function loadTake(")]
    assert "card.hidden" in fn, "the notes for other takes are not hidden"
    assert "fb-empty-take" in fn, (
        "a take with no notes shows an empty pane and no explanation of why")
    load = src[src.index("function loadTake(chip){"):]
    load = load[:load.index("function decodePeaks")]
    # Bounded by the FUNCTION rather than by a character count. The old `[:400]` window
    # was a proxy for "inside loadTake", and a comment explaining why the resume waits for
    # `loadedmetadata` pushed the call past it. What matters is that loading a take brings
    # its notes — not where in the body the line happens to sit.
    assert "showVersion(chip.dataset.version" in load, (
        "loading a take does not bring its notes")


def test_a_pin_belongs_to_its_take():
    src = ROOM.read_text(encoding="utf-8")
    fn = src[src.index("function renderPins()"):]
    fn = fn[:fn.index("// The whisper is the room's one voice")]
    assert 'n.version || ""' in fn and "shownVersion" in fn, (
        "every take's pins are drawn on one lane at once")


def test_selecting_a_take_does_not_start_it(studio):
    """Two intentions, two controls: the row loads it, ▶ auditions it."""
    c, db, pid, _t, _k, admin = studio
    _submit_v2(db, pid)
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    assert 'class="take-row sr-take-row"' in page, (
        "a take row is not selectable; the only way to load one is to play it")
    src = ROOM.read_text(encoding="utf-8")
    # the row handler, not `showVersion` (which also walks `.sr-take-row` to mark
    # which one is loaded) — anchor on the comment that introduces it
    rows = src[src.index("// Selecting a take: load it and its notes"):]
    rows = rows[:rows.index('root.querySelectorAll(".sr-row-play")')]
    assert "audio.play()" not in rows, (
        "selecting a take starts playback — that is the report, not the fix")
    assert "closeAllSheets" not in rows, (
        "selecting a take shuts the sheet you are choosing from")
    assert "showVersion(" in rows, "selecting a take does not bring its notes"
