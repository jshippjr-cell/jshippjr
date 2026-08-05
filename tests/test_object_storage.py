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
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web.uploads import _persist_upload  # noqa: E402


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
    mirror off.

    The SDK is stubbed present rather than required: `boto3` is an optional extra, and
    a test that only passes on a runner which happens to have it installed is a test
    that lies elsewhere. The SDK half of `configured` is covered by
    `test_credentials_without_the_sdk_are_half_configured_not_durable`.
    """
    from chordential_oia.storage import s3 as s3_mod
    monkeypatch.setattr(s3_mod, "_SDK_PRESENT", True)
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



def test_credentials_without_the_sdk_are_half_configured_not_durable(tmp_path, monkeypatch):
    """The cutover's live trap, reproduced.

    `render.yaml` installed `.[web,gmail,ai,stripe,postgres]` — no `s3` extra — so the
    production image had no `boto3`. With the four credentials set, `S3ObjectStore`
    still reported `durable = True`; `put()` returned False because the client could
    not be built; and `durable` is exactly what tells `persist_upload` to skip the
    SQLite mirror. Measured end to end at the time: an uploaded master ended up with
    **zero** copies, while the boot line printed "object storage active — uploads are
    durable."

    Falling back to the disk is the honest failure: loud at boot, and lossless.
    """
    import builtins

    from chordential_oia.storage import s3 as s3_mod

    real_import = builtins.__import__

    def _no_boto3(name, *a, **k):
        if name.split(".")[0] in ("boto3", "botocore"):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_boto3)
    monkeypatch.setattr(s3_mod, "_SDK_PRESENT", False)      # the memo, as a prod image sees it
    monkeypatch.setenv(STORAGE_ENV, "s3")
    monkeypatch.setenv("CHORDENTIAL_S3_BUCKET", "chordential-media")
    monkeypatch.setenv("CHORDENTIAL_S3_ACCESS_KEY", "k")
    monkeypatch.setenv("CHORDENTIAL_S3_SECRET_KEY", "s")

    assert s3_mod.S3ObjectStore().configured is False
    status = storage_status(str(tmp_path))
    assert status["active"] == "local" and status["durable"] is False
    assert status["misconfigured"] is True, (
        "credentials without the SDK must report half-configured — otherwise the "
        "mirror is skipped for a store that cannot write")
    assert isinstance(get_object_store(str(tmp_path)), LocalObjectStore)


def test_the_deploy_installs_the_sdk_it_needs_to_be_durable():
    """The seam is only as durable as the image. `CHORDENTIAL_STORAGE` can be flipped
    in the dashboard without a rebuild, so the extra has to be installed BEFORE it is
    ever needed — not at the moment someone turns it on."""
    import re
    from pathlib import Path as _P

    blueprint = _P(__file__).resolve().parents[1] / "render.yaml"
    build = re.search(r"buildCommand:\s*\"([^\"]+)\"", blueprint.read_text(encoding="utf-8"))
    assert build, "no buildCommand in render.yaml"
    extras = re.search(r"\[([^\]]+)\]", build.group(1))
    assert extras and "s3" in [e.strip() for e in extras.group(1).split(",")], (
        f"render.yaml does not install the s3 extra: {build.group(1)}")



# --------------------------------------------------------------------------- #
# Moving the existing media (the step the cutover runbook was missing)
# --------------------------------------------------------------------------- #
def _run_migration(store, monkeypatch, dry_run=False):
    import importlib.util
    import sys
    from pathlib import Path as _P

    script = _P(__file__).resolve().parents[1] / "scripts" / "migrate_uploads_to_object_store.py"
    spec = importlib.util.spec_from_file_location("mig_under_test", script)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    # Patch the SHARED module, not the script: the script is a thin CLI over
    # `storage.migrate` now, so patching its own globals would no longer reach the
    # logic. That the patch target moved is the point — see
    # `test_the_cli_and_the_console_share_one_implementation`.
    from chordential_oia.storage import migrate as shared
    monkeypatch.setattr(shared, "get_object_store", lambda root="": store)
    monkeypatch.setattr(shared, "storage_status", lambda root="": {
        "requested": "s3", "active": "s3", "durable": True, "misconfigured": False})
    monkeypatch.setattr(mig, "storage_status", lambda root="": {
        "requested": "s3", "active": "s3", "durable": True, "misconfigured": False})
    monkeypatch.setattr(sys, "argv", ["mig"] + (["--dry-run"] if dry_run else []))
    return mig.main()


class _Bucket:
    durable = True

    def __init__(self): self.items = {}
    def put(self, k, d, ct=""): self.items[k] = d; return True
    def get(self, k): return self.items.get(k)
    def exists(self, k): return k in self.items
    def size(self, k): return len(self.items[k]) if k in self.items else None
    def delete(self, k): return bool(self.items.pop(k, None))
    def local_path(self, k): return None
    def url(self, k, *, expires=3600): return f"https://bucket.example/{k}"


def test_the_migration_carries_files_that_exist_only_in_the_mirror(app_mod, monkeypatch):
    """A `cp -r` of the upload directory is not enough, and that is the whole point.

    After a redeploy wipes the ephemeral disk, a key can exist ONLY in the durable
    `media_blob` mirror. Copying the directory would leave it behind — and the disk is
    about to be removed, so "left behind" means gone.
    """
    from chordential_oia.web import db

    conn = db.connect()
    try:
        db.save_media_blob(conn, "proj9-wiped.mp3", b"ID3" + b"W" * 500, "audio/mpeg")
    finally:
        conn.close()
    on_disk = Path(os.environ["CHORDENTIAL_UPLOAD_DIR"])
    on_disk.mkdir(parents=True, exist_ok=True)
    (on_disk / "proj9-live.mp3").write_bytes(b"ID3" + b"L" * 400)

    bucket = _Bucket()
    assert _run_migration(bucket, monkeypatch) == 0
    assert "proj9-live.mp3" in bucket.items, "a file on disk did not reach the bucket"
    assert "proj9-wiped.mp3" in bucket.items, (
        "a mirror-only key was left behind — this is exactly what a directory copy misses")


def test_the_migration_refuses_to_report_success_on_a_wedged_bucket(app_mod, monkeypatch):
    """`put()` returning True is not evidence. The script reads every object back and
    compares SHA-256, because the day this matters is the day the disk is removed."""
    class Wedged(_Bucket):
        def put(self, k, d, ct=""): return True      # accepts, keeps nothing
        def get(self, k): return None

    on_disk = Path(os.environ["CHORDENTIAL_UPLOAD_DIR"])
    on_disk.mkdir(parents=True, exist_ok=True)
    (on_disk / "master.wav").write_bytes(b"RIFF" + b"x" * 100)
    assert _run_migration(Wedged(), monkeypatch) == 1


def test_the_migration_writes_nothing_on_a_dry_run(app_mod, monkeypatch):
    on_disk = Path(os.environ["CHORDENTIAL_UPLOAD_DIR"])
    on_disk.mkdir(parents=True, exist_ok=True)
    (on_disk / "take.mp3").write_bytes(b"ID3" + b"y" * 100)
    bucket = _Bucket()
    assert _run_migration(bucket, monkeypatch, dry_run=True) == 0
    assert bucket.items == {}, "a dry run wrote to the bucket"


# --------------------------------------------------------------------------- #
# Every write goes through it
# --------------------------------------------------------------------------- #
def test_no_route_writes_to_the_upload_directory_itself():
    """The claim `_persist_upload` used to make in its docstring and did not keep.
    Reads and the packaging step may touch the directory; opening it for WRITING is
    what put four of five files on one disk.

    Scanned across the whole web package, not just `app.py`: ADR-0044 moved the write
    door into `uploads.py` and the packaging step into `delivery_ops.py`, so a scan of
    one file would now pass by looking at the wrong place. Both spellings of the
    directory count — the frozen `UPLOAD_DIR` and the per-call `upload_dir()`.
    """
    import chordential_oia.web.app as app_mod
    web = Path(app_mod.__file__).parent
    offenders = []
    for path in sorted(web.glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if '"wb"' not in line:
                continue
            if "open(os.path.join(UPLOAD_DIR" in line or "open(os.path.join(upload_dir()" in line:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
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
    # Patched on `web.uploads`, not on `app` — that is where the write door lives since
    # ADR-0044 moved it, and a function resolves its globals in its own module.
    from chordential_oia.web import uploads as uploads_mod
    monkeypatch.setattr(uploads_mod, "get_object_store", lambda *a, **k: fake)

    conn = db.connect()
    try:
        before = {r["name"] for r in conn.execute("SELECT name FROM media_blob")}
        _persist_upload(conn, "durable-master.mp3", b"ID3" + b"C" * 100, "audio/mpeg")
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


# --------------------------------------------------------------------------- #
# The operator's door: a page, not a shell
# --------------------------------------------------------------------------- #
def test_the_console_reports_the_store_without_reading_a_log(app_mod):
    """Until this page existed, the only signal was a line printed at boot. If a
    credential is revoked six months from now, uploads start failing and nothing
    surfaces it until someone scrolls back through deploy logs."""
    with TestClient(app_mod.app) as c:
        r = c.get("/settings/storage")
    assert r.status_code == 200
    assert "Local disk" in r.text                      # this instance is on the disk
    assert "Files on disk" in r.text                   # and it counts what is waiting


def test_the_console_refuses_to_copy_onto_the_disk_it_is_replacing(app_mod):
    """Copying onto the disk we are about to remove is not a migration. The button is
    disabled in the page AND the call refuses server-side — a disabled attribute is a
    hint, not a control."""
    with TestClient(app_mod.app) as c:
        page = c.get("/settings/storage")
        assert "disabled" in page.text
        r = c.post("/settings/storage/migrate", data={"mode": "live"})
    assert r.status_code == 200
    assert "Refused" in r.text


def test_the_console_copies_and_shows_every_file(app_mod, monkeypatch):
    """The button does the same work as the script, including carrying the mirror-only
    keys a folder copy would lose."""
    from chordential_oia.storage import local as local_mod
    from chordential_oia.storage import migrate as mig
    from chordential_oia.web import db

    class Bucket(local_mod.LocalObjectStore):
        durable = True

    bucket = Bucket(os.environ["CHORDENTIAL_UPLOAD_DIR"] + "-bucket")
    monkeypatch.setattr(mig, "get_object_store", lambda root="": bucket)
    monkeypatch.setattr(mig, "storage_status", lambda root="": {
        "requested": "s3", "active": "s3", "durable": True, "misconfigured": False})

    on_disk = Path(os.environ["CHORDENTIAL_UPLOAD_DIR"])
    on_disk.mkdir(parents=True, exist_ok=True)
    (on_disk / "proj7-v1.mp3").write_bytes(b"ID3" + b"m" * 300)
    conn = db.connect()
    try:
        db.save_media_blob(conn, "proj7-wiped.mp3", b"ID3" + b"w" * 200, "audio/mpeg")
    finally:
        conn.close()

    with TestClient(app_mod.app) as c:
        r = c.post("/settings/storage/migrate", data={"mode": "live"})
    assert r.status_code == 200
    assert "Done" in r.text and "copied" in r.text
    assert bucket.get("proj7-v1.mp3") is not None
    assert bucket.get("proj7-wiped.mp3") is not None, "the mirror-only key was left behind"


def test_the_cli_and_the_console_share_one_implementation():
    """I told the operator these cannot drift. That is only true if the script imports
    the module rather than carrying its own copy of the logic."""
    import ast
    from pathlib import Path as _P

    script = _P(__file__).resolve().parents[1] / "scripts" / "migrate_uploads_to_object_store.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                for a in n.names if (n.module or "").endswith("storage.migrate")}
    assert {"migrate", "inventory", "verify_round_trip"} <= imported, (
        "the script no longer imports the shared implementation — it has its own copy, "
        "and the button and the command can now disagree")
    body = script.read_text(encoding="utf-8")
    assert "hashlib" not in body, "the script re-implements the digest check"


# --------------------------------------------------------------------------- #
# A write that did not land must never leave zero copies
# --------------------------------------------------------------------------- #
def test_a_failed_remote_write_keeps_the_bytes_in_the_mirror(app_mod, monkeypatch):
    """Reported live: the first upload after the R2 switch played back as SILENCE.

    `persist_upload` discarded `put()`'s return value, and `durable` then skipped the
    mirror — so a remote write that did not land left the file with **zero copies**,
    while the version row was still created pointing at the missing key. The client's
    player fetched a nonexistent object and played nothing.

    A failed write must fall back to the mirror. Losing a master is not an acceptable
    outcome of a best-effort seam.
    """
    from chordential_oia.web import db, uploads as uploads_mod

    class Refusing:
        durable = True
        def put(self, k, d, ct=""): return False
        def get(self, k): return None
        def exists(self, k): return False
        def delete(self, k): return False
        def local_path(self, k): return None
        def url(self, k, *, expires=3600): return None

    monkeypatch.setattr(uploads_mod, "get_object_store", lambda root="": Refusing())
    conn = db.connect()
    try:
        ok = uploads_mod._persist_upload(conn, "lost-master.mp3", b"ID3" + b"M" * 500,
                                         "audio/mpeg")
        blob = db.get_media_blob(conn, "lost-master.mp3")
    finally:
        conn.close()
    assert ok is False, "a failed write must report itself"
    assert blob is not None and blob[0] == b"ID3" + b"M" * 500, (
        "the bytes were lost — this is the silence the operator heard")


def test_a_write_that_reports_success_but_did_not_land_is_caught(app_mod, monkeypatch):
    """The nastier shape: `put()` returns True and the object is not retrievable. Trust
    the read-back, never the return value — the same rule the migration follows."""
    from chordential_oia.web import db, uploads as uploads_mod

    class Lying:
        durable = True
        def put(self, k, d, ct=""): return True      # claims success
        def get(self, k): return None
        def exists(self, k): return False            # ...but nothing is there
        def delete(self, k): return False
        def local_path(self, k): return None
        def url(self, k, *, expires=3600): return None

    monkeypatch.setattr(uploads_mod, "get_object_store", lambda root="": Lying())
    conn = db.connect()
    try:
        ok = uploads_mod._persist_upload(conn, "phantom.mp3", b"ID3" + b"P" * 300,
                                         "audio/mpeg")
        blob = db.get_media_blob(conn, "phantom.mp3")
    finally:
        conn.close()
    assert ok is False
    assert blob is not None, "a lying store still must not cost us the bytes"


def test_a_healthy_durable_store_still_skips_the_mirror(app_mod, monkeypatch):
    """The fix must not undo ADR-0043's point: with a working bucket the mirror stays
    off, or every master doubles into the database for no benefit."""
    from chordential_oia.web import db, uploads as uploads_mod

    class Working:
        durable = True
        def __init__(self): self.items = {}
        def put(self, k, d, ct=""): self.items[k] = d; return True
        def get(self, k): return self.items.get(k)
        def exists(self, k): return k in self.items
        def delete(self, k): return bool(self.items.pop(k, None))
        def local_path(self, k): return None
        def url(self, k, *, expires=3600): return f"https://bucket.example/{k}"

    store = Working()
    monkeypatch.setattr(uploads_mod, "get_object_store", lambda root="": store)
    conn = db.connect()
    try:
        ok = uploads_mod._persist_upload(conn, "healthy.mp3", b"ID3" + b"H" * 200,
                                         "audio/mpeg")
        blob = db.get_media_blob(conn, "healthy.mp3")
    finally:
        conn.close()
    assert ok is True
    assert store.items.get("healthy.mp3") is not None
    assert blob is None, "a durable store must not also mirror — that is the bloat"


def test_the_console_names_a_file_that_exists_nowhere(app_mod):
    """The question the operator actually has when a client hears silence: the portal is
    asking for a file — is it there?

    A version row can reference a key no store holds, and nothing says so until someone
    presses play. Reported live: an upload published, appeared in the portal, and played
    back as nothing; three round trips of log-reading later we still could not name the
    file. Now the page does.
    """
    from chordential_oia.web import db

    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        delivery = db.get_delivery(conn, pid)
        versions = list(delivery.get("versions") or [])
        versions.append({"n": 99, "label": "v99 Ghost", "url": "/uploads/proj-ghost.mp3",
                         "filename": "proj-ghost.mp3", "name": "GHOST"})
        db.update_delivery(conn, pid, "versions", versions)
    finally:
        conn.close()

    with TestClient(app_mod.app) as c:
        r = c.get("/settings/storage")
    assert r.status_code == 200
    assert "will not play" in r.text
    assert "missing everywhere" in r.text
    assert "proj-ghost.mp3" in r.text, "the missing file must be named, not just counted"


def test_the_page_never_renders_a_python_method_repr(app_mod):
    """`inv.keys` resolved to the dict's `.keys` METHOD in Jinja, so the page showed
    `<built-in method keys of dict object at 0x…>` where a count belonged. Shipped, and
    the operator saw it."""
    with TestClient(app_mod.app) as c:
        r = c.get("/settings/storage")
    assert "built-in method" not in r.text
    assert "object at 0x" not in r.text


# --------------------------------------------------------------------------- #
# Present is not playable
# --------------------------------------------------------------------------- #
def test_a_present_but_empty_file_is_reported_as_unplayable(app_mod):
    """Existence and playability are different claims, and only one of them was checked.

    A zero-byte object is in the bucket. It answers `exists()` with True, it survives a
    SHA-verified migration, and it plays as silence — indistinguishable to the person
    pressing play from a file that was never uploaded, and the exact opposite of it to
    anyone reading a green checkmark. The audit reports the SIZE for every referenced
    file so the two questions stop sharing one answer.
    """
    from chordential_oia.web import db

    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        db.save_media_blob(conn, "proj-hollow.mp3", b"", "audio/mpeg")
        delivery = db.get_delivery(conn, pid)
        versions = list(delivery.get("versions") or [])
        versions.append({"n": 98, "label": "v98 Hollow", "url": "/uploads/proj-hollow.mp3",
                         "filename": "proj-hollow.mp3", "name": "HOLLOW"})
        db.update_delivery(conn, pid, "versions", versions)
    finally:
        conn.close()

    from chordential_oia.storage.migrate import audit_referenced_media
    conn = db.connect()
    try:
        audit = audit_referenced_media(conn, os.environ["CHORDENTIAL_UPLOAD_DIR"])
    finally:
        conn.close()
    row = next(r for r in audit["rows"] if r["key"] == "proj-hollow.mp3")
    assert row["empty"] is True
    assert row["ok"] is False, "a zero-byte file must not be reported as fine"
    assert audit["empty"] == 1

    with TestClient(app_mod.app) as c:
        r = c.get("/settings/storage")
    assert "empty — 0 bytes" in r.text
    assert "proj-hollow.mp3" in r.text


def test_every_referenced_file_reports_its_size(app_mod):
    """Not just the broken ones. The operator's question is "is the file the portal is
    asking for a real file", and a table that only lists failures cannot answer it for
    the row they came to look at."""
    from chordential_oia.web import db
    from chordential_oia.storage.migrate import audit_referenced_media

    conn = db.connect()
    try:
        audit = audit_referenced_media(conn, os.environ["CHORDENTIAL_UPLOAD_DIR"])
    finally:
        conn.close()
    assert audit["checked"] > 0, "the seeded demo references no media at all"
    for row in audit["rows"]:
        assert "bytes" in row and isinstance(row["bytes"], int)
        if row["ok"]:
            assert row["bytes"] > 0 and row["where"] in ("bucket", "mirror")


# --------------------------------------------------------------------------- #
# The seeded demo is media too
# --------------------------------------------------------------------------- #
def test_seeded_demo_media_survives_the_disk_being_wiped(app_mod):
    """Found in production by the audit above, which named exactly two files no store
    held — and both were seeded, not uploaded.

    The seed staged the demo master with `shutil.copyfile` and pushed the built ZIP
    straight at the store, both bypassing the write door, so neither ever reached the
    SQLite mirror. Seeding is idempotent and never ran again; the first redeploy wiped
    the ephemeral disk and the demo campaign's ":60 master" and "Download everything"
    have been dead ever since. The guard test for this only matched `open(…, "wb")`
    spellings, so it watched two doors and there were four.
    """
    import shutil

    from chordential_oia.web import db
    from chordential_oia.storage.migrate import audit_referenced_media

    root = os.environ["CHORDENTIAL_UPLOAD_DIR"]
    shutil.rmtree(root, ignore_errors=True)          # the redeploy

    conn = db.connect()
    try:
        audit = audit_referenced_media(conn, root)
    finally:
        conn.close()
    broken = [r for r in audit["rows"] if not r["ok"]]
    assert broken == [], (
        "seeded media the demo portal points at did not survive a disk wipe: "
        + ", ".join(f"{r['what']} ({r['key']})" for r in broken))


def test_a_built_delivery_package_reaches_the_bucket(app_mod, monkeypatch):
    """The one artefact the client pays for was the one that never went to the bucket.

    `_build_delivery_package` wrote the ZIP to the disk and then called
    `db.save_media_blob` directly, so with a bucket configured the package sat on the
    ephemeral disk plus a SQLite blob — the mirror bloat the Postgres cutover exists to
    end, on the largest file in the system.
    """
    from chordential_oia.web import db, delivery_ops

    bucket = _Bucket()
    monkeypatch.setattr("chordential_oia.storage.get_object_store",
                        lambda *a, **k: bucket)
    import chordential_oia.web.uploads as uploads_mod
    monkeypatch.setattr(uploads_mod, "get_object_store", lambda *a, **k: bucket)

    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        pkg = delivery_ops._build_delivery_package(conn, pid)
    finally:
        conn.close()
    assert pkg is not None
    key = os.path.basename(pkg["filename"])
    assert key in bucket.items, "the delivery package never reached the bucket"
    assert len(bucket.items[key]) > 0

