"""Where client media is written.

``persist_upload`` is THE write door for uploaded bytes (ADR-0043) and every route
that accepts a file goes through it, so it cannot live in ``app.py`` — the routes that
call it are spread across /opportunity, /project and /creator, and each of those groups
is being moved into its own module.

``upload_dir()`` reads the environment on every call rather than freezing it at import.
That is not style: a dozen test modules set ``CHORDENTIAL_UPLOAD_DIR`` and then reload
only ``db`` and ``app``. A module-level constant here would never see the new value,
because ``from .uploads import UPLOAD_DIR`` binds a value and reloading ``app`` does not
re-execute this file. ``app.py`` still exposes ``UPLOAD_DIR`` for its own routes and for
those tests; it is computed at app-import time from this function.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import UploadFile

from ..storage import get_object_store, storage_status
from . import db

_HERE = os.path.dirname(__file__)


def upload_dir() -> str:
    """The directory the local object store writes to. Resolved per call — see above."""
    return os.environ.get("CHORDENTIAL_UPLOAD_DIR") or os.path.join(_HERE, "uploads")


# Audio uploads we accept for relevant-work samples.
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


#: Env override for the mirror ceiling, in megabytes. ``0`` disables the mirror.
MIRROR_MB_ENV = "CHORDENTIAL_MIRROR_MB"

#: What the DATABASE MIRROR will take when the database is **SQLite**. ADR-0026's number,
#: and ADR-0026's reasoning still holds here: a feature-length cut blobbed into a SQLite
#: file is worse than the risk it covers.
SQLITE_MIRROR_BYTES = 64 * 1024 * 1024

#: What the mirror will take when the database is **Postgres** — which production has
#: been since 2026-08-06. Deliberately the same as the largest file the upload routes
#: will ACCEPT (``CHORDENTIAL_SUBMISSION_MAX_MB`` / ``CHORDENTIAL_CUT_MAX_MB``, both
#: 512 MB), because that is the rule this constant exists to express:
#:
#:     **Whatever we are willing to accept, we must be willing to keep.**
#:
#: The old code carried ONE number, 64 MB, chosen when the mirror was SQLite. The
#: premise changed at the cutover and the number did not — so a 70 MB picture cut was
#: accepted, written to exactly one place (a container disk Render replaces on every
#: deploy) and silently lost, while a 5 MB stem beside it survived. Measured against a
#: real Postgres 16: 5 MB back after a wipe, 70 MB a 404.
#:
#: This costs no memory that has not already been spent — ``_read_capped`` buffers the
#: whole upload to enforce the accept cap in the first place, so a file big enough to
#: worry about is already resident when we decide whether to keep it.
PG_MIRROR_BYTES = 512 * 1024 * 1024


def mirror_cap(conn) -> int:
    """The largest file the durable database mirror will take, in bytes.

    THE one place this is decided (one derivation, many reporters). Resolved per call
    rather than frozen at import, for the same reason as :func:`upload_dir` — test
    modules set the environment and reload only ``db`` and ``app``.
    """
    raw = (os.environ.get(MIRROR_MB_ENV) or "").strip()
    if raw:
        try:
            return max(0, int(float(raw))) * 1024 * 1024
        except ValueError:
            pass                                # a typo must not silently disable the net
    return PG_MIRROR_BYTES if db.is_postgres(conn) else SQLITE_MIRROR_BYTES


class Stored:
    """What actually happened to the bytes.

    ``ok``       the object store accepted them — what the old bare ``bool`` return
                 meant. ``__bool__`` still answers it, so ``if _persist_upload(...)``
                 is unchanged; an ``is True`` / ``is False`` identity check is not, and
                 three tests had to move to ``.ok``.
    ``durable``  they will survive this container being replaced. THE question, and
                 until now nothing anywhere could answer it — which is why files were
                 discovered missing rather than reported at risk.
    ``reason``   why not, when not: ``too-large`` | ``mirror-failed`` | ``opted-out``.
    """

    __slots__ = ("ok", "durable", "reason")

    def __init__(self, ok: bool, durable: bool, reason: str = ""):
        self.ok, self.durable, self.reason = bool(ok), bool(durable), reason

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:                  # pragma: no cover - debugging aid
        return f"Stored(ok={self.ok}, durable={self.durable}, reason={self.reason!r})"


def _persist_upload(conn, name: str, data: bytes, content_type: str = "",
                    mirror: bool = True) -> Stored:
    """THE place client media is written (ADR-0043). Every upload route goes through
    here; none may open a file under ``upload_dir()`` itself.

    Bytes go to the configured object store — the local disk by default, an
    S3-compatible bucket when ``CHORDENTIAL_STORAGE=s3``. A real bucket is durable on
    its own, so the database mirror is skipped: doubling every master into the database
    would buy nothing.

    Without a bucket, **the database IS the durable store** and the mirror is not a
    "net" — it is the only copy that outlives a deploy. So the mirror is written for
    everything up to :func:`mirror_cap`, and a file over that cap is REPORTED rather
    than quietly accepted: the caller gets ``durable=False`` and can say so on the
    surface, which is the difference between a warning and a discovery.

    ``mirror=False`` remains for callers that genuinely do not want a second copy.

    This docstring used to claim to be "the single place that persists media, so
    every write site is durable" while three routes wrote to the directory directly
    — the intake artifact, the procurement document, and the opportunity doc upload.
    Measured on a seeded instance, four of five uploaded files had exactly one copy,
    on the disk the cutover removes. The claim is now enforced by a test.
    """
    if not content_type:
        import mimetypes
        content_type = mimetypes.guess_type(name)[0] or ""
    key = os.path.basename(name)
    store = get_object_store(upload_dir())
    durable_store = bool(getattr(store, "durable", False))

    # The write is CONFIRMED, not assumed. `put()` returning False — or returning True
    # for bytes that are not actually retrievable — used to be invisible here: the
    # return value was discarded, and `durable` then skipped the mirror, so a failed
    # remote write left the file with ZERO copies while the version row was created
    # pointing at it. The client's player fetched a missing object and played silence.
    # Reported live, 2026-08-05, on the first upload after the R2 switch.
    ok = bool(store.put(key, data, content_type))
    if ok and durable_store:
        # One HEAD against a bucket we have just written to is nothing next to the
        # upload itself, and it is the difference between "we sent it" and "it is there".
        ok = bool(store.exists(key))
    if not ok:
        # Never lose the bytes to a seam that is meant to be best-effort. The mirror is
        # the net; a remote write that did not land is exactly when it must catch.
        print(f"[storage] WARNING: the object store did not accept {key!r} — keeping the "
              f"bytes in the database mirror instead. Client media is NOT on the bucket; "
              f"re-run the migration from /settings/storage once the store is healthy.",
              flush=True)
        saved = db.save_media_blob(conn, key, data, content_type)
        return Stored(False, saved, "" if saved else "mirror-failed")

    if durable_store:
        return Stored(True, True)
    if not mirror:
        return Stored(True, False, "opted-out")

    cap = mirror_cap(conn)
    if len(data) > cap:
        # Said out loud, at the moment it happens. This is the file that disappears on
        # the next deploy, and the whole point is that nobody should have to find that
        # out by clicking a dead link weeks later.
        print(f"[storage] WARNING: {key!r} is {len(data) / 1048576:.0f} MB, over the "
              f"{cap / 1048576:.0f} MB database-mirror limit — it exists ONLY on this "
              f"container's disk and will NOT survive the next deploy. Raise "
              f"{MIRROR_MB_ENV}, or configure an object store.", flush=True)
        return Stored(True, False, "too-large")

    saved = db.save_media_blob(conn, key, data, content_type)
    if not saved:
        print(f"[storage] WARNING: the database mirror refused {key!r} — it exists ONLY "
              f"on this container's disk and will NOT survive the next deploy.",
              flush=True)
    return Stored(True, saved, "" if saved else "mirror-failed")


def persist_file(conn, name: str, path: str, content_type: str = "") -> bool:
    """THE write door for something already ON DISK (ADR-0043), without reading it.

    `_persist_upload` takes bytes, which is right for an upload arriving over HTTP and
    wrong for the delivery package: that one artefact can be a gigabyte, and `fh.read()`
    on it put the whole archive in memory on top of the copy already on disk. The web
    service was killed for exactly that the first time the packager could see the audio
    (operator, 2026-08-22). Same door, same rules — the bytes just never come through
    Python when the store can take a path.
    """
    key = os.path.basename(name or "")
    if not key:
        return False
    store = get_object_store(upload_dir())
    durable = bool(getattr(store, "durable", False))
    put_file = getattr(store, "put_file", None)
    ok = False
    try:
        if callable(put_file):
            ok = bool(put_file(key, path, content_type))
        else:
            with open(path, "rb") as fh:      # an older store: correct, just costly
                ok = bool(store.put(key, fh.read(), content_type))
    except OSError:
        return False
    if not ok:
        print(f"[storage] WARNING: the object store did not accept {key!r}.", flush=True)
    # The mirror is the net under a store that is NOT durable — and it is the one place
    # the bytes must pass through Python, so it is skipped exactly where the file is
    # largest (a bucket instance).
    if ok and not durable:
        try:
            with open(path, "rb") as fh:
                db.save_media_blob(conn, key, fh.read(), content_type)
        except OSError:
            pass
    return ok


def _store_pending_submission(conn, project_id: int, data: bytes,
                              src_filename: str, who: str) -> None:
    """A creator's submission lands here — NOT in the client-visible version ladder.
    It waits in ``delivery_json['pending_version']`` until Jon publishes it, so the
    client never hears work he hasn't vetted ("the machine proposes, Jon disposes").
    The file is written now; publishing just moves the metadata into the ladder."""
    from datetime import datetime as _dt, timezone as _tz
    ext = os.path.splitext(src_filename or "")[1].lower()
    safe_ext = ext if ext in _AUDIO_EXTS else ".mp3"
    # Unique, PERMANENT per-submission name (random suffix). The old "proj{id}-pending"
    # scheme reused one filename and — because the disk-existence check misses files that
    # live only in the durable DB mirror after a redeploy — a new submission overwrote the
    # previous version's blob under the same key, so v1/v2 ended up pointing at one file.
    safe_name = f"proj{project_id}-v{os.urandom(5).hex()}{safe_ext}"
    # The door decides whether the mirror can take it (`mirror_cap`) and says so;
    # the take records the answer so the room can warn before a deploy rather than
    # after one.
    stored = _persist_upload(conn, safe_name, data)
    # WHICH CUT this take was written against. Music is written to a picture, and the
    # picture moves — so a take is only ever in sync with one of them. Without this the
    # room could play v2 (scored to cut 1) against cut 2 and look entirely normal while
    # every hit landed late; the composer sees the drift and assumes their own bounce is
    # wrong. Stamped at the moment of submission, when the answer is not in doubt.
    pic = (db.get_delivery(conn, project_id).get("picture") or {})
    db.update_delivery(conn, project_id, "pending_version", {
        "url": f"/uploads/{safe_name}",
        "filename": safe_name,
        "orig": src_filename or "",
        "by": who or "A creator",
        "at": _dt.now(_tz.utc).isoformat(),
        "cut": int(pic.get("n") or 0) or None,
    })
    return stored


def boot_line() -> str:
    """What every boot says about where client media goes (ADR-0043).

    "We never actually turned object storage on" must not be something discovered by
    losing a master, and a half-configured switch falls back to disk silently unless it
    announces itself. Lives here rather than in ``app.py`` because it reports THIS
    module's policy — and because ``app.py`` is under a line ratchet whose whole point
    is that logic goes where it belongs.

    The no-bucket line used to read "not durable across a disk removal; set
    CHORDENTIAL_STORAGE=s3 before the Postgres cutover" — advice for a cutover that
    happened on 2026-08-06, and silence about the thing actually eating files. Without a
    bucket the DATABASE is the durable store, so the number that matters is the CEILING:
    under it a file survives a deploy, over it there is one copy on a disk Render
    replaces.
    """
    st = storage_status(upload_dir())
    if st["misconfigured"]:
        return (f"[storage] WARNING: CHORDENTIAL_STORAGE={st['requested']} was requested "
                f"but the bucket is not fully configured — falling back to the LOCAL disk "
                f"at {upload_dir()}. Uploads are NOT durable.")
    if st["durable"]:
        return "[storage] object storage active — uploads are durable."
    conn = db.connect()
    try:
        cap = mirror_cap(conn)
        kind = "Postgres" if db.is_postgres(conn) else "SQLite"
    finally:
        conn.close()
    if cap <= 0:
        return (f"[storage] WARNING: local disk at {upload_dir()} and the database mirror "
                f"is DISABLED ({MIRROR_MB_ENV}=0) — no upload survives a deploy.")
    # THE MIRROR IS ONLY AS DURABLE AS THE DATABASE HOLDING IT. This said "files at or
    # under N MB survive a deploy" whatever the database was — and a SQLite file inside
    # the container is wiped by the same rebuild that wipes the uploads. So the sentence
    # was FALSE in exactly the configuration where someone would lean on it, and a fresh
    # upload could vanish between being made and being packaged (operator, 2026-08-22:
    # *"not even the fresh 2 new ones i just pushed through"*).
    if kind == "SQLite" and not db.sqlite_is_durable():
        return (f"[storage] WARNING: local disk at {upload_dir()}, mirrored into a SQLite "
                f"file at {db.sqlite_path()} — which is on the SAME disk. NOTHING here "
                f"survives a deploy. Point CHORDENTIAL_DB at Postgres (or a persistent "
                f"path), or set CHORDENTIAL_STORAGE=s3.")
    return (f"[storage] local disk at {upload_dir()}, mirrored into {kind} up to "
            f"{cap // 1048576} MB — files at or under that survive a deploy, larger ones "
            f"do NOT. Raise {MIRROR_MB_ENV} or set CHORDENTIAL_STORAGE=s3.")


def storage_warning() -> str:
    """One sentence for a SURFACE when uploads will not survive a deploy ("" when they
    will). The boot line says this once, into a log nobody reads while testing."""
    st = storage_status(upload_dir())
    if st["durable"]:
        return ""
    conn = db.connect()
    try:
        cap = mirror_cap(conn)
        pg = db.is_postgres(conn)
    finally:
        conn.close()
    if cap <= 0:
        return ("Uploads are not backed up on this instance — the database mirror is "
                "switched off, so nothing here survives a deploy.")
    if not pg and not db.sqlite_is_durable():
        return ("Uploads are not backed up on this instance: the mirror is a SQLite file "
                "on the same disk as the uploads, so a deploy replaces BOTH. A file can "
                "be uploaded, approved and packaged in one sitting and be gone from the "
                "next. Point CHORDENTIAL_DB at Postgres, or set CHORDENTIAL_STORAGE=s3.")
    return ""


def media_present(conn, name: str) -> bool:
    """Is there ANYTHING behind ``/uploads/<name>``?

    Asked of both places `serve_upload` answers from — the object store and the durable
    DB mirror. Asking only the store reports a file as lost while it is still serving
    (the mirror is what keeps a published take playable across a redeploy that wiped the
    disk); asking neither is how a lane ends up listing a link to an empty container,
    which is the state reported live on 2026-08-20: *"they are links to an empty
    container … i need a way to delete these useless links"*.

    A missing file is a fact about the SERVER, not about the record — so this reports it
    and nothing here deletes anything. What to do about it is the operator's call.
    """
    key = os.path.basename((name or "").strip())
    if not key:
        return False
    if get_object_store(upload_dir()).exists(key):
        return True
    return db.media_blob_exists(conn, key)


def media_durable(conn, name: str) -> bool:
    """Will the bytes behind ``/uploads/<name>`` survive this container being replaced?

    The companion to :func:`media_present`, and MEASURED for the same reason: a flag
    stamped at upload time records what was true that day, and the answer moves — the
    mirror ceiling can be raised, a bucket can be configured, a migration can run. A
    surface that warns "this will be lost" must be reading the state of the world now,
    or it will eventually warn about a file that is fine and stay silent about one that
    is not.

    Present-but-not-durable is the interesting state: the file downloads perfectly
    today and is gone after the next deploy. That is precisely the window in which
    telling someone is still useful.
    """
    key = os.path.basename((name or "").strip())
    if not key:
        return False
    store = get_object_store(upload_dir())
    if bool(getattr(store, "durable", False)):
        return bool(store.exists(key))
    # No bucket: the DATABASE is the durable store, so the mirror row is the answer.
    return db.media_blob_exists(conn, key)


def rehydrate_media(conn, name: str) -> bool:
    """Put a file back on the LOCAL DISK from wherever it actually survives.

    The packager resolves assets with ``os.path.isfile`` — the disk and nothing else —
    so a file living only in the durable DB mirror reads to it as gone, and the ZIP it
    builds holds documents and no audio. That is precisely the state a deploy leaves
    behind, and it is what produced *"17 of 17 files could not be put in the package —
    the audio is not on the server"* on a project whose files were all still there
    (operator, 2026-08-22). Two surfaces were asking two different questions about the
    same seventeen files: ``media_present`` asks both places, the packager asked one.

    Rather than teach the packager about the database — it is the engine layer and has no
    connection — the bytes are restored before it runs, which also repairs the disk copy
    for every later read. Same move ``serve_upload`` already makes on a cache miss.

    Returns True when the file is on disk afterwards.
    """
    key = os.path.basename((name or "").strip())
    if not key:
        return False
    store = get_object_store(upload_dir())
    try:
        if store.local_path(key):
            return True                     # already there; nothing to do
    except Exception:                       # noqa: BLE001 — a probe may never raise
        pass
    blob = db.get_media_blob(conn, key)
    if blob is None:
        return False                        # genuinely gone from both places
    data, ctype = blob
    try:
        store.put(key, data, ctype or "")
    except Exception:                       # noqa: BLE001 — best-effort, like every seam
        return False
    try:
        return bool(store.local_path(key))
    except Exception:                       # noqa: BLE001
        return False


def forget_media(conn, name: str) -> None:
    """Remove an upload from BOTH copies. The one door out, mirroring
    ``_persist_upload`` as the one door in — deleting the file off the disk while the
    mirror still holds it leaves a link that works for reasons nobody remembers."""
    key = os.path.basename((name or "").strip())
    if not key:
        return
    try:
        get_object_store(upload_dir()).delete(key)
    except Exception:                       # noqa: BLE001 — best-effort, like every seam
        pass
    db.delete_media_blob(conn, key)


async def _read_capped(file: UploadFile, cap: int) -> Optional[bytes]:
    """Read an upload in chunks up to ``cap`` bytes; None if it exceeds the cap
    (never buffer an unbounded body — Phase-2 review P1-3)."""
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
