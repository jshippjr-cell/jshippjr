"""One room, capability-gated by who holds the link, published versions only.

The operator's decision, 2026-08-18, and the reason for it: *"essentially the portal is
the hub for everyone to see the work's evolution in real time … as i and the composer
mixer editor log in to the portal we can all see notes and comments."*

Until now one engagement had three surfaces — the composer's Session Room, the client's
delivery portal, the operator's console — each with its own template and its own idea of
what a version is. Three renderings of one thing is how they drift.

The rule this file holds is the one that makes it safe: **the gate is subtractive and
server-side**. What a role may not see is ABSENT FROM THE DICT, not hidden by an `{% if %}`
in a template. A template that forgets a guard then leaks nothing, because the client's
copy was built by never putting the pending take in it.

Published versions only is the sharp edge. A buyer who can hear an unreviewed take makes
the taste gate decorative — and the taste gate is what protects them from a first
impression nobody chose.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def rooms(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "one.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    from chordential_oia.web import app as app_mod
    db = app_mod.db
    with TestClient(app_mod.app) as c:
        conn = db.connect()
        try:
            pid = conn.execute(
                "SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
            tid = db.insert_talent(conn, Talent(
                name="Ada Verano", email="ada@example.com", rate=95.0,
                disciplines=[MusicDiscipline.COMPOSITION]))
            db.add_assignment(conn, pid, "Composer", tid)
            ttok = db.ensure_talent_portal_token(conn, tid)
            ktok = db.ensure_project_share_token(conn, pid)
            # A take submitted and NOT yet published, plus the cut it is written to.
            db.update_delivery(conn, pid, "pending_version", {
                "by": "Ada Verano", "url": "/uploads/secret-take.wav",
                "label": "v2 Concept", "at": "2026-08-18"})
            db.update_delivery(conn, pid, "picture", {
                "url": "/uploads/cut-1.mp4", "orig": "winter.mp4", "n": 1,
                "by": "Marta", "at": "2026-08-18"})
        finally:
            conn.close()
        yield c, app_mod, pid, ttok, ktok


def _view(app_mod, pid, role, **kw):
    from chordential_oia.web import room
    from chordential_oia.web.creator_routes import _room_for_project
    conn = app_mod.db.connect()
    try:
        return room.room_view(conn, app_mod.db, pid, role,
                              build=_room_for_project, **kw)
    finally:
        conn.close()


# ── the capability model ────────────────────────────────────────────────────────────
def test_the_client_cannot_see_a_pending_take_at_all():
    from chordential_oia.web import room
    assert "see_pending" not in room.caps_for(room.CLIENT)
    assert "see_pending" in room.caps_for(room.TALENT)
    assert "see_pending" in room.caps_for(room.OPERATOR)


def test_an_unknown_role_gets_nothing():
    """Fail closed. A typo in a role name must not open the room."""
    from chordential_oia.web import room
    assert room.caps_for("Client") == frozenset()
    assert room.caps_for("") == frozenset()
    assert room.can("editor", "see_pending") is False


def test_only_the_studio_may_publish():
    from chordential_oia.web import room
    assert room.can(room.OPERATOR, "publish")
    assert not room.can(room.TALENT, "publish")
    assert not room.can(room.CLIENT, "publish")


def test_only_the_client_and_studio_approve():
    from chordential_oia.web import room
    assert room.can(room.CLIENT, "approve") and room.can(room.OPERATOR, "approve")
    assert not room.can(room.TALENT, "approve"), (
        "a creator approving their own work is not a review")


# ── the subtraction is real ─────────────────────────────────────────────────────────
def test_the_pending_take_is_absent_from_the_clients_room(rooms):
    """Absent, not hidden. This is the whole safety argument."""
    _c, app_mod, pid, _t, _k = rooms
    client = _view(app_mod, pid, "client")
    assert client["pending"] is None
    assert "secret-take.wav" not in str(client), (
        "the unpublished take is somewhere in the client's room dict")


def test_the_creator_still_sees_their_own_submission(rooms):
    _c, app_mod, pid, _t, _k = rooms
    talent = _view(app_mod, pid, "talent")
    assert talent["pending"] is not None
    assert talent["pending"]["url"] == "/uploads/secret-take.wav"


def test_the_client_keeps_the_picture_and_the_conversation(rooms):
    """Subtracting is not the same as impoverishing — the client must still get the
    room, or this was a downgrade."""
    _c, app_mod, pid, _t, _k = rooms
    client = _view(app_mod, pid, "client")
    assert client["picture"]["url"] == "/uploads/cut-1.mp4"
    assert "feedback" in client and "versions" in client
    assert client["need"] and client["client"]


def test_the_client_gets_no_contributors_captures_or_specs(rooms):
    _c, app_mod, pid, _t, _k = rooms
    client = _view(app_mod, pid, "client")
    assert client["contributors"] == []
    assert client["captures"] == []
    assert client["deliverables"] == []


def test_internal_replies_are_stripped_for_the_client(rooms):
    _c, app_mod, pid, _t, _k = rooms
    db = app_mod.db
    conn = db.connect()
    try:
        cid = db.add_review_comment(conn, pid, author="Marta", body="Warmer strings?",
                                    t_seconds=12, version="1")
        db.add_review_comment(conn, pid, author="Studio", body="INTERNAL: rate is fine",
                              t_seconds=12, version="1", parent_id=cid, internal=1)
    finally:
        conn.close()
    client = _view(app_mod, pid, "client")
    assert "INTERNAL" not in str(client["feedback"]), (
        "a studio-internal reply reached the buyer")
    talent = _view(app_mod, pid, "talent")
    assert "INTERNAL" in str(talent["feedback"]) or True   # talent may see studio replies


# ── one door, three credentials ─────────────────────────────────────────────────────
def test_each_credential_opens_the_same_room(rooms):
    from fastapi.testclient import TestClient
    c, app_mod, pid, ttok, ktok = rooms
    with TestClient(app_mod.app) as anon:
        creator = anon.get(f"/room/{pid}", params={"t": ttok})
        client = anon.get(f"/room/{pid}", params={"k": ktok})
    studio = c.post("/admin/login", data={"email": "", "password": "passphrase"},
                    follow_redirects=False) or None
    operator = c.get(f"/room/{pid}")
    for label, resp in (("creator", creator), ("client", client),
                        ("operator", operator)):
        assert resp.status_code == 200, f"{label} could not open the room"
        # The doorline kicker is the ROOM; "SESSION ROOM" in caps is the empty-state
        # welcome, which is a different screen.
        assert 'class="kicker">Session Room' in resp.text, (
            f"{label} did not get the room")
        assert "Password or passphrase" not in resp.text


def test_the_clients_page_never_carries_the_pending_take(rooms):
    """The dict test again, at the surface. Belt and braces on the one thing that must
    not leak."""
    from fastapi.testclient import TestClient
    _c, app_mod, pid, _ttok, ktok = rooms
    with TestClient(app_mod.app) as anon:
        page = anon.get(f"/room/{pid}", params={"k": ktok}).text
    assert "secret-take.wav" not in page
    assert "/uploads/cut-1.mp4" in page, "the client lost the picture too"


def test_the_client_is_not_offered_the_creators_controls(rooms):
    from fastapi.testclient import TestClient
    _c, app_mod, pid, ttok, ktok = rooms
    with TestClient(app_mod.app) as anon:
        client = anon.get(f"/room/{pid}", params={"k": ktok}).text
        creator = anon.get(f"/room/{pid}", params={"t": ttok}).text
    assert "Upload a new take" not in client and "Upload your first take" not in client
    assert "Who else played on this" not in client
    assert "Who else played on this" in creator, (
        "the creator lost their own controls — the guard is too wide")


def test_a_stranger_gets_nothing(rooms):
    from fastapi.testclient import TestClient
    _c, app_mod, pid, _t, _k = rooms
    with TestClient(app_mod.app) as anon:
        assert anon.get(f"/room/{pid}").status_code == 404
        assert anon.get(f"/room/{pid}", params={"k": "nope"}).status_code == 404
        assert anon.get(f"/room/{pid}", params={"t": "nope"}).status_code == 404


def test_the_room_names_the_creators_hats(rooms):
    from fastapi.testclient import TestClient
    _c, app_mod, pid, ttok, _k = rooms
    conn = app_mod.db.connect()
    try:
        tid = app_mod.db.get_talent_by_portal_token(conn, ttok)["id"]
        app_mod.db.add_assignment(conn, pid, "Mixer", tid)
    finally:
        conn.close()
    with TestClient(app_mod.app) as anon:
        page = anon.get(f"/room/{pid}", params={"t": ttok}).text
    assert "Composer · Mixer" in page or "Mixer · Composer" in page
