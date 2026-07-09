"""Durable uploads (the review player kept 404ing after a redeploy wiped local disk):
uploaded media is mirrored into the DB and served from there when the disk copy is gone.
"""
import importlib, os


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    for m in ("db", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def test_upload_survives_disk_wipe(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    audio = b"ID3\x03\x00\x00\x00" + b"\xff\xfb\x90\x00" * 500
    app_mod._persist_upload(conn, "proj9-v1.mp3", audio)
    # the bytes are mirrored into the durable DB
    blob = app_mod.db.get_media_blob(conn, "proj9-v1.mp3")
    conn.close()
    assert blob is not None and blob[0] == audio

    up = str(tmp_path / "up")
    with TestClient(app_mod.app) as c:
        assert c.get("/uploads/proj9-v1.mp3").status_code == 200         # disk copy
        os.remove(os.path.join(up, "proj9-v1.mp3"))                      # simulate redeploy wipe
        r = c.get("/uploads/proj9-v1.mp3")
        assert r.status_code == 200                                      # served from the DB
        assert r.content == audio and r.headers["content-type"] == "audio/mpeg"
        assert os.path.exists(os.path.join(up, "proj9-v1.mp3"))          # rehydrated to disk


def test_zip_never_served_from_uploads(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    app_mod._persist_upload(conn, "bundle.zip", b"PK\x03\x04zip")
    conn.close()
    with TestClient(app_mod.app) as c:
        # the payment-gated ZIP backdoor stays closed even with a DB mirror present
        assert c.get("/uploads/bundle.zip").status_code == 404


def test_delivery_zip_download_survives_disk_wipe(tmp_path, monkeypatch):
    """The payment-gated delivery ZIP kept 404ing after a redeploy wiped disk. It's now
    mirrored into the DB at build time and rehydrated (or rebuilt) on download."""
    import glob
    from fastapi.testclient import TestClient
    from chordential_oia.models import (
        Opportunity, BuyerType, MusicRequirement)
    app_mod = _app(tmp_path, monkeypatch)
    up = str(tmp_path / "up")
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="X", need="Campaign", description="x", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0))
    pid = app_mod.db.insert_project(conn, oid, "X", "Campaign", 0, 0, ["Composer"])
    ptok = app_mod.db.ensure_project_share_token(conn, pid)
    app_mod._persist_upload(conn, f"proj{pid}-a.mp3", b"ID3audio-master", "audio/mpeg")
    app_mod.db.update_delivery(conn, pid, "assets",
        [{"label": "Final master", "filename": f"proj{pid}-a.mp3",
          "url": f"/uploads/proj{pid}-a.mp3", "kind": "audio"}])
    app_mod.db.update_delivery(conn, pid, "download_unlocked", True)
    pkg = app_mod._build_delivery_package(conn, pid)
    zipname = os.path.basename(pkg["filename"])
    assert app_mod.db.get_media_blob(conn, zipname) is not None     # mirrored at build
    conn.close()

    with TestClient(app_mod.app) as c:
        # simulate a redeploy that wipes the ephemeral disk
        for f in glob.glob(os.path.join(up, "*")):
            os.remove(f)
        r = c.get(f"/project/{pid}/dl/{zipname}?k={ptok}")
        assert r.status_code == 200 and r.content[:2] == b"PK"       # rehydrated from the DB

        # a legacy ZIP not in the mirror rebuilds from durable source media
        conn = app_mod.db.connect()
        app_mod.db.delete_media_blob(conn, zipname)
        conn.close()
        for f in glob.glob(os.path.join(up, "*")):
            os.remove(f)
        r2 = c.get(f"/project/{pid}/dl/{zipname}?k={ptok}")
        assert r2.status_code == 200 and r2.content[:2] == b"PK"     # rebuilt
