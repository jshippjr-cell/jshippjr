"""A package with holes in it, and a promise nothing kept.

Reported live (operator, 2026-08-22), correcting me: *"how can you say that, when this is
a re-test. the 1st test i was able to download, it had the text files but no audio.. we
are re testing to see if the audio gets packaged correctly"*

They were right and I was wrong. I had explained the missing download with the paywall,
without checking that the download had been available on the previous run. It had. What
changed was not payment.

**The packager was never the problem.** With the audio present it bundles every file
(`referenced_count == 0`, asserted below). The first build was made while the ephemeral
disk had eaten the stems, so it shipped documents and listed the audio as "referenced, not
bundled" — and the room correctly withdrew the download rather than offering a ZIP of
paperwork (ADR-0079).

**The hole was the healing.** `_package_is_stale` only asked whether the ZIP was OLDER
than the work. A docs-only package is not old — nothing landed after it — so nothing ever
rebuilt it, while the client's room said *"Chordential has been told, and you'll have it
shortly."* There was nothing behind that sentence.

Now that uploads survive a deploy (ADR-0084), a package with holes counts as stale **the
moment its missing bytes are back** — and only then, because rebuilding while the audio is
still gone changes nothing and would loop.
"""
import importlib
import os
import zipfile

import pytest

pytest.importorskip("fastapi")

BEFORE = "2026-08-01T00:00:00+00:00"      # everything delivered before the build


@pytest.fixture()
def delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "k.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "outbox", "signals", "room", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db, production
    from chordential_oia.web.delivery_ops import scoped_signoff
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    from chordential_oia.web.uploads import _persist_upload
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        _persist_upload(conn, "master.mp3", b"ID3" + b"\x00" * 4000, "audio/mpeg")
        db.update_delivery(conn, pid, "versions", [{
            "n": 1, "label": "v2 FINAL", "url": "/uploads/master.mp3",
            "filename": "master.mp3", "at": BEFORE, "by": "Ada"}])
        production.set_creative_lock(conn, db, pid, version_n=1, by="Marta")
        lanes, _r, _a = scoped_signoff(db.get_project(conn, pid),
                                       db.get_delivery(conn, pid))
        assets = []
        for i, lane in enumerate(lanes):
            if lane.get("from_version"):
                continue
            fn = f"stem{i}.wav"
            _persist_upload(conn, fn, b"RIFF" + b"\x00" * 6000, "audio/wav")
            assets.append({"label": lane["asset"], "url": f"/uploads/{fn}",
                           "filename": fn, "at": BEFORE,
                           "orig": f"SAND_CASTLE_{i}_(Instrumental).wav", "kind": "audio"})
        db.update_delivery(conn, pid, "assets", assets)
        for a in assets:
            db.set_asset_approval(conn, pid, a["filename"], status="Approved",
                                  by="Marta", email="m@x.com", version="1")
    finally:
        conn.close()
    return c, db, pid


# ── the packager itself ─────────────────────────────────────────────────────────────
def test_the_audio_is_bundled_when_the_audio_is_there(delivery):
    """The thing the operator was re-testing. This has always worked; what failed was
    building while the files were gone."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    from chordential_oia.web.uploads import upload_dir
    _c, db, pid = delivery
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, pid)
    finally:
        conn.close()
    assert pkg["referenced_count"] == 0, "the build left files out"
    names = zipfile.ZipFile(os.path.join(upload_dir(), pkg["filename"])).namelist()
    audio = [n for n in names if n.lower().endswith((".wav", ".mp3", ".aif", ".aiff"))]
    assert len(audio) == 5, f"expected 4 stems + the master, got {audio}"
    assert any(n.startswith("Masters/") for n in audio)


# ── and the healing that never fired ────────────────────────────────────────────────
def _hole_it(db, pid, *, referenced):
    conn = db.connect()
    try:
        z = dict(db.get_delivery(conn, pid)["delivery_zip"])
        z["referenced_count"] = referenced
        db.update_delivery(conn, pid, "delivery_zip", z)
        return db.get_delivery(conn, pid)
    finally:
        conn.close()


def test_a_holed_package_is_stale_once_its_bytes_are_back(delivery):
    from chordential_oia.web.delivery_ops import _build_delivery_package, _package_is_stale
    _c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
    finally:
        conn.close()
    d = _hole_it(db, pid, referenced=4)
    conn = db.connect()
    try:
        assert _package_is_stale(d, conn) is True, (
            "a docs-only package is not 'old', so nothing ever rebuilt it")
    finally:
        conn.close()


def test_it_is_not_stale_while_the_audio_is_still_missing(delivery):
    """Rebuilding without the bytes produces the same holed package — saying stale would
    rebuild on every download, for ever, and change nothing."""
    from chordential_oia.web.delivery_ops import _build_delivery_package, _package_is_stale
    from chordential_oia.web.uploads import forget_media
    _c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
        for a in (db.get_delivery(conn, pid).get("assets") or []):
            forget_media(conn, a["filename"])
    finally:
        conn.close()
    d = _hole_it(db, pid, referenced=4)
    conn = db.connect()
    try:
        assert _package_is_stale(d, conn) is False
    finally:
        conn.close()


def test_a_complete_package_is_left_alone(delivery):
    from chordential_oia.web.delivery_ops import _build_delivery_package, _package_is_stale
    _c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
        d = db.get_delivery(conn, pid)
        assert _package_is_stale(d, conn) is False
    finally:
        conn.close()


def test_unlocking_heals_a_holed_package(delivery):
    """The operator's override is the button they reach for when the download is not
    there. It must not hand back the same broken ZIP."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
    finally:
        conn.close()
    _hole_it(db, pid, referenced=4)
    c.post(f"/project/{pid}/delivery/unlock", data={"unlock": "1"})
    conn = db.connect()
    try:
        z = db.get_delivery(conn, pid)["delivery_zip"]
    finally:
        conn.close()
    assert z["referenced_count"] == 0, "the override handed back the holed package"


# ── the console must not report two eras at once ────────────────────────────────────
def _console(c, pid):
    return c.get(f"/project/{pid}/delivery").text


def test_a_holed_build_whose_files_are_back_says_press_rebuild(delivery):
    """The contradiction the operator hit: a red banner reading "17 of 17 files could not
    be put in the package" over a live "missing from the server" list that was EMPTY,
    while the client's room reported every file present. The banner was reading
    `referenced_count` — a number stored at BUILD TIME — and the list was reading the
    server now. One question, two eras."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
    finally:
        conn.close()
    _hole_it(db, pid, referenced=4)          # the last build had holes…
    page = _console(c, pid)                  # …but every file is on the server now
    assert "The package was built while the audio was missing" in page
    assert "press" in page and "Rebuild delivery package" in page
    assert "are not on the server" not in page, (
        "it is still claiming files are missing that are demonstrably here")


def test_files_that_really_are_gone_are_still_named(delivery):
    """The other half. When the bytes are genuinely absent, rebuilding cannot help and
    the banner must say so and name them."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    from chordential_oia.web.uploads import forget_media
    c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
        gone = (db.get_delivery(conn, pid).get("assets") or [])[0]
        forget_media(conn, gone["filename"])
    finally:
        conn.close()
    _hole_it(db, pid, referenced=4)
    page = _console(c, pid)
    assert "is not on the server" in page or "are not on the server" in page
    assert gone["orig"] in page, "the operator cannot tell WHICH file to put back"
    assert "Restore &amp; rebuild" in page


def test_a_clean_package_says_nothing_at_all(delivery):
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
    finally:
        conn.close()
    page = _console(c, pid)
    assert "could not be put in the package" not in page
    assert "built while the audio was missing" not in page
