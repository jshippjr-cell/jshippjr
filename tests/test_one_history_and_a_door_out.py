"""Two lists of one history, and a refusal that named a door nobody could find.

Reported live (operator, 2026-08-21), with both surfaces screenshotted side by side:
*"campaign time line and activity feed is redundant remove the campaign time line, create
an accordion view of the version and review activiy"*

They were the same events twice, differing only in that the timeline also named the
version uploads. Two renderings of one history is how they drift — the same rule that put
the queue count in one place and the price in another (ADR-0029, ADR-0033) — and the
console had already grown long enough that neither list could be read to the bottom.

And, on the same screen: *"what does it mean to reopen, i dont know how to do that and
this is a demo project if i want to delete it, let me delete it"*. The delete refusal for
a Delivered project advised reopening it first. **There is no reopen.** Advice naming an
action the product does not have is worse than no advice — it reads as though the door
exists and you are too stupid to find it. The refusals are a speed bump, not a wall: each
protects a record that matters on a real deal and each is wrong about a rehearsal.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "outbox", "signals", "room", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        db.update_delivery(conn, pid, "versions", [
            {"n": 1, "label": "v1 Concept", "url": "/uploads/a.mp3",
             "filename": "a.mp3", "at": "2026-08-18T22:44", "by": "Ada"},
            {"n": 2, "label": "v2 FINAL", "url": "/uploads/b.mp3",
             "filename": "b.mp3", "at": "2026-08-19T19:27", "by": "Ada"}])
        db.add_review_comment(conn, pid, author="Studio", body="Hello",
                              t_seconds=12, version="1")
        db.add_review_comment(conn, pid, author="Studio", body="jargon",
                              t_seconds=20, version="1")
        db.add_review_comment(conn, pid, author="Client", body="I love the piano intro",
                              t_seconds=7, version="2")
    finally:
        conn.close()
    return c, app_mod, db, pid


# ── one history ─────────────────────────────────────────────────────────────────────
def test_the_second_copy_of_the_history_is_gone(console):
    c, _app, _db, pid = console
    page = c.get(f"/project/{pid}/delivery").text
    assert "<h2>Campaign timeline</h2>" not in page


def test_the_history_folds_by_version(console):
    c, _app, _db, pid = console
    page = c.get(f"/project/{pid}/delivery").text
    assert "Version &amp; review activity" in page
    assert page.count("<details class=\"vfold\"") >= 2, "not one fold per take"


def test_the_current_take_is_open_and_the_earlier_one_is_not(console):
    """An accordion whose every panel is shut is a worse page, not a shorter one."""
    c, _app, _db, pid = console
    page = c.get(f"/project/{pid}/delivery").text
    assert '<details class="vfold" open>' in page
    assert '<details class="vfold">' in page


def test_a_shut_fold_still_says_what_is_in_it(console):
    """The reason people stop opening collapsed sections is that a shut one tells them
    nothing about whether it is worth opening."""
    c, _app, _db, pid = console
    page = c.get(f"/project/{pid}/delivery").text
    assert "2 notes" in page and "1 note" in page


def test_nothing_was_lost_in_the_fold(console):
    c, _app, _db, pid = console
    page = c.get(f"/project/{pid}/delivery").text
    for body in ("Hello", "jargon", "I love the piano intro"):
        assert body in page, f"{body!r} disappeared with the timeline"
    assert "v1 Concept" in page and "v2 FINAL" in page
    assert "2026-08-19 19:27" in page, "the fold lost the upload time the timeline gave"


def test_a_note_from_before_the_takes_were_numbered_still_shows(console):
    """A note nobody can find is a note nobody answers."""
    c, _app, db, pid = console
    conn = db.connect()
    try:
        db.add_review_comment(conn, pid, author="Client", body="an older thought",
                              t_seconds=3, version="")
    finally:
        conn.close()
    page = c.get(f"/project/{pid}/delivery").text
    assert "Before the takes were numbered" in page
    assert "an older thought" in page


# ── and a door that exists ──────────────────────────────────────────────────────────
def test_the_refusal_no_longer_names_an_action_that_does_not_exist(console):
    c, _app, _db, _pid = console
    page = c.get("/projects?kept=delivered&id=1&name=Winter").text
    assert "reopen it first" not in page, (
        "still telling the operator to do something the product cannot do")


def test_the_refusal_offers_a_real_way_through(console):
    c, _app, _db, _pid = console
    page = c.get("/projects?kept=delivered&id=1&name=Winter").text
    assert "Delete it anyway" in page
    assert "a delivery a client has in hand" in page, (
        "the override does not say what it destroys")


def test_the_override_actually_deletes(console):
    from chordential_oia.talent import Talent
    from chordential_oia.models import MusicDiscipline
    c, _app, db, _pid = console
    conn = db.connect()
    try:
        pid = db.insert_project(conn, None, "Larkspur", "Rehearsal Film",
                                1000, 2000, ["Composer"])
        db.update_delivery(conn, pid, "state", "Delivered")
    finally:
        conn.close()
    assert c.post(f"/project/{pid}/delete",
                  follow_redirects=False).headers["location"].startswith(
                      "/projects?kept=delivered")
    r = c.post(f"/project/{pid}/delete", data={"force": "1"}, follow_redirects=False)
    assert "deleted=" in r.headers["location"]
    conn = db.connect()
    try:
        assert db.get_project(conn, pid) is None
    finally:
        conn.close()


def test_the_speed_bump_is_still_there(console):
    """Overridable is not the same as absent — an unforced press must still refuse, or
    the protection was removed rather than made reachable."""
    c, _app, db, _pid = console
    conn = db.connect()
    try:
        pid = db.insert_project(conn, None, "Larkspur", "Real Film", 1000, 2000, ["Composer"])
        db.update_delivery(conn, pid, "state", "Delivered")
    finally:
        conn.close()
    c.post(f"/project/{pid}/delete", follow_redirects=False)
    conn = db.connect()
    try:
        assert db.get_project(conn, pid) is not None
    finally:
        conn.close()


def test_every_refusal_has_an_override_sentence():
    """A reason to refuse with no matching statement of what forcing it destroys would
    put an unexplained button in front of an irreversible act."""
    from chordential_oia.web import db as dbm
    assert set(dbm.PROJECT_DELETE_OVERRIDE) == set(dbm.PROJECT_DELETE_BLOCK)
