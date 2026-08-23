"""Keeping the files with the storage that is already paid for.

Reported live (operator, 2026-08-20): *"i dont want to take the steps to setup more
storage i want to use the storage i have and not lose files."*

Fair, and it turned out to be entirely achievable — because the durable store was already
there and only half-wired. Production runs on managed Postgres (2026-08-06), every upload
is mirrored into ``media_blob``, and ``serve_upload`` already rehydrates from that mirror
when the container's disk comes back empty. It works. It was measured working.

**The leak was one number.** ADR-0026 set the mirror ceiling at 64 MB, and its stated
reason was SQLite — *"a feature-length cut in SQLite is worse than the risk it covers"*.
The cutover changed that premise and the number stayed, so:

    5 MB stem, deploy, 200 — all bytes back.
    70 MB cut, deploy, 404 — gone.

Both had been accepted by the same door, on the same day, with the same cheerful success
message. The rule that replaces the number is the one the door should always have held:
**whatever we are willing to accept, we must be willing to keep.** The upload routes cap
what they take at 512 MB and buffer it whole to do so, so a mirror of the same size costs
no memory that has not already been spent.

And the residue is REPORTED rather than discovered. A file over the ceiling still gets
stored — refusing real work to protect a policy would be worse — but it is announced at
the moment it happens and marked on the surface while it is still there to save, which is
the only window in which saying anything is useful.
"""
import importlib
import os

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "s.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("CHORDENTIAL_MIRROR_MB", raising=False)
    monkeypatch.delenv("CHORDENTIAL_STORAGE", raising=False)
    for m in ("db", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod, db, uploads
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    return app_mod, db, uploads


# ── the rule ────────────────────────────────────────────────────────────────────────
def test_whatever_we_accept_we_are_willing_to_keep(studio):
    """The mirror ceiling is not lower than the biggest file the doors will take.

    This is the whole defect as one assertion. A door that accepts 512 MB and a mirror
    that keeps 64 MB means the system says yes to a file it has already decided to lose.
    """
    from chordential_oia.web import creator_routes, project_routes, uploads
    accept = max(creator_routes._SUBMISSION_MAX_BYTES, project_routes._CUT_MAX_BYTES)
    assert uploads.PG_MIRROR_BYTES >= accept, (
        f"the doors accept {accept // 1048576} MB and the mirror keeps only "
        f"{uploads.PG_MIRROR_BYTES // 1048576} MB — the gap is the file that vanishes")


def test_the_ceiling_depends_on_which_database_it_is(studio):
    """ADR-0026's reasoning was about SQLite and still holds there. It was never a fact
    about Postgres, which is what production has been since the cutover."""
    _app, db, uploads = studio
    conn = db.connect()
    try:
        assert uploads.mirror_cap(conn) == uploads.SQLITE_MIRROR_BYTES
    finally:
        conn.close()
    assert uploads.PG_MIRROR_BYTES > uploads.SQLITE_MIRROR_BYTES


def test_one_place_decides_it(studio):
    """`mirror_cap` is the derivation; no route may carry its own copy of the number.
    Five of them did, each computing `mirror=len(data) <= _CUT_MIRROR_BYTES`, which is
    how the policy came to be un-reviewable in one place."""
    from pathlib import Path
    web = Path(importlib.import_module("chordential_oia.web.app").__file__).parent
    for name in ("creator_routes.py", "project_routes.py", "opportunity_routes.py"):
        src = (web / name).read_text(encoding="utf-8")
        assert "_CUT_MIRROR_BYTES" not in src, f"{name} still carries its own ceiling"


def test_the_env_can_raise_or_disable_it(studio, monkeypatch):
    _app, db, uploads = studio
    conn = db.connect()
    try:
        monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "256")
        assert uploads.mirror_cap(conn) == 256 * 1024 * 1024
        monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "0")
        assert uploads.mirror_cap(conn) == 0
        # A typo must not silently switch the durable copy off.
        monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "lots")
        assert uploads.mirror_cap(conn) == uploads.SQLITE_MIRROR_BYTES
    finally:
        conn.close()


# ── what the door now reports ───────────────────────────────────────────────────────
def test_the_door_says_whether_the_bytes_will_survive(studio, monkeypatch):
    _app, db, uploads = studio
    monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "4")
    conn = db.connect()
    try:
        small = uploads._persist_upload(conn, "a.wav", b"x" * (1024 * 1024), "audio/wav")
        big = uploads._persist_upload(conn, "b.wav", b"x" * (6 * 1024 * 1024), "audio/wav")
    finally:
        conn.close()
    assert small.ok and small.durable and small.reason == ""
    assert big.ok, "a file over the ceiling must still be STORED — refusing real work is worse"
    assert not big.durable and big.reason == "too-large"


def test_the_result_is_still_a_bool_to_anyone_who_wants_one(studio):
    """`Stored` replaced a bare bool at the one door every upload goes through. Existing
    callers say `if _persist_upload(...)`, and that must keep meaning "did it store"."""
    _app, db, uploads = studio
    conn = db.connect()
    try:
        assert bool(uploads._persist_upload(conn, "c.wav", b"ok", "audio/wav")) is True
    finally:
        conn.close()


def test_an_oversized_file_is_announced_when_it_happens(studio, monkeypatch, capsys):
    """Not left to be discovered by clicking a dead link weeks later."""
    _app, db, uploads = studio
    monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "1")
    conn = db.connect()
    try:
        uploads._persist_upload(conn, "d.wav", b"x" * (3 * 1024 * 1024), "audio/wav")
    finally:
        conn.close()
    out = capsys.readouterr().out
    assert "will NOT survive the next deploy" in out and "'d.wav'" in out


def test_the_mirror_confirms_rather_than_assumes(studio):
    """`save_media_blob` returns whether the bytes are ACTUALLY there, read back by
    size. The caller stamps durability on the strength of it, so an unverified `True`
    would be a lie of exactly the kind this pass exists to remove."""
    _app, db, _uploads = studio
    conn = db.connect()
    try:
        assert db.save_media_blob(conn, "e.wav", b"1234567890", "audio/wav") is True
        assert db.media_blob_size(conn, "e.wav") == 10
        assert db.media_blob_size(conn, "nope.wav") is None
    finally:
        conn.close()


# ── the state that matters, measured ────────────────────────────────────────────────
def test_present_and_durable_are_different_questions(studio, monkeypatch):
    """The interesting state is present-but-not-durable: it downloads perfectly today
    and is gone after the next deploy. That is the window in which a warning helps."""
    _app, db, uploads = studio
    monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "2")
    conn = db.connect()
    try:
        uploads._persist_upload(conn, "keep.wav", b"x" * 1024, "audio/wav")
        uploads._persist_upload(conn, "risk.wav", b"x" * (4 * 1024 * 1024), "audio/wav")
        assert uploads.media_present(conn, "keep.wav") and uploads.media_durable(conn, "keep.wav")
        assert uploads.media_present(conn, "risk.wav"), "it is on the disk right now"
        assert not uploads.media_durable(conn, "risk.wav"), "and it will not be tomorrow"
        assert not uploads.media_present(conn, "never.wav")
        assert not uploads.media_durable(conn, "")
    finally:
        conn.close()


def test_durability_is_measured_not_stamped(studio, monkeypatch):
    """Raising the ceiling and re-storing clears the warning with no record to migrate.
    A flag written at upload time would still be reporting yesterday's policy."""
    _app, db, uploads = studio
    monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "1")
    conn = db.connect()
    try:
        data = b"x" * (2 * 1024 * 1024)
        uploads._persist_upload(conn, "f.wav", data, "audio/wav")
        assert not uploads.media_durable(conn, "f.wav")
        monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "64")
        uploads._persist_upload(conn, "f.wav", data, "audio/wav")
        assert uploads.media_durable(conn, "f.wav")
    finally:
        conn.close()


# ── the thing the operator actually asked for ───────────────────────────────────────
def test_a_file_survives_the_deploy_that_wipes_the_disk(studio):
    """The end-to-end claim, with the disk removed the way Render removes it."""
    import shutil
    from fastapi.testclient import TestClient
    app_mod, db, uploads = studio
    payload = b"ID3" + os.urandom(200_000)
    conn = db.connect()
    try:
        uploads._persist_upload(conn, "master.mp3", payload, "audio/mpeg")
    finally:
        conn.close()
    up = uploads.upload_dir()
    assert os.path.exists(os.path.join(up, "master.mp3"))

    shutil.rmtree(up)                    # the deploy
    os.makedirs(up, exist_ok=True)
    assert os.listdir(up) == []

    with TestClient(app_mod.app) as c:
        r = c.get("/uploads/master.mp3")
    assert r.status_code == 200 and r.content == payload, (
        "the file did not come back from the storage we already pay for")


def test_the_disk_heals_itself_on_the_way_past(studio):
    """Serving from the mirror also puts the file back, so the next read is a normal
    FileResponse and Range/seek works for a client scrubbing a long cut."""
    import shutil
    from fastapi.testclient import TestClient
    app_mod, db, uploads = studio
    conn = db.connect()
    try:
        uploads._persist_upload(conn, "heal.mp3", b"ID3" + b"h" * 5000, "audio/mpeg")
    finally:
        conn.close()
    up = uploads.upload_dir()
    shutil.rmtree(up); os.makedirs(up, exist_ok=True)
    with TestClient(app_mod.app) as c:
        assert c.get("/uploads/heal.mp3").status_code == 200
    assert os.path.exists(os.path.join(up, "heal.mp3")), "it served but did not restore"


# ── and the boot line stops giving stale advice ─────────────────────────────────────
def test_the_boot_line_names_the_ceiling(studio):
    """It used to say "set CHORDENTIAL_STORAGE=s3 before the Postgres cutover" — advice
    for a cutover that happened on 2026-08-06 — and said nothing about the limit that
    was actually eating files."""
    _app, _db, uploads = studio
    line = uploads.boot_line()
    assert "mirrored into" in line
    assert "before the Postgres cutover" not in line, "the stale advice is back"
    # This fixture's SQLite file sits beside the uploads, so the ceiling is beside the
    # point — the mirror dies with the disk. Naming a survivable size there was the
    # false promise fixed on 2026-08-22; what it must do is say NOTHING survives.
    assert "NOTHING here survives a deploy" in line


def test_the_ceiling_is_named_when_the_mirror_really_is_durable(studio, monkeypatch):
    """The other half: on Postgres the mirror outlives the container, so the MB ceiling
    is the number that matters and must still be stated."""
    _app, db, uploads = studio
    monkeypatch.setattr(db, "is_postgres", lambda conn: True)
    line = uploads.boot_line()
    assert "mirrored into Postgres" in line and "MB" in line
    assert "survive a deploy" in line
    assert "NOTHING here survives" not in line


def test_a_disabled_mirror_says_so_loudly(studio, monkeypatch):
    _app, _db, uploads = studio
    monkeypatch.setenv("CHORDENTIAL_MIRROR_MB", "0")
    line = uploads.boot_line()
    assert "WARNING" in line and "no upload survives a deploy" in line


def test_a_configured_bucket_still_reports_durable(studio, monkeypatch):
    """The mirror is skipped entirely with a real object store — doubling every master
    into the database would buy nothing."""
    _app, _db, uploads = studio
    monkeypatch.setattr(uploads, "storage_status",
                        lambda root="": {"requested": "s3", "active": "s3",
                                         "durable": True, "misconfigured": False})
    assert "object storage active" in uploads.boot_line()
