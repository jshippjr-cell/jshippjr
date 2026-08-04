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

from ..storage import get_object_store
from . import db

_HERE = os.path.dirname(__file__)


def upload_dir() -> str:
    """The directory the local object store writes to. Resolved per call — see above."""
    return os.environ.get("CHORDENTIAL_UPLOAD_DIR") or os.path.join(_HERE, "uploads")


# Audio uploads we accept for relevant-work samples.
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


_CUT_MIRROR_BYTES = int(os.environ.get("CHORDENTIAL_CUT_MIRROR_MB", "64")) * 1024 * 1024


def _persist_upload(conn, name: str, data: bytes, content_type: str = "",
                    mirror: bool = True) -> None:
    """THE place client media is written (ADR-0043). Every upload route goes through
    here; none may open a file under ``upload_dir()`` itself.

    Bytes go to the configured object store — the local disk by default, an
    S3-compatible bucket when ``CHORDENTIAL_STORAGE=s3``. The SQLite mirror is the
    net under a store that ISN'T durable, so it is written only then: with a real
    bucket configured, mirroring would double every master into the database for no
    benefit, and the Postgres cutover is partly motivated by that bloat.

    ``mirror=False`` is the VIDEO policy (ADR-0026): cuts above the threshold skip
    the mirror even on local, because a feature-length cut in SQLite is worse than
    the risk it covers. The client door says so honestly.

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
    store.put(key, data, content_type)
    if not mirror or getattr(store, "durable", False):
        return
    db.save_media_blob(conn, key, data, content_type)


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
    # ADR-0026: disk always; DB mirror only under threshold (a large take must not
    # blob into SQLite).
    _persist_upload(conn, safe_name, data, mirror=len(data) <= _CUT_MIRROR_BYTES)
    db.update_delivery(conn, project_id, "pending_version", {
        "url": f"/uploads/{safe_name}",
        "filename": safe_name,
        "orig": src_filename or "",
        "by": who or "A creator",
        "at": _dt.now(_tz.utc).isoformat(),
    })


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
