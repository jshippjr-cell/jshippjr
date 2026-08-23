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


def test_the_client_download_heals_a_holed_package_by_itself(delivery):
    """Asked directly: *"why is this coming up, when the client approve 2 more audio
    stems… at very least there should be 2 audio files in the delivery package"*.

    The banner reports the LAST build, so it can be alarming about a package that is
    already recoverable. What matters is that the client cannot receive the empty one:
    the download route rebuilds a stale package before serving it, so the audio reaches
    them whether or not the operator presses anything.
    """
    import io
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, pid)
        z = dict(pkg)
        z["referenced_count"] = 4                 # built while the audio was missing
        db.update_delivery(conn, pid, "delivery_zip", z)
        db.update_delivery(conn, pid, "state", "Delivered")
        db.update_delivery(conn, pid, "download_unlocked", True)
        tok = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as anon:
        r = anon.get(f"/project/{pid}/dl/{z['filename']}", params={"k": tok})
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    audio = [n for n in names if n.lower().endswith((".wav", ".mp3"))]
    assert len(audio) == 5, f"the client still received a package with no audio: {names}"
    conn = db.connect()
    try:
        assert db.get_delivery(conn, pid)["delivery_zip"]["referenced_count"] == 0
    finally:
        conn.close()


def test_the_banner_says_they_are_covered(delivery):
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        _build_delivery_package(conn, pid)
    finally:
        conn.close()
    _hole_it(db, pid, referenced=4)
    page = _console(c, pid)
    # The sentence wraps in the template, so match either side of the line break rather
    # than a phrase that only exists in the source.
    assert "You are covered either way" in page
    assert "cannot receive the empty one" in page


# ── the deadlock: no link, so the heal could never fire ─────────────────────────────
def _client_payoff(pid, tok):
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as anon:
        page = anon.get(f"/room/{pid}", params={"k": tok}).text
    i = page.index('class="payoff"')
    return page[i:i + 1600]


def _delivered_with_holes(db, pid, *, recoverable):
    """A package built while the audio was missing. ``recoverable`` decides whether the
    bytes are back on the server now."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    from chordential_oia.web.uploads import forget_media
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, pid)
        z = dict(pkg)
        z["referenced_count"] = 4
        db.update_delivery(conn, pid, "delivery_zip", z)
        db.update_delivery(conn, pid, "state", "Delivered")
        db.update_delivery(conn, pid, "download_unlocked", True)
        if not recoverable:
            for a in (db.get_delivery(conn, pid).get("assets") or []):
                forget_media(conn, a["filename"])
        return db.ensure_project_share_token(conn, pid), z["filename"]
    finally:
        conn.close()


def test_a_recoverable_package_still_gives_the_client_the_download(delivery):
    """THE deadlock, reported five times: *"THERE IS NO WHERE INSIDE THE ROOM THAT ALLOWS
    FOR ME TO DOWNLOAD"*.

    A holed package replaced the download with "being re-assembled" — and the rebuild
    that fills the holes runs inside the DOWNLOAD ROUTE. Hiding the link therefore
    removed the only thing that could fix it. The client could not break out from inside
    the room, and the operator could not see why.
    """
    _c, db, pid = delivery
    tok, _zip = _delivered_with_holes(db, pid, recoverable=True)
    block = _client_payoff(pid, tok)
    assert "Download everything" in block, "the client still has no way to download"
    assert "being re-assembled" not in block


def test_clicking_it_hands_them_the_audio(delivery):
    """And the link is not decorative: the download rebuilds first, so what arrives has
    the audio in it."""
    import io
    import re as _re
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    _c, db, pid = delivery
    tok, _zip = _delivered_with_holes(db, pid, recoverable=True)
    block = _client_payoff(pid, tok)
    m = _re.search(r'href="(/project/\d+/dl/[^"]+)"', block)
    assert m, "no download URL rendered"
    with TestClient(app_mod.app) as anon:
        r = anon.get(m.group(1).replace("&amp;", "&"))
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len([n for n in names if n.lower().endswith((".wav", ".mp3"))]) == 5, names
    conn = db.connect()
    try:
        assert db.get_delivery(conn, pid)["delivery_zip"]["referenced_count"] == 0
    finally:
        conn.close()


def test_an_unrecoverable_package_is_still_withheld(delivery):
    """The other half stands. When the audio is genuinely gone, a ZIP of paperwork
    labelled "Download everything" is worse than offering nothing."""
    _c, db, pid = delivery
    tok, _zip = _delivered_with_holes(db, pid, recoverable=False)
    block = _client_payoff(pid, tok)
    assert "being re-assembled" in block
    assert "Download everything" not in block


# ── two new stems, published into a lane that already shipped ────────────────────────
def _lane_of(db, pid):
    from chordential_oia.web.delivery_ops import scoped_signoff
    conn = db.connect()
    try:
        lanes, _r, _a = scoped_signoff(db.get_project(conn, pid),
                                       db.get_delivery(conn, pid))
        return next(L["asset"] for L in lanes if not L.get("from_version"))
    finally:
        conn.close()


def _ship_then_publish_two_more(c, db, pid):
    """The operator's sequence: a package already delivered, then two more stems
    published into a lane that is already in it."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    from chordential_oia.web.uploads import _persist_upload
    lane = _lane_of(db, pid)
    conn = db.connect()
    try:
        assets = [{"label": lane, "url": f"/uploads/o{i}.wav", "filename": f"o{i}.wav",
                   "at": BEFORE, "orig": n, "kind": "audio"}
                  for i, n in enumerate(("SAND CASTLE_1_Vocal.wav",
                                         "SAND CASTLE_2_Drums.wav"))]
        for a in assets:
            _persist_upload(conn, a["filename"], b"RIFF" + b"\x00" * 5000, "audio/wav")
        db.update_delivery(conn, pid, "assets", assets)
        for a in assets:
            db.set_asset_approval(conn, pid, a["filename"], status="Approved",
                                  by="Marta", email="m@x.com", version="1")
        db.update_delivery(conn, pid, "state", "Delivered")
        db.update_delivery(conn, pid, "download_unlocked", True)
        _build_delivery_package(conn, pid)
        pend = []
        for i, n in enumerate(("SAND CASTLE_5_Guitar.wav", "SAND CASTLE_6_Piano.wav")):
            fn = f"n{i}.wav"
            _persist_upload(conn, fn, b"RIFF" + b"\x00" * 7000, "audio/wav")
            pend.append({"label": lane, "url": f"/uploads/{fn}", "filename": fn,
                         "orig": n, "kind": "audio", "by": "Ada",
                         "at": "2026-08-22T10:00:00+00:00"})
        db.update_delivery(conn, pid, "pending_assets", pend)
        tok = db.ensure_project_share_token(conn, pid)
        zipname = db.get_delivery(conn, pid)["delivery_zip"]["filename"]
    finally:
        conn.close()
    for i in range(2):
        c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": f"n{i}.wav", "action": "publish", "origin": "room"},
               headers={"X-Requested-With": "fetch"})
    return tok, zipname


def test_publishing_carries_the_timestamp(delivery):
    """The cause. Publishing built a fresh dict and dropped `at`, so a newly published
    file had NO DATE — and staleness compares the newest asset date against the package's
    `built_at`. Dateless new files plus older dated ones read as FRESH."""
    c, db, pid = delivery
    _ship_then_publish_two_more(c, db, pid)
    conn = db.connect()
    try:
        assets = db.get_delivery(conn, pid)["assets"]
    finally:
        conn.close()
    assert len(assets) == 4
    assert all((a.get("at") or "").strip() for a in assets), (
        "a published asset still has no timestamp")


def test_a_different_number_of_files_is_stale_on_its_own(delivery):
    """Belt and braces: the count check only ran when NO asset had a date, so one dated
    asset was enough to hide three new ones. It is now asked first, always."""
    from chordential_oia.web.delivery_ops import _package_is_stale
    c, db, pid = delivery
    _ship_then_publish_two_more(c, db, pid)
    conn = db.connect()
    try:
        d = db.get_delivery(conn, pid)
        d["delivery_zip"] = dict(d["delivery_zip"], built_at="2099-01-01T00:00:00+00:00")
        assert _package_is_stale(d, conn) is True, (
            "4 assets against a package that saw 2 reads as fresh")
    finally:
        conn.close()


def test_the_client_downloads_the_two_new_stems_by_name(delivery):
    """THE report: *"the download did not have the two new audio files"*.

    Both halves had to be fixed for this to pass. The package has to REBUILD (it read as
    fresh), and the files have to be DISTINGUISHABLE — naming every file in a lane after
    the lane produced `CAMPAIGN_Lane.wav`, `-2`, `-3`, `-4`, which is one name four times
    with a counter. All four were in the ZIP the whole time and none of them could be
    told apart.
    """
    import io
    c, db, pid = delivery
    tok, zipname = _ship_then_publish_two_more(c, db, pid)
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    conn = db.connect()
    try:
        zipname = db.get_delivery(conn, pid)["delivery_zip"]["filename"]
    finally:
        conn.close()
    with TestClient(app_mod.app) as anon:
        r = anon.get(f"/project/{pid}/dl/{zipname}", params={"k": tok})
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    for want in ("SAND CASTLE_5_Guitar.wav", "SAND CASTLE_6_Piano.wav"):
        assert any(n.endswith(want) for n in names), f"{want} is not in the package: {names}"
    for want in ("SAND CASTLE_1_Vocal.wav", "SAND CASTLE_2_Drums.wav"):
        assert any(n.endswith(want) for n in names), f"{want} was lost: {names}"


def test_a_lane_with_one_file_still_gets_the_campaign_name(delivery):
    """The rename is right when a lane holds ONE file — `CAMPAIGN_Instrumental.wav` beats
    a random upload id. It only had to stop when the lane became a folder."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    from chordential_oia.web.uploads import upload_dir
    _c, db, pid = delivery
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, pid)   # fixture: one file per lane
    finally:
        conn.close()
    names = zipfile.ZipFile(os.path.join(upload_dir(), pkg["filename"])).namelist()
    assert any("ORIGINAL_" in n for n in names), names


# ── when it still fails, it has to say WHICH and WHY ────────────────────────────────
def test_the_build_records_which_files_it_could_not_find(delivery):
    """A count cannot be checked against anything. After a fourth docs-only download the
    console and the build were still trading numbers, so the build now NAMES what it
    missed — and that list is directly comparable with the live presence check."""
    from chordential_oia.web.delivery_ops import _build_delivery_package
    _c, db, pid = delivery
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "assets", [{
            "label": "Mix-ready stem package", "filename": "vanished.wav",
            "url": "/uploads/vanished.wav", "orig": "SAND CASTLE_9_Ghost.wav",
            "kind": "audio", "at": BEFORE}])
        pkg = _build_delivery_package(conn, pid)
    finally:
        conn.close()
    assert pkg["referenced_count"] == 1
    assert pkg["referenced_names"] == ["SAND CASTLE_9_Ghost.wav"], (
        "the build knows what it missed and still will not say")


def test_the_console_names_them(delivery):
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        db.update_delivery(conn, pid, "assets", [{
            "label": "Mix-ready stem package", "filename": "vanished.wav",
            "url": "/uploads/vanished.wav", "orig": "SAND CASTLE_9_Ghost.wav",
            "kind": "audio", "at": BEFORE}])
        _build_delivery_package(conn, pid)
    finally:
        conn.close()
    page = c.get(f"/project/{pid}/delivery").text
    assert "SAND CASTLE_9_Ghost.wav" in page
    # the phrase wraps in the template, so match the half that cannot break
    assert "not find:" in page


def test_a_rebuild_that_throws_is_recorded_not_swallowed(delivery, monkeypatch):
    """The download must still succeed — a broken rebuild is not the payer's problem —
    but it swallowed the failure and served the STALE package, so a rebuild that COULD
    NOT RUN looked exactly like one with nothing to do."""
    from chordential_oia.web import project_routes
    from chordential_oia.web.delivery_ops import _build_delivery_package
    c, db, pid = delivery
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, pid)
        db.update_delivery(conn, pid, "state", "Delivered")
        db.update_delivery(conn, pid, "download_unlocked", True)
        db.update_delivery(conn, pid, "delivery_zip",
                           dict(pkg, asset_count=99))     # forces "stale"
        tok = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()

    def _boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(project_routes, "_build_delivery_package", _boom)
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as anon:
        r = anon.get(f"/project/{pid}/dl/{pkg['filename']}", params={"k": tok})
    assert r.status_code == 200, "the client's download was broken by a failed rebuild"
    conn = db.connect()
    try:
        said = " ".join((u["body"] or "") for u in db.list_updates(conn, pid))
    finally:
        conn.close()
    assert "could not be rebuilt" in said and "disk on fire" in said


# ── when the disk cannot take the files back ────────────────────────────────────────
def test_the_package_reads_the_mirror_when_the_disk_will_not_take_it(delivery, monkeypatch):
    """The state the operator's project was actually in.

    The packager resolved every asset with ``os.path.isfile`` and relied on a rehydrate
    step to put the bytes back first. That step calls ``store.put``, which returns False
    on a full ephemeral allowance — and nobody read the return value. So on a container
    whose disk was wiped and could not be refilled, every file was declared missing while
    the console (which asks the DATABASE) said all of them were present. Two answers to
    one question, and the client downloaded documents: *"I downloaded again and i got Docs
    no audio"*, *"the 2 new files arent being packaged either"* (2026-08-22).

    The bytes now go from the durable mirror straight into the archive. The disk is not
    part of the question.
    """
    import glob
    from chordential_oia.storage import local as local_mod
    from chordential_oia.web.delivery_ops import _build_delivery_package
    from chordential_oia.web.uploads import media_present, upload_dir
    _c, db, pid = delivery
    conn = db.connect()
    try:
        names = [a["filename"] for a in db.get_delivery(conn, pid)["assets"]]
        for f in glob.glob(os.path.join(upload_dir(), "*")):
            os.remove(f)                                   # the deploy
        assert all(media_present(conn, n) for n in names), "fixture lost the mirror too"
        # …and the disk will not accept them back.
        monkeypatch.setattr(local_mod.LocalObjectStore, "put",
                            lambda self, k, d, c="": False)
        pkg = _build_delivery_package(conn, pid)
        blob = db.get_media_blob(conn, pkg["filename"])
    finally:
        conn.close()
    assert pkg["referenced_count"] == 0, (
        f"the build still could not find {pkg['referenced_names']} — files the database "
        f"is holding perfectly well")
    assert blob is not None, "the package itself was not kept"
    import io
    names_in = zipfile.ZipFile(io.BytesIO(blob[0])).namelist()
    audio = [n for n in names_in if n.lower().endswith((".wav", ".mp3"))]
    assert len(audio) == 5, f"the client would receive documents only: {names_in}"


def test_without_a_reader_it_still_reports_honestly(delivery):
    """The engine keeps working with no `fetch` — it simply has nothing to fall back on,
    and says so rather than pretending. This is what the web layer's injection replaces,
    and it is the behaviour every other caller relies on."""
    import glob
    from chordential_oia.delivery import build_delivery_zip
    from chordential_oia.web.uploads import upload_dir
    _c, db, pid = delivery
    conn = db.connect()
    try:
        row = db.get_project(conn, pid)
        assignments = db.list_assignments(conn, pid)
        d = db.get_delivery(conn, pid)
        for f in glob.glob(os.path.join(upload_dir(), "*")):
            os.remove(f)
        pkg = build_delivery_zip(row, assignments, d, upload_dir())     # no fetch
    finally:
        conn.close()
    assert pkg["referenced_count"] == 4
    assert pkg["referenced_names"], "it cannot say which files it could not find"


# ── and whether any of it survives the next deploy ──────────────────────────────────
def test_the_boot_line_stops_claiming_sqlite_survives_a_deploy(tmp_path, monkeypatch):
    """It said "files at or under N MB survive a deploy" whatever the database was. A
    SQLite file inside the container is wiped by the same rebuild that wipes the uploads,
    so the sentence was FALSE in exactly the configuration where someone would lean on
    it — and a fresh upload could vanish between being made and being packaged:
    *"not even the fresh 2 new ones i just pushed through"* (operator, 2026-08-22).
    """
    import importlib
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "here.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.delenv("CHORDENTIAL_STORAGE", raising=False)
    for m in ("db", "uploads"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web.uploads import boot_line, storage_warning
    line = boot_line()
    assert "survive a deploy" not in line or "NOTHING here survives" in line
    assert "NOTHING here survives a deploy" in line
    assert storage_warning(), "the surface is told nothing"


def test_a_persistent_sqlite_path_is_not_maligned(tmp_path, monkeypatch):
    """The warning has to be about WHERE the file is, not about SQLite. A database on a
    persistent disk is a real durable mirror and must not be called broken."""
    from chordential_oia.web import db as dbm
    monkeypatch.setenv("CHORDENTIAL_DB", "/var/data/chordential.db")
    assert dbm.sqlite_is_durable() is True
    monkeypatch.setenv("CHORDENTIAL_DB", "/app/chordential.db")
    assert dbm.sqlite_is_durable() is False
    monkeypatch.setenv("CHORDENTIAL_DB", "postgresql://x/y")
    assert dbm.sqlite_path() == "" and dbm.sqlite_is_durable() is False


def test_the_console_says_it_where_the_operator_is_looking(delivery):
    c, _db, pid = delivery
    page = c.get(f"/project/{pid}/delivery").text
    assert "Nothing here is backed up." in page
    assert "on the same disk as the uploads" in page


def test_the_ROOM_says_it_too_because_that_is_where_the_work_happens(delivery):
    """*"you keep referencing the delivery console, but im testing things in the room"*
    (operator, 2026-08-22). A warning on a page nobody is on is not a warning.

    It first landed INSIDE the client-only sign-off block, where the studio never renders
    at all — so it was invisible to the one role that can act on it."""
    c, db, pid = delivery
    studio = c.get(f"/room/{pid}").text
    assert "Nothing here is backed up." in studio


def test_the_client_is_not_shown_our_storage_problem(delivery):
    """Subtracted by room.CAPS. The buyer can do nothing with this but worry."""
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    _c, db, pid = delivery
    conn = db.connect()
    try:
        tok = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    with TestClient(app_mod.app) as anon:
        page = anon.get(f"/room/{pid}", params={"k": tok}).text
    assert "Nothing here is backed up." not in page
    assert "backed up" not in page
