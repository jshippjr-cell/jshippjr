"""Judging a take against nothing but itself, and a logo re-set as text.

Two reports from one screenshot of the delivery console.

**The taste gate was deaf to picture.** A composer's submission arrived in "Versions &
review activity" as a bare ``<audio>`` element. The decision it gates — whether the
client ever hears this take — was being made without the cut the music was written to,
which was one page away in the client portal. *"i only get to hear the audio. i need a
link into the portal so i can review the composer's audio with the video it is
supporting so i can give feedback before i push it to the client."*

**The logo was being re-set.** The composer's Session Room drew the wordmark out of a
serif face and a coloured ``<b>`` — ``Chord<b>ential</b>`` — while every other surface
(client portal, brief, agreements, every email) ships the actual file. A re-set wordmark
is a different mark to anyone who knows the real one.
"""
import importlib
import pathlib
import re

import pytest

pytest.importorskip("fastapi")

TEMPLATES = (pathlib.Path(__file__).resolve().parent.parent
             / "src" / "chordential_oia" / "web" / "templates")


# ── the logo is the logo ────────────────────────────────────────────────────────────
def test_no_template_re_sets_the_wordmark_as_text():
    """`Chord<b>ential</b>` and friends: the lockup rebuilt out of markup. The brand
    name in a sentence is fine; the LOGO drawn with type is not."""
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"Chord</?[a-z]|Chord<b>|>Chord<", text, re.I):
            line = text[:m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(TEMPLATES)}:{line}")
    assert offenders == [], (
        "the wordmark is being re-set in markup instead of using the file: "
        + ", ".join(offenders))


def test_the_session_room_ships_the_real_wordmark():
    room = (TEMPLATES / "creator_portal.html").read_text(encoding="utf-8")
    assert room.count('src="/static/public/wordmark-ko.png"') >= 2, (
        "the composer's doorline lost the wordmark file")
    assert "Chord<b>ential</b>" not in room


def test_every_branded_surface_uses_an_asset_not_a_font():
    """The surfaces a client, composer or contributor actually looks at."""
    for name in ("creator_portal.html", "delivery_portal.html", "workspace.html",
                 "composer_agreement.html", "contributor_release.html",
                 "first_touch.html", "admin_login.html", "base.html"):
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        assert re.search(r"/static/(public/(wordmark-(ko|dark)|mark-icon)|logo)\.png",
                         text), f"{name} shows no logo asset at all"


# ── the taste gate can see ──────────────────────────────────────────────────────────
@pytest.fixture()
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "gate.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"email": "", "password": "passphrase"},
               follow_redirects=False)
        conn = app_mod.db.connect()
        try:
            pid = conn.execute(
                "SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
            tok = app_mod.db.ensure_project_share_token(conn, pid)
        finally:
            conn.close()
        yield c, app_mod, pid, tok


def _pending(app_mod, pid, *, with_picture: bool):
    conn = app_mod.db.connect()
    try:
        app_mod.db.update_delivery(conn, pid, "pending_version", {
            "by": "Ada Verano", "url": "/uploads/take-v1.wav", "label": "v1 Concept",
            "at": "2026-08-18"})
        if with_picture:
            app_mod.db.update_delivery(conn, pid, "picture", {
                "url": "/uploads/cut-1.mp4", "orig": "winter-appeal-v1.mp4",
                "n": 1, "by": "Marta Reyes", "at": "2026-08-18"})
    finally:
        conn.close()


def test_the_pending_take_plays_against_the_clients_cut(console):
    c, app_mod, pid, _tok = console
    _pending(app_mod, pid, with_picture=True)
    page = c.get(f"/project/{pid}/delivery").text
    block = page[page.index('class="pending"'):page.index('id="review"')
                 if 'id="review"' in page else len(page)]
    assert "/uploads/cut-1.mp4" in block, "the cut is not on the gate"
    assert "/uploads/take-v1.wav" in block, "the take is not on the gate"
    assert "<video" in block, "there is nothing to watch it against"
    assert "winter-appeal-v1.mp4" in block, "say which cut is being screened"


def test_the_gate_links_to_the_room(console):
    """"or better yet, in addition to a link to the full size portal" — both. The full
    surface is now THE room (ADR-0068), so that is where the link goes."""
    c, app_mod, pid, _tok = console
    _pending(app_mod, pid, with_picture=True)
    page = c.get(f"/project/{pid}/delivery").text
    assert f"/room/{pid}" in page
    assert "Open the room" in page


def test_with_no_cut_it_says_so_and_still_plays_the_take(console):
    """A client who has not sent their picture yet must not produce a black rectangle."""
    c, app_mod, pid, _tok = console
    _pending(app_mod, pid, with_picture=False)
    page = c.get(f"/project/{pid}/delivery").text
    block = page[page.index('class="pending"'):]
    assert "<video" not in block[:2000]
    assert "/uploads/take-v1.wav" in block
    assert "No cut from the client yet" in block
    assert "Open the room" in block


def test_the_publish_and_discard_decisions_survive(console):
    """The screening room is added BESIDE the decision, never in place of it."""
    c, app_mod, pid, _tok = console
    _pending(app_mod, pid, with_picture=True)
    page = c.get(f"/project/{pid}/delivery").text
    assert "Publish to client" in page and "Discard" in page


def test_the_client_still_cannot_see_a_pending_take(console):
    """The whole reason the gate exists. Putting the picture next to it must not leak
    the take onto the client's page."""
    from fastapi.testclient import TestClient
    c, app_mod, pid, tok = console
    _pending(app_mod, pid, with_picture=True)
    with TestClient(app_mod.app) as buyer:
        portal = buyer.get(f"/project/{pid}/delivery-portal?k={tok}").text
    assert "take-v1.wav" not in portal, "the client can hear an unpublished take"
