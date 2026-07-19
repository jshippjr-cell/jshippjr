"""Phase 4 — range (span) notes: a client note can cover a stretch of the picture
(t_seconds…t_end), stored on review_comments.t_end and rendered as a span on the
composer's spine. A malformed/backwards range degrades to a single-point pin."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, app_mod


def _setup(db_mod):
    from chordential_oia.talent import InviteStatus, ReviewStatus, Talent
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Devin", email="d@x.com", credits="c",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED, rate=90.0))
    db_mod.set_talent_agreement(conn, tid, "2026-07-18", "t")
    pid = db_mod.insert_project(conn, opp_id=None, client="A", need="spot",
                                budget_min=1, budget_max=2, deadline="2026-08-01",
                                roles=["Composer"])
    db_mod.add_assignment(conn, pid, "Composer", tid)
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    share = db_mod.ensure_project_share_token(conn, pid)
    conn.close()
    return pid, tok, share


def test_range_note_stored_and_rendered(ctx):
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    r = client.post(f"/project/{pid}/review/comment",
                    data={"k": share, "author": "Dana", "email": "dana@x.com",
                          "t": "3", "t_end": "7", "body": "soften this stretch"},
                    follow_redirects=False)
    assert r.status_code in (200, 303)
    conn = db_mod.connect()
    row = conn.execute("SELECT t_seconds, t_end FROM review_comments "
                       "WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    conn.close()
    assert row["t_seconds"] == 3.0 and row["t_end"] == 7.0
    page = client.get(f"/creator/{tok}").text
    assert "note-span" in page and '"t_end": 7' in page


def test_backwards_range_degrades_to_point(ctx):
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    client.post(f"/project/{pid}/review/comment",
                data={"k": share, "author": "Dana", "email": "dana@x.com",
                      "t": "10", "t_end": "4", "body": "backwards"},
                follow_redirects=False)
    conn = db_mod.connect()
    row = conn.execute("SELECT t_seconds, t_end FROM review_comments "
                       "WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    conn.close()
    assert row["t_seconds"] == 10.0 and row["t_end"] is None   # a point, not a span


def test_no_t_end_is_a_plain_point_note(ctx):
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    client.post(f"/project/{pid}/review/comment",
                data={"k": share, "author": "Dana", "email": "dana@x.com",
                      "t": "5", "body": "at this frame"}, follow_redirects=False)
    conn = db_mod.connect()
    row = conn.execute("SELECT t_end FROM review_comments "
                       "WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    conn.close()
    assert row["t_end"] is None


def test_capture_shelf_is_private_to_composer(ctx):
    """Phase 4 §13: a captured idea shows in the composer room + persists, but is
    NEVER rendered on the client portal (the private-shelf promise)."""
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    secret = "SECRETMOTIF_rising_fifth"
    r = client.post(f"/creator/{tok}/project/{pid}/capture",
                    data={"text": secret},
                    headers={"X-Requested-With": "fetch"}, follow_redirects=False)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert secret in client.get(f"/creator/{tok}").text
    assert secret not in client.get(f"/project/{pid}/delivery-portal?k={share}").text
    # persisted on the shelf
    conn = db_mod.connect()
    caps = db_mod.get_captures(conn, pid)
    conn.close()
    assert len(caps) == 1 and caps[0]["text"] == secret


def test_empty_capture_is_ignored(ctx):
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    client.post(f"/creator/{tok}/project/{pid}/capture", data={"text": "   "},
                headers={"X-Requested-With": "fetch"}, follow_redirects=False)
    conn = db_mod.connect()
    assert db_mod.get_captures(conn, pid) == []
    conn.close()


def test_reply_to_bad_comment_id_is_not_faked(ctx):
    """A reply to a stale/cross-project/guessed comment_id must NOT fabricate
    success or fire an operator ping (eng P0)."""
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    r = client.post(f"/creator/{tok}/project/{pid}/note/999999/reply",
                    data={"body": "hi"}, headers={"X-Requested-With": "fetch"},
                    follow_redirects=False)
    assert r.status_code == 200 and r.json()["ok"] is False
    conn = db_mod.connect()
    n = conn.execute("SELECT COUNT(*) FROM review_comments WHERE parent_id=999999",
                     ).fetchone()[0]
    conn.close()
    assert n == 0


def test_range_note_shown_on_console_and_portal_with_span_cue(ctx):
    """A range note renders as a range on BOTH the console and the client portal,
    and its cue attribution names every cue the span overlaps (EP P0)."""
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    conn = db_mod.connect()
    db_mod.add_cue(conn, pid, name="a", t_in="0", t_out="5")     # m01
    db_mod.add_cue(conn, pid, name="b", t_in="5", t_out="12")    # m02
    conn.close()
    client.post(f"/project/{pid}/review/comment",
                data={"k": share, "author": "Dana", "email": "dana@x.com",
                      "t": "2", "t_end": "8", "body": "whole section"},
                follow_redirects=False)
    console = client.get(f"/project/{pid}/delivery").text
    portal = client.get(f"/project/{pid}/delivery-portal?k={share}").text
    assert "0:02–0:08" in console and "0:02–0:08" in portal
    assert "m01–m02" in console          # span crosses both cues


def test_comment_timecode_capped(ctx):
    client, db_mod, _ = ctx
    pid, tok, share = _setup(db_mod)
    client.post(f"/project/{pid}/review/comment",
                data={"k": share, "author": "Dana", "email": "dana@x.com",
                      "t": "100000000000000", "body": "huge"}, follow_redirects=False)
    conn = db_mod.connect()
    row = conn.execute("SELECT t_seconds FROM review_comments WHERE body='huge'").fetchone()
    conn.close()
    assert row["t_seconds"] is None
