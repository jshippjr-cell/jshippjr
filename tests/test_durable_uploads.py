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
