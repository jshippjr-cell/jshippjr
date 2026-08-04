"""Client media stops depending on one machine's disk.

The deferred-work note was blunt: *"migrate uploads to object storage first or the
cutover destroys every client cut, master and stem."* Measured on a seeded instance
before this change, **four of five uploaded files had exactly one copy** — because three
routes wrote straight into `UPLOAD_DIR`, bypassing the helper whose own docstring claimed
to be *"the single place that persists media, so every write site is durable"*: the
intake artifact (a voice memo, a transcript, an RFP), the procurement document (a W-9, a
COI), and the opportunity doc upload (the audio on the client-facing brief).

ADR-0043 puts every write and read behind `storage.get_object_store()`, on the same
provider-seam pattern as payments and mail: local disk by default (behaviour unchanged),
S3-compatible when `CHORDENTIAL_STORAGE=s3`.

**What these tests do and don't prove.** They exercise the seam, the routing, and the
local backend for real. They do *not* reach a live bucket — there are no credentials in
this environment — so the S3 backend is covered by its contract and its configuration
logic, and a `FakeStore` stands in to prove the app is genuinely backend-agnostic. The
first real R2 write is an ops step, not something a test here can claim.
"""

import importlib
import os
from pathlib import Path

import pytest

from chordential_oia.storage import (
    LocalObjectStore, STORAGE_ENV, get_object_store, storage_status,
)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# The seam
# --------------------------------------------------------------------------- #
def test_the_default_is_the_disk_and_nothing_changes(tmp_path, monkeypatch):
    """An instance that configures nothing must behave exactly as it did before the
    seam existed. This is the whole risk budget of the change."""
    monkeypatch.delenv(STORAGE_ENV, raising=False)
    store = get_object_store(str(tmp_path))
    assert isinstance(store, LocalObjectStore)
    assert store.durable is False


def test_the_local_store_round_trips(tmp_path):
    s = LocalObjectStore(str(tmp_path))
    assert s.put("a.mp3", b"ID3xyz", "audio/mpeg")
    assert s.get("a.mp3") == b"ID3xyz"
    assert s.exists("a.mp3")
    assert s.local_path("a.mp3") == str(tmp_path / "a.mp3")
    assert s.url("a.mp3") is None            # served by the app, not by URL
    assert s.delete("a.mp3") and not s.exists("a.mp3")
    assert s.get("a.mp3") is None


@pytest.mark.parametrize("key", ["../escape.mp3", "/etc/passwd", "a/b.mp3", "", "."])
def test_the_local_store_refuses_to_leave_its_root(tmp_path, key):
    """The traversal guard moved here from `_safe_upload_path`, so it travels with
    the store instead of sitting beside one of several callers."""
    s = LocalObjectStore(str(tmp_path))
    assert s.put(key, b"x") is False
    assert s.get(key) is None
    assert s.exists(key) is False
    assert s.local_path(key) is None


def test_selecting_s3_without_credentials_falls_back_loudly(tmp_path, monkeypatch):
    """Half-configured must not silently accept uploads into a bucket that isn't
    there. It degrades to disk AND reports itself misconfigured."""
    monkeypatch.setenv(STORAGE_ENV, "s3")
    for var in ("CHORDENTIAL_S3_BUCKET", "CHORDENTIAL_S3_ACCESS_KEY",
                "CHORDENTIAL_S3_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert isinstance(get_object_store(str(tmp_path)), LocalObjectStore)
    status = storage_status(str(tmp_path))
    assert status["requested"] == "s3"
    assert status["active"] == "local"
    assert status["misconfigured"] is True


def test_a_fully_configured_s3_reports_durable(tmp_path, monkeypatch):
    """Configuration only — no network. Proves the selector hands back the remote
    backend and that it declares itself durable, which is what turns the SQLite
    mirror off."""
    monkeypatch.setenv(STORAGE_ENV, "s3")
    monkeypatch.setenv("CHORDENTIAL_S3_BUCKET", "chordential-media")
    monkeypatch.setenv("CHORDENTIAL_S3_ACCESS_KEY", "k")
    monkeypatch.setenv("CHORDENTIAL_S3_SECRET_KEY", "s")
    store = get_object_store(str(tmp_path))
    assert store.durable is True
    assert store.__class__.__name__ == "S3ObjectStore"
    assert storage_status(str(tmp_path))["misconfigured"] is False


def test_the_s3_backend_never_raises_without_boto3(tmp_path, monkeypatch):
    """Best-effort like every other seam: a missing SDK or a wedged bucket returns
    False/None. Losing the bucket must degrade to "that file isn't available", never
    to a 500 on the client's portal."""
    monkeypatch.setenv("CHORDENTIAL_S3_BUCKET", "b")
    monkeypatch.setenv("CHORDENTIAL_S3_ACCESS_KEY", "k")
    monkeypatch.setenv("CHORDENTIAL_S3_SECRET_KEY", "s")
    from chordential_oia.storage.s3 import S3ObjectStore
    s = S3ObjectStore()
    monkeypatch.setattr(s, "_c", lambda: None)
    assert s.put("a", b"x") is False
    assert s.get("a") is None
    assert s.exists("a") is False
    assert s.delete("a") is False
    assert s.url("a") is None
    assert s.local_path("a") is None


# --------------------------------------------------------------------------- #
# Every write goes through it
# --------------------------------------------------------------------------- #
def test_no_route_writes_to_the_upload_directory_itself():
    """The claim `_persist_upload` used to make in its docstring and did not keep.
    Reads and the packaging step may touch the directory; opening it for WRITING is
    what put four of five files on one disk."""
    import chordential_oia.web.app as app_mod
    src = Path(app_mod.__file__).read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in src.splitlines()
        if "open(os.path.join(UPLOAD_DIR" in line and '"wb"' in line
    ]
    assert offenders == [], (
        "these write client media straight to disk instead of through the store:\n  "
        + "\n  ".join(offenders))


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "s.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv(STORAGE_ENV, raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _ids():
    from chordential_oia.web import db
    conn = db.connect()
    try:
        return (conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"],
                conn.execute("SELECT id FROM projects WHERE share_token != '' "
                             "LIMIT 1").fetchone()["id"])
    finally:
        conn.close()


def test_every_upload_route_leaves_a_second_copy(app_mod):
    """The measurement that opened this: three routes bypassed the mirroring helper,
    so a voice memo, a compliance document and the brief's audio each had exactly one
    copy on the disk the cutover removes."""
    from chordential_oia.web import db

    opp_id, project_id = _ids()
    with TestClient(app_mod.app) as c:
        c.post(f"/project/{project_id}/delivery/version",
               files={"file": ("take.mp3", b"ID3" + b"A" * 5000, "audio/mpeg")})
        c.post(f"/opportunity/{opp_id}/intelligence/analyze",
               data={"stance": "objective", "lane": "discovery_call", "text": ""},
               files={"file": ("memo.txt", b"a voice memo transcript", "text/plain")})
        c.post(f"/opportunity/{opp_id}/doc/upload",
               files={"file": ("cue.mp3", b"ID3" + b"B" * 5000, "audio/mpeg")},
               data={"label": "Cue"})

    conn = db.connect()
    try:
        mirrored = {r["name"] for r in conn.execute("SELECT name FROM media_blob")}
    finally:
        conn.close()
    for expect in ("intake_", "opp", "proj"):
        assert any(n.startswith(expect) for n in mirrored), (
            f"nothing matching {expect!r} was mirrored — that route still writes "
            f"only to disk. Mirrored: {sorted(mirrored)}")


def test_the_mirror_is_skipped_when_the_store_is_durable(app_mod, monkeypatch, tmp_path):
    """The mirror is the net under a store that isn't durable. With a real bucket it
    would double every master into SQLite for no benefit — and that bloat is part of
    why the Postgres cutover exists."""
    from chordential_oia.web import db

    class FakeStore:
        durable = True
        def __init__(self): self.items = {}
        def put(self, k, d, ct=""): self.items[k] = d; return True
        def get(self, k): return self.items.get(k)
        def exists(self, k): return k in self.items
        def delete(self, k): return bool(self.items.pop(k, None))
        def local_path(self, k): return None
        def url(self, k, *, expires=3600): return f"https://bucket.example/{k}?sig=x"

    fake = FakeStore()
    monkeypatch.setattr(app_mod, "get_object_store", lambda *a, **k: fake)

    conn = db.connect()
    try:
        before = {r["name"] for r in conn.execute("SELECT name FROM media_blob")}
        app_mod._persist_upload(conn, "durable-master.mp3", b"ID3" + b"C" * 100, "audio/mpeg")
        after = {r["name"] for r in conn.execute("SELECT name FROM media_blob")}
    finally:
        conn.close()

    assert fake.items.get("durable-master.mp3"), "the bytes never reached the store"
    assert after == before, "a durable store still got mirrored into SQLite"


def test_a_remote_store_serves_by_redirect_not_by_streaming(app_mod, monkeypatch):
    """With a bucket, bytes must not stream through this process — the browser talks
    to the bucket directly, which is also what keeps Range/seek working on a long cut."""
    class FakeStore:
        durable = True
        def put(self, k, d, ct=""): return True
        def get(self, k): return None
        def exists(self, k): return True
        def delete(self, k): return True
        def local_path(self, k): return None
        def url(self, k, *, expires=3600): return f"https://bucket.example/{k}?sig=x"

    monkeypatch.setattr(app_mod, "get_object_store", lambda *a, **k: FakeStore())
    with TestClient(app_mod.app) as c:
        r = c.get("/uploads/anything.mp3", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith("https://bucket.example/anything.mp3")


def test_the_zip_is_still_never_served_from_uploads(app_mod, monkeypatch):
    """A payment-gated deliverable must not become reachable just because the store
    changed. The .zip block predates this work and has to survive it."""
    class FakeStore:
        durable = True
        def put(self, k, d, ct=""): return True
        def get(self, k): return None
        def exists(self, k): return True
        def delete(self, k): return True
        def local_path(self, k): return None
        def url(self, k, *, expires=3600): return "https://bucket.example/x"

    monkeypatch.setattr(app_mod, "get_object_store", lambda *a, **k: FakeStore())
    with TestClient(app_mod.app) as c:
        assert c.get("/uploads/HolidayAnthem_Delivery.zip",
                     follow_redirects=False).status_code == 404


def test_uploads_still_serve_off_disk_by_default(app_mod):
    """The default path, end to end: upload through a real route, fetch it back."""
    _opp, project_id = _ids()
    with TestClient(app_mod.app) as c:
        c.post(f"/project/{project_id}/delivery/version",
               files={"file": ("take.mp3", b"ID3" + b"Z" * 4000, "audio/mpeg")})
        conn_names = [p.name for p in
                      Path(os.environ["CHORDENTIAL_UPLOAD_DIR"]).glob("proj*.mp3")]
        assert conn_names, "the upload never reached the disk"
        r = c.get(f"/uploads/{conn_names[0]}")
    assert r.status_code == 200
    assert r.content.startswith(b"ID3")
