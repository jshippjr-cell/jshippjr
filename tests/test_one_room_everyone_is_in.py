"""One engagement is one room, and the people doing the work are in it.

Reported live, after assigning one creator three roles on one project: *"i assigned
myself to three overlapping tasks (composer, editor, and Mixer) and the video shows up 3
separate times in the portal. it should only show up once. Think google docs where its
one central doc but different user accessing the same doc and each person can see one
another because they've been given a thumbnail and a color to identify them."*

Two things were wrong underneath that.

**The room was keyed by assignment, not by engagement.** ``_creator_assignment_view``
built one card per assignment ROW, so three hats on one project rendered the same
picture, the same take and the same brief three times down the page.

**The creator could not join the live room at all.** The room's presence and event bus
(``/project/<id>/session.json`` + ``/presence``) resolved exactly two roles — client and
operator. The one person actually doing the work had no role, so the composer never saw
who else was here and never appeared to anyone who was. The bus, the role-filtered event
stream and the presence TTL all already existed; the talent arm did not.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "room.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _creator_on(app_mod, roles, *, name="Jon Shipp"):
    """One creator, wearing `roles` on a single project."""
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    db = app_mod.db
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        tid = db.insert_talent(conn, Talent(
            name=name, email="jon@example.com", rate=90.0,
            disciplines=[MusicDiscipline.COMPOSITION]))
        for role in roles:
            db.add_assignment(conn, pid, role, tid)
        return pid, tid, db.ensure_talent_portal_token(conn, tid)
    finally:
        conn.close()


# ── one engagement, one room ────────────────────────────────────────────────────────
def test_three_hats_on_one_project_are_one_room(studio):
    from chordential_oia.web.creator_routes import _creator_assignment_view
    _c, app_mod = studio
    pid, tid, _tok = _creator_on(app_mod, ["Composer", "Music Editor", "Mixer"])
    conn = app_mod.db.connect()
    try:
        view = _creator_assignment_view(conn, tid)
    finally:
        conn.close()
    assert len(view) == 1, f"the engagement rendered {len(view)} times"
    assert view[0]["project_id"] == pid


def test_the_hats_are_named_on_the_one_room(studio):
    """Collapsing them must not lose them — the creator still needs to know they are
    also the mixer on this."""
    from chordential_oia.web.creator_routes import _creator_assignment_view
    _c, app_mod = studio
    _pid, tid, _tok = _creator_on(app_mod, ["Composer", "Music Editor", "Mixer"])
    conn = app_mod.db.connect()
    try:
        room = _creator_assignment_view(conn, tid)[0]
    finally:
        conn.close()
    # `list_talent_assignments` orders by role, so the room reads them alphabetically.
    assert room["roles"] == ["Composer", "Mixer", "Music Editor"]
    assert room["role"] == "Composer · Mixer · Music Editor"


def test_the_page_renders_the_engagement_once_however_many_hats(studio):
    """Measured against a ONE-hat baseline rather than a fixed count: the room legitimately
    names the cut more than once (the player, and the download for their DAW). What must
    not change is how many times the ROOM appears."""
    c, app_mod = studio
    db = app_mod.db

    def _render(roles, email):
        from chordential_oia.models import MusicDiscipline
        from chordential_oia.talent import Talent
        conn = db.connect()
        try:
            pid = conn.execute(
                "SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
            tid = db.insert_talent(conn, Talent(
                name="Jon Shipp", email=email, rate=90.0,
                disciplines=[MusicDiscipline.COMPOSITION]))
            for role in roles:
                db.add_assignment(conn, pid, role, tid)
            db.update_delivery(conn, pid, "picture", {
                "url": "/uploads/cut-1.mp4", "orig": "winter.mp4", "n": 1,
                "by": "Marta", "at": "2026-08-18"})
            tok = db.ensure_talent_portal_token(conn, tid)
        finally:
            conn.close()
        return c.get(f"/creator/{tok}").text

    one = _render(["Composer"], "one@example.com")
    three = _render(["Composer", "Music Editor", "Mixer"], "three@example.com")
    assert three.count("/uploads/cut-1.mp4") == one.count("/uploads/cut-1.mp4"), (
        "the cut is rendered once per hat instead of once per engagement")
    assert three.count('class="room sr-room"') == one.count('class="room sr-room"') == 1


def test_separate_projects_still_get_separate_rooms(studio):
    """The dedupe is per PROJECT. Two engagements must not collapse into one."""
    from chordential_oia.web.creator_routes import _creator_assignment_view
    _c, app_mod = studio
    db = app_mod.db
    _pid, tid, _tok = _creator_on(app_mod, ["Composer"])
    conn = db.connect()
    try:
        others = conn.execute(
            "SELECT id FROM projects ORDER BY id LIMIT 2").fetchall()
        if len(others) < 2:
            pytest.skip("the demo set has only one project")
        db.add_assignment(conn, others[1]["id"], "Composer", tid)
        view = _creator_assignment_view(conn, tid)
    finally:
        conn.close()
    assert len({v["project_id"] for v in view}) == 2
    assert len(view) == 2


# ── everyone is in the room ─────────────────────────────────────────────────────────
def test_the_creator_is_a_role_in_the_room(studio):
    from chordential_oia.web.project_routes import _session_role
    _c, app_mod = studio
    pid, _tid, tok = _creator_on(app_mod, ["Composer"])
    conn = app_mod.db.connect()
    try:
        role, name = _session_role(conn, pid, "", "", tok)
    finally:
        conn.close()
    assert role == "talent", "the person doing the work still has no role in the room"
    assert name == "Jon Shipp"


def test_a_creators_token_does_not_open_a_project_they_are_not_on(studio):
    """A portal token is a credential for a CREATOR, not a skeleton key to every room."""
    from chordential_oia.web.project_routes import _session_role
    _c, app_mod = studio
    db = app_mod.db
    _pid, _tid, tok = _creator_on(app_mod, ["Composer"])
    conn = db.connect()
    try:
        rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
        elsewhere = next((r["id"] for r in rows if r["id"] != _pid), None)
        if elsewhere is None:
            pytest.skip("only one project in the demo set")
        role, _name = _session_role(conn, elsewhere, "", "", tok)
    finally:
        conn.close()
    assert role is None


def test_presence_and_the_feed_answer_the_creator(studio):
    c, app_mod = studio
    pid, _tid, tok = _creator_on(app_mod, ["Composer"])
    ping = c.post(f"/project/{pid}/presence", data={"t": tok, "name": "Jon Shipp"})
    assert ping.status_code == 200
    poll = c.get(f"/project/{pid}/session.json", params={"t": tok})
    assert poll.status_code == 200
    body = poll.json()
    assert any(p["role"] == "talent" and p["name"] == "Jon Shipp"
               for p in body["presence"]), body["presence"]


def test_the_client_sees_the_studio_in_the_room_and_not_the_roster(studio):
    """One room, and the people in it can see each other — but a client sees ONE of us.

    This test used to assert the composer's own name reached the client's roster, and
    that is exactly what the executive review would not put in front of a real client
    (ADR-0070): the buyer learns who we hired, live, as they arrive and leave. The
    presence itself is the point and stays — someone IS here with you — collapsed to
    the studio.
    """
    c, app_mod = studio
    pid, _tid, tok = _creator_on(app_mod, ["Composer"])
    conn = app_mod.db.connect()
    try:
        share = app_mod.db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    c.post(f"/project/{pid}/presence", data={"t": tok, "name": "Jon Shipp"})
    seen = c.get(f"/project/{pid}/session.json", params={"k": share}).json()["presence"]
    assert not any(p["name"] == "Jon Shipp" for p in seen), (
        "the client's roster names the creator we hired")
    assert any(p["name"] == "Chordential" for p in seen), (
        "the client cannot tell that anyone is in the room with them at all")


def test_the_composer_room_mounts_the_live_layer(studio):
    c, app_mod = studio
    _pid, _tid, tok = _creator_on(app_mod, ["Composer"])
    page = c.get(f"/creator/{tok}").text
    assert 'id="session-room"' in page, "the composer's room never joins the room"
    assert 'data-role="talent"' in page
    assert 'data-token-kind="t"' in page
    assert "session-room.js" in page


def test_a_bad_creator_token_is_refused_by_the_bus(studio):
    c, app_mod = studio
    pid, _tid, _tok = _creator_on(app_mod, ["Composer"])
    assert c.get(f"/project/{pid}/session.json", params={"t": "nope"}).status_code == 404
    assert c.post(f"/project/{pid}/presence",
                  data={"t": "nope", "name": "X"}).status_code == 404
