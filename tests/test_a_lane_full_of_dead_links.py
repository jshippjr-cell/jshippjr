"""A lane listing files that are not there, and no way to take one off.

Reported live (operator, 2026-08-20), twice in the same sitting:

*"i logged in as the composer to try to upload the stems again and i noticed it is still
listing the individual track but they are links to an empty container, which i understand,
but i need a way to delete these useless links if they dont have a function anymore"*

*"as the studio, reviewing the new link of the same stems that just got uploaded, its
giving me this error"* — **"That didn't go through. Check your connection and try
again."**

Both come out of the same place. Production's disk is rebuilt on every deploy, so a lane
accumulates rows whose bytes are gone, and:

1. **The room rendered them as ordinary downloads.** A name that looks like a file and
   opens an empty container is the honesty rule broken, not a cosmetic miss.
2. **Nothing could remove one.** The per-file gate only ever existed on files still
   WAITING; a published row had no control at all.
3. **A press the server could not honour answered with a REDIRECT.** The room vets files
   over ``fetch``, which follows the redirect, gets HTML where it expected JSON, and
   reports a network failure — sending the operator after a connection problem that was
   never there. That is the toast in the screenshot.

The rule this file holds: **the server answers a per-file press, truthfully, in a shape
the caller can read** — and a file that is gone says so instead of pretending to be a
download.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "l.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    from chordential_oia.web.uploads import _persist_upload
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("letmein"))
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])
    _persist_upload(conn, "alive.wav", b"RIFFsound", "audio/wav")
    # The lane view only exists once the master is approved — deliverables are what comes
    # AFTER the creative lock, which is exactly the state the report came from.
    from chordential_oia.web import production
    db.update_delivery(conn, pid, "versions", [
        {"n": 1, "label": "v1", "url": "/uploads/alive.wav", "filename": "alive.wav"}])
    production.set_creative_lock(conn, db, pid, version_n=1, by="Jon Shipp")
    db.update_delivery(conn, pid, "assets", [
        {"label": "Mix-ready stem package", "url": "/uploads/alive.wav",
         "filename": "alive.wav", "orig": "SAND_CASTLE_1_Kick.wav", "kind": "stems"},
        {"label": "Mix-ready stem package", "url": "/uploads/dead.wav",
         "filename": "dead.wav", "orig": "SAND_CASTLE_2_Snare.wav", "kind": "stems"},
    ])
    conn.close()
    return c, db, pid


def _fetch(c, url, **data):
    return c.post(url, data=data, headers={"X-Requested-With": "fetch"},
                  follow_redirects=False)


# ── is there anything behind the link? ──────────────────────────────────────────────
def test_a_present_file_and_a_gone_one_are_told_apart(lane):
    from chordential_oia.web.uploads import media_present
    _c, db, _pid = lane
    conn = db.connect()
    try:
        assert media_present(conn, "alive.wav")
        assert not media_present(conn, "dead.wav")
        assert not media_present(conn, "")
    finally:
        conn.close()


def test_the_mirror_counts_as_present(lane):
    """`serve_upload` answers from the durable DB mirror when the disk copy is gone —
    that is what keeps a published take playable across a redeploy. Asking only the
    object store reports a file as lost while it is still serving."""
    from chordential_oia.web.uploads import media_present, upload_dir
    import os
    _c, db, _pid = lane
    conn = db.connect()
    try:
        # `_persist_upload` already mirrored this one (the mirror is the net under a
        # store that is not durable), so losing the disk copy loses nothing.
        os.remove(os.path.join(upload_dir(), "alive.wav"))    # deploy wiped the disk
        assert media_present(conn, "alive.wav"), (
            "the mirror still holds it and it still serves — calling it lost is wrong")
        # …and once the mirror goes too, it really is gone. That is the state a lane
        # full of dead links is in: neither copy left.
        db.delete_media_blob(conn, "alive.wav")
        assert not media_present(conn, "alive.wav")
    finally:
        conn.close()


def test_the_room_marks_the_dead_row_instead_of_linking_it(lane):
    c, _db, pid = lane
    page = c.get(f"/room/{pid}").text
    assert "file is no longer on the server" in page
    assert "SAND_CASTLE_2_Snare.wav" in page
    assert 'href="/uploads/dead.wav"' not in page, (
        "a name that opens an empty container is still rendered as a download")
    assert 'href="/uploads/alive.wav"' in page, "the live file lost its link too"


# ── and the studio can take it off ──────────────────────────────────────────────────
def test_the_studio_can_remove_a_file_from_a_lane(lane):
    c, db, pid = lane
    r = _fetch(c, f"/project/{pid}/delivery/asset/remove",
               filename="dead.wav", origin="room")
    assert r.status_code == 200 and r.json()["ok"] is True
    conn = db.connect()
    try:
        left = [a["filename"] for a in db.get_delivery(conn, pid)["assets"]]
    finally:
        conn.close()
    assert left == ["alive.wav"]


def test_the_removal_says_why_in_the_project_log(lane):
    """A file leaving a delivery is a fact about the delivery. "Where did the snare go"
    is a question someone asks three weeks later."""
    c, db, pid = lane
    _fetch(c, f"/project/{pid}/delivery/asset/remove", filename="dead.wav", origin="room")
    conn = db.connect()
    try:
        said = " ".join(u["body"] for u in db.list_updates(conn, pid))
    finally:
        conn.close()
    assert "SAND_CASTLE_2_Snare.wav" in said
    assert "no longer on the server" in said


def test_removing_takes_the_approval_with_it(lane):
    """The sign-off rollup opens the paywall. An approval left pointing at a file that
    no longer exists is the rollup counting an approval of nothing."""
    c, db, pid = lane
    conn = db.connect()
    try:
        db.set_asset_approval(conn, pid, "dead.wav", status="Approved", by="Marta")
        assert "dead.wav" in db.get_delivery(conn, pid)["asset_approvals"]
    finally:
        conn.close()
    _fetch(c, f"/project/{pid}/delivery/asset/remove", filename="dead.wav", origin="room")
    conn = db.connect()
    try:
        assert "dead.wav" not in (db.get_delivery(conn, pid).get("asset_approvals") or {})
    finally:
        conn.close()


def test_removing_a_live_file_forgets_both_copies(lane):
    """The disk AND the mirror. Deleting one and leaving the other is how a removed file
    keeps downloading for reasons nobody remembers."""
    from chordential_oia.web.uploads import media_present
    c, db, pid = lane
    conn = db.connect()
    try:
        db.save_media_blob(conn, "alive.wav", b"RIFFsound", "audio/wav")
    finally:
        conn.close()
    _fetch(c, f"/project/{pid}/delivery/asset/remove", filename="alive.wav", origin="room")
    conn = db.connect()
    try:
        assert not media_present(conn, "alive.wav")
    finally:
        conn.close()


def test_a_waiting_file_can_be_removed_too(lane):
    c, db, pid = lane
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "pending_assets", [
            {"label": "Mix-ready stem package", "url": "/uploads/pend.wav",
             "filename": "pend.wav", "orig": "SAND_CASTLE_3_Bass.wav", "kind": "stems"}])
    finally:
        conn.close()
    r = _fetch(c, f"/project/{pid}/delivery/asset/remove",
               filename="pend.wav", origin="room")
    assert r.json()["ok"] is True
    conn = db.connect()
    try:
        assert db.get_delivery(conn, pid)["pending_assets"] == []
    finally:
        conn.close()


def test_a_gone_waiting_file_is_not_publishable(lane):
    """Approving it would put a dead link in front of the client. The only honest press
    left is to clear the row."""
    c, db, pid = lane
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "pending_assets", [
            {"label": "Mix-ready stem package", "url": "/uploads/pend.wav",
             "filename": "pend.wav", "orig": "SAND_CASTLE_3_Bass.wav", "kind": "stems"}])
    finally:
        conn.close()
    page = c.get(f"/room/{pid}").text
    assert "/delivery/asset/publish" not in page.split("SAND_CASTLE_3_Bass.wav")[1][:600]
    assert "/delivery/asset/remove" in page


def test_a_client_is_never_offered_the_control(lane):
    """ADR-0068 — the room subtracts. Removing a deliverable is the studio's decision."""
    c, db, pid = lane
    conn = db.connect()
    try:
        share = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as anon:
        page = anon.get(f"/room/{pid}", params={"k": share}).text
    assert "/delivery/asset/remove" not in page


# ── and a press it cannot honour says so ────────────────────────────────────────────
def test_a_press_on_a_file_that_moved_on_answers_json_not_a_redirect(lane):
    """THE toast in the screenshot. The room vets over `fetch`; a 303 is followed to an
    HTML page, the JSON parse throws, and the page blames the connection — so the
    operator went looking for a network problem that did not exist."""
    c, _db, pid = lane
    r = _fetch(c, f"/project/{pid}/delivery/asset/publish",
               filename="not-waiting.wav", origin="room", action="publish")
    assert r.status_code == 409, "still a redirect — fetch reads that as a dead connection"
    assert r.headers["content-type"].startswith("application/json")
    # The press also reports what the CLIENT ends up seeing (ADR-0088). On a refusal
    # there is nothing to report, so the subset that carries the meaning is asserted
    # rather than the whole envelope — a diagnostic field must not break a contract test.
    body = r.json()
    assert {k: body[k] for k in ("ok", "action", "filename", "reason")} == {
        "ok": False, "action": "publish",
        "filename": "not-waiting.wav", "reason": "gone"}


def test_removing_the_same_row_twice_says_gone_rather_than_failing(lane):
    c, _db, pid = lane
    _fetch(c, f"/project/{pid}/delivery/asset/remove", filename="dead.wav", origin="room")
    again = _fetch(c, f"/project/{pid}/delivery/asset/remove",
                   filename="dead.wav", origin="room")
    assert again.status_code == 409 and again.json()["reason"] == "gone"


def test_a_successful_press_still_answers_json(lane):
    c, db, pid = lane
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "pending_assets", [
            {"label": "Mix-ready stem package", "url": "/uploads/alive.wav",
             "filename": "alive.wav", "orig": "SAND_CASTLE_1_Kick.wav", "kind": "stems"}])
    finally:
        conn.close()
    r = _fetch(c, f"/project/{pid}/delivery/asset/publish",
               filename="alive.wav", origin="room", action="publish")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_without_javascript_it_still_redirects(lane):
    """No `X-Requested-With` means a plain form post — which must still land the
    operator back where they pressed."""
    c, _db, pid = lane
    r = c.post(f"/project/{pid}/delivery/asset/remove",
               data={"filename": "dead.wav", "origin": "room"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/room/{pid}")


# ── the console's "missing" list learns the same thing ──────────────────────────────
def test_the_restore_console_no_longer_names_a_mirrored_file(lane):
    """`_missing_asset_files` asked only the object store, so a file that survives a
    redeploy in the DB mirror — and downloads perfectly — was listed as lost and offered
    for re-upload."""
    import os
    from chordential_oia.web.project_routes import _missing_asset_files
    from chordential_oia.web.uploads import upload_dir
    _c, db, pid = lane
    conn = db.connect()
    try:
        db.save_media_blob(conn, "alive.wav", b"RIFFsound", "audio/wav")
        os.remove(os.path.join(upload_dir(), "alive.wav"))
        missing = _missing_asset_files(conn, db.get_delivery(conn, pid))
    finally:
        conn.close()
    names = [a["filename"] for a in missing]
    assert names == ["dead.wav"], f"the mirrored file was called lost too: {names}"


def test_sending_a_deliverable_back_forgets_the_mirror_too(lane):
    """Send-back unlinked the path under `upload_dir()` and left the mirror, and
    `serve_upload` answers from the mirror — so a rejected deliverable kept downloading."""
    from chordential_oia.web.uploads import media_present
    c, db, pid = lane
    conn = db.connect()
    try:
        db.save_media_blob(conn, "alive.wav", b"RIFFsound", "audio/wav")
        db.update_delivery(conn, pid, "pending_assets", [
            {"label": "Mix-ready stem package", "url": "/uploads/alive.wav",
             "filename": "alive.wav", "orig": "SAND_CASTLE_1_Kick.wav", "kind": "stems"}])
    finally:
        conn.close()
    _fetch(c, f"/project/{pid}/delivery/asset/publish",
           filename="alive.wav", origin="room", action="discard")
    conn = db.connect()
    try:
        assert not media_present(conn, "alive.wav"), "the sent-back file still downloads"
    finally:
        conn.close()
