"""Four times: *"im in the client room and there is no new deliverables, i pushed it from
the studio side. the client should be seeing it and i dont"* (operator, 2026-08-21).

Every reproduction of that flow on a clean instance put the file in front of the client —
publishing into an empty lane, into a lane already fully approved, under a mismatched lane
label, and into a project already Delivered. All four reached them.

Which is the whole point of this file. When four reproductions disagree with the person
looking at the screen, **the answer is in that project's data and the fifth guess is worth
less than one measurement**. Nothing anywhere compared what is STORED against what the
client's room actually renders, so "I pushed it" and "I can't see it" could both be true
with no way to find the gap.

The comparison is deliberately dumb: take the filenames the client's own sign-off list
would render, subtract them from the filenames in ``assets``, and name what is left. It
assumes nothing about WHY lane matching missed, so it keeps working when the matching
rules change — and it cannot be argued with.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "v.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "outbox", "signals", "room", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db, production
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    from chordential_oia.web.uploads import _persist_upload
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        _persist_upload(conn, "m1.mp3", b"ID3x", "audio/mpeg")
        db.update_delivery(conn, pid, "versions", [{
            "n": 1, "label": "v1", "url": "/uploads/m1.mp3", "filename": "m1.mp3",
            "at": "x", "by": "Ada"}])
        production.set_creative_lock(conn, db, pid, version_n=1, by="Marta")
    finally:
        conn.close()
    return c, app_mod, db, pid


LANE = "Mix-ready stem package"


def _store(db, pid, *, published=(), waiting=(), ghosts=()):
    from chordential_oia.web.uploads import _persist_upload
    conn = db.connect()
    try:
        assets, pend = [], []
        for i, orig in enumerate(published):
            fn = f"p{i}.wav"
            _persist_upload(conn, fn, b"RIFFx", "audio/wav")
            assets.append({"label": LANE, "url": f"/uploads/{fn}", "filename": fn,
                           "orig": orig, "kind": "audio"})
        for i, orig in enumerate(ghosts):          # a row with no bytes behind it
            assets.append({"label": LANE, "url": f"/uploads/g{i}.wav",
                           "filename": f"g{i}.wav", "orig": orig, "kind": "audio"})
        for i, orig in enumerate(waiting):
            fn = f"w{i}.wav"
            _persist_upload(conn, fn, b"RIFFx", "audio/wav")
            pend.append({"label": LANE, "url": f"/uploads/{fn}", "filename": fn,
                         "orig": orig, "kind": "audio", "by": "Ada", "at": "x"})
        db.update_delivery(conn, pid, "assets", assets)
        db.update_delivery(conn, pid, "pending_assets", pend)
    finally:
        conn.close()


def _look(db, pid):
    from chordential_oia.web.delivery_ops import client_visibility
    conn = db.connect()
    try:
        return client_visibility(db.get_project(conn, pid), db.get_delivery(conn, pid))
    finally:
        conn.close()


# ── the measurement ─────────────────────────────────────────────────────────────────
def test_a_published_file_the_client_sees_is_reported_as_seen(project):
    _c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav", "Keys.wav"])
    v = _look(db, pid)
    assert {r["name"] for r in v["published"]} == {"Bass.wav", "Keys.wav"}
    assert v["hidden"] == [] and v["ok"] is True


def test_a_file_still_at_the_taste_gate_is_named_as_such(project):
    """The commonest innocent answer to "why can't they see it": it was uploaded but
    never published. That is correct behaviour and was invisible."""
    _c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav"], waiting=["NewGuitar.wav"])
    v = _look(db, pid)
    assert [r["name"] for r in v["waiting"]] == ["NewGuitar.wav"]
    assert "NewGuitar.wav" not in {r["name"] for r in v["published"]}


def test_a_row_with_no_bytes_behind_it_is_reported_lost(project):
    """The ephemeral-disk shape: the lane still lists it, the client's player renders a
    dead control, and publishing it refuses. It looked identical to a healthy file."""
    _c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav"], ghosts=["Ghost.wav"])
    v = _look(db, pid)
    assert [r["name"] for r in v["lost"]] == ["Ghost.wav"]


def test_a_published_file_that_reaches_nobody_is_named_with_its_lane(project):
    """The reported bug's shape, whatever causes it: stored, published, and on no lane
    the client's room renders. Pushing it again cannot help, so the panel says so and
    names the label that decided it."""
    from chordential_oia.web.delivery_ops import client_visibility
    _c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav"])
    conn = db.connect()
    try:
        row, delivery = db.get_project(conn, pid), db.get_delivery(conn, pid)
        # Force the mismatch the measurement exists to catch, without asserting WHICH
        # matching rule produced it.
        import chordential_oia.web.delivery_ops as ops
        real = ops.scoped_signoff
        ops.scoped_signoff = lambda r, d: ([{"asset": "Mix-ready stem package",
                                             "files": []}], {}, [])
        try:
            v = client_visibility(row, delivery)
        finally:
            ops.scoped_signoff = real
    finally:
        conn.close()
    assert [r["name"] for r in v["hidden"]] == ["Bass.wav"]
    assert v["hidden"][0]["label"] == LANE
    assert v["ok"] is False


# ── and it is on the screen where the question gets asked ───────────────────────────
def test_the_console_says_what_the_client_can_see(project):
    c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav"], waiting=["NewGuitar.wav"], ghosts=["Ghost.wav"])
    page = c.get(f"/project/{pid}/delivery").text
    assert "What the client can see" in page
    assert "still at your taste gate" in page
    assert "NewGuitar.wav" in page and "waiting on you" in page
    assert "no bytes on the server" in page and "Ghost.wav" in page


def test_a_healthy_delivery_says_so_plainly(project):
    c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav", "Keys.wav"])
    page = c.get(f"/project/{pid}/delivery").text
    assert "Everything stored is in front of them." in page


def test_the_diagnostic_never_breaks_the_page(project):
    """A read-only panel on the busiest operator screen. If it can 500 the console it is
    worse than the bug it explains."""
    from chordential_oia.web import delivery_ops
    c, _app, db, pid = project
    _store(db, pid, published=["Bass.wav"])
    real = delivery_ops._conn_for_presence
    delivery_ops._conn_for_presence = lambda: None      # DB unavailable mid-render
    try:
        v = _look(db, pid)
        assert v["published"], "the diagnostic gave up entirely rather than degrading"
    finally:
        delivery_ops._conn_for_presence = real
