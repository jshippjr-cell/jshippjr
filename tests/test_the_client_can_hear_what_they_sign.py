"""The buyer could not hear a single thing.

Reported live (operator, 2026-08-21): *"I pushed the approved newly uploaded stems from
the studio to the client, and i dont see the clients ability to download or listen to the
new uploads that were pushed."*

It was worse than the stems. **Every media URL in the client's room pointed at
``/uploads/{name}``, which is behind the ADMIN gate**, so a buyer's ``<audio>`` element
fetched a 303 to the login page and rendered silence — the master they were reviewing as
well as the deliverables they were being asked to sign off. The timed notes still worked,
which is what hid it: you can leave a note at 0:12 on a player that never played.

The second half was the paywall. The token-scoped door, ``/project/{id}/dl/{name}``,
answered a client token with **402 Payment Required** for everything until the balance was
settled — while its own message read *"You can still stream and review the work."* You
could not. Asking someone to approve a file they are forbidden to hear is not a paywall,
it is a broken review.

So: a client's room routes every media URL through their own door, and that door streams
media inline whether or not the balance is settled. The package and every real download
stay gated — that is what the balance buys.
"""
import importlib
import re

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def deal(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "h.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "outbox", "signals", "room", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.uploads import _persist_upload
    with TestClient(app_mod.app):
        pass
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        _persist_upload(conn, "master-v1.mp3", b"ID3fakeaudio", "audio/mpeg")
        _persist_upload(conn, "tv-1.wav", b"RIFFfakeaudio", "audio/wav")
        db.update_delivery(conn, pid, "versions", [{
            "n": 1, "label": "v1 Concept", "url": "/uploads/master-v1.mp3",
            "filename": "master-v1.mp3", "at": "2026-08-19", "by": "Ada"}])
        db.update_delivery(conn, pid, "assets", [{
            "label": "Instrumental / TV mix", "url": "/uploads/tv-1.wav",
            "filename": "tv-1.wav", "orig": "TVmix.wav", "kind": "audio"}])
        db.update_delivery(conn, pid, "delivery_zip",
                           {"filename": "pkg.zip", "url": "/uploads/pkg.zip"})
        k = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    return TestClient(app_mod.app), app_mod, db, pid, k


# ── the client's room hands them a door they hold ───────────────────────────────────
def test_the_client_is_never_given_the_admin_gated_path(deal):
    anon, _app, _db, pid, k = deal
    page = anon.get(f"/room/{pid}", params={"k": k}).text
    assert "/uploads/" not in page, (
        "the buyer's player is still pointed at a URL that answers with a login page")


def test_the_client_can_actually_play_the_master(deal):
    """The one that mattered: they were reviewing a take they could not hear."""
    anon, _app, _db, pid, k = deal
    page = anon.get(f"/room/{pid}", params={"k": k}).text
    urls = {u.replace("&amp;", "&") for u in
            re.findall(r'"(/project/\d+/dl/[^"]+)"', page)}
    master = [u for u in urls if "master-v1" in u]
    assert master, "the master is not reachable by the client at all"
    r = anon.get(master[0], follow_redirects=False)
    assert r.status_code == 200, f"the client still cannot hear the master ({r.status_code})"
    assert r.content == b"ID3fakeaudio"


def test_the_studio_and_the_creator_keep_the_direct_path(deal):
    """The rewrite is for the credential that needs it. A creator's `?t=` is not a
    project token the download route accepts, and the studio holds none at all — routing
    either through `/dl/` would break what already works."""
    from chordential_oia.web import room
    from chordential_oia.web.creator_routes import _room_for_project
    _anon, app_mod, db, pid, _k = deal
    conn = db.connect()
    try:
        view = room.room_view(conn, db, pid, "operator", build=_room_for_project)
    finally:
        conn.close()
    assert "/uploads/master-v1.mp3" in str(view)


# ── the rewrite cannot leak, and cannot forget ──────────────────────────────────────
def test_routing_happens_after_the_subtraction(deal):
    """A pending take is removed from the client's room. If media were routed BEFORE the
    subtraction, the rewrite would mint a working client URL for the take first and the
    subtraction would then have to catch it — this asserts the order that cannot leak."""
    _anon, _app, db, pid, k = deal
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "pending_version", {
            "url": "/uploads/secret-take.wav", "label": "v2", "by": "Ada"})
    finally:
        conn.close()
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as anon:
        page = anon.get(f"/room/{pid}", params={"k": k}).text
    assert "secret-take" not in page


def test_the_walk_rewrites_any_media_url_anywhere(deal):
    """Done as a blanket walk rather than field by field, so a new surface cannot forget
    it — the same argument as wrapping the branded shell inside `send_email`."""
    from chordential_oia.web import room
    nested = {"a": {"url": "/uploads/x.wav"},
              "b": [{"files": [{"url": "/uploads/y.wav"}]}],
              "keep": {"dl_url": "/uploads/z.zip"},
              "external": {"url": "https://example.com/a.wav"}}
    out = room.route_media(nested, 7, "TOK", "k")
    assert out["a"]["url"] == "/project/7/dl/x.wav?k=TOK&stream=1"
    assert out["b"][0]["files"][0]["url"] == "/project/7/dl/y.wav?k=TOK&stream=1"
    assert out["keep"]["dl_url"] == "/uploads/z.zip", (
        "the real download was rewritten into a streaming URL — that is the paywall")
    assert out["external"]["url"] == "https://example.com/a.wav"


# ── streaming is not the paywall's business; the package is ─────────────────────────
def test_a_deliverable_streams_before_the_balance_is_settled(deal):
    """You cannot ask someone to approve a stem they are not allowed to hear."""
    anon, _app, _db, pid, k = deal
    r = anon.get(f"/project/{pid}/dl/tv-1.wav", params={"k": k, "stream": "1"},
                 follow_redirects=False)
    assert r.status_code == 200, "the stems are still paywalled for the person signing them off"
    assert r.content == b"RIFFfakeaudio"


def test_it_is_served_inline_so_the_player_can_seek(deal):
    anon, _app, _db, pid, k = deal
    r = anon.get(f"/project/{pid}/dl/tv-1.wav", params={"k": k, "stream": "1"})
    assert "attachment" not in (r.headers.get("content-disposition") or "")
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_the_package_is_never_streamable(deal):
    """A ZIP is the deliverable the balance buys. `stream=1` must not be a way around
    that, however it is asked for."""
    anon, _app, _db, pid, k = deal
    r = anon.get(f"/project/{pid}/dl/pkg.zip", params={"k": k, "stream": "1"},
                 follow_redirects=False)
    assert r.status_code == 402


def test_a_plain_download_is_still_gated(deal):
    """Without `stream`, nothing changes: the individual file download waits for payment
    exactly as it did."""
    anon, _app, _db, pid, k = deal
    assert anon.get(f"/project/{pid}/dl/tv-1.wav", params={"k": k}).status_code == 402


def test_a_stranger_gets_nothing_streamable_either(deal):
    """The stream mode relaxes the PAYWALL, never the credential."""
    anon, _app, _db, pid, _k = deal
    assert anon.get(f"/project/{pid}/dl/tv-1.wav",
                    params={"k": "nope", "stream": "1"}).status_code == 404


def test_paying_still_opens_the_real_download(deal):
    anon, _app, db, pid, k = deal
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "download_unlocked", True)
    finally:
        conn.close()
    r = anon.get(f"/project/{pid}/dl/tv-1.wav", params={"k": k})
    assert r.status_code == 200
    assert "attachment" in (r.headers.get("content-disposition") or "")
