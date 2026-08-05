"""Moving existing client media onto the configured object store.

The logic lives here rather than in `scripts/` so that the operator has a door that is
not a terminal. `scripts/migrate_uploads_to_object_store.py` is a thin CLI over these
functions, and the admin console calls the same ones — one implementation, so a button
press and a shell command cannot drift into doing different things.

Two sources are read, because neither alone is complete:

* the **upload directory** — every file on the disk;
* the **`media_blob` mirror** — the durable copy of anything under the mirror cap. After
  a redeploy wiped the ephemeral disk, some keys exist ONLY here, and a directory-only
  copy would silently leave them behind.

Every object is verified by reading it back and comparing SHA-256. `put()` returning
True is not evidence — the day this matters is the day the disk is removed.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os

from . import get_object_store, storage_status


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_sources(conn, root: str) -> dict:
    """``{key: bytes}`` from the disk and the mirror, plus what came from where."""
    disk = {}
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    disk[name] = fh.read()
    mirror = {}
    try:
        from ..web import db

        rows = conn.execute("SELECT name FROM media_blob").fetchall()
        for r in rows:
            key = r["name"] if hasattr(r, "keys") else r[0]
            blob = db.get_media_blob(conn, key)
            if blob is not None:
                mirror[key] = blob[0]
    except Exception:                       # noqa: BLE001 — no mirror table is fine
        mirror = {}
    return {"disk": disk, "mirror": mirror}


def inventory(conn, root: str = "") -> dict:
    """What a migration would move, without moving anything."""
    root = root or ""
    src = read_sources(conn, root)
    disk, mirror = src["disk"], src["mirror"]
    keys = sorted(set(disk) | set(mirror))
    return {
        "root": root,
        "on_disk": len(disk),
        "in_mirror": len(mirror),
        "total_keys": len(keys),
        "mirror_only": sorted(set(mirror) - set(disk)),
        "bytes": sum(len(disk.get(k) or mirror.get(k) or b"") for k in keys),
    }


def verify_round_trip(root: str = "") -> dict:
    """Put, read back and delete one throwaway object.

    `durable=True` only says credentials and the SDK are present — nothing in that check
    makes a network call, and a dry run cannot catch a bad credential either (a failed
    `get()` returns None, indistinguishable from "not uploaded yet"). This fails on one
    object instead of after attempting the whole library.
    """
    store = get_object_store(root)
    key, body = "_chordential-probe-delete-me.txt", b"chordential round trip"
    put_ok = bool(store.put(key, body, "text/plain"))
    back = store.get(key)
    read_ok = back == body
    del_ok = bool(store.delete(key))
    return {"put": put_ok, "read_back": read_ok, "cleaned_up": del_ok,
            "ok": bool(read_ok and del_ok)}


def migrate(conn, root: str = "", *, dry_run: bool = False) -> dict:
    """Copy every key onto the configured store, verifying each by SHA-256 read-back.

    Idempotent: a key already present with a matching digest is skipped, so this is safe
    to re-run after fixing whatever failed. Refuses outright unless the active store is
    durable — copying onto the disk we are about to remove is not a migration.
    """
    root = root or ""
    status = storage_status(root)
    if not status["durable"]:
        return {"ok": False, "refused": True, "status": status,
                "reason": ("the active store is the local disk (or a half-configured "
                           "bucket that fell back to it) — set CHORDENTIAL_STORAGE=s3 "
                           "and the four CHORDENTIAL_S3_* vars first"),
                "moved": 0, "skipped": 0, "failed": 0, "results": []}

    src = read_sources(conn, root)
    disk, mirror = src["disk"], src["mirror"]
    store = get_object_store(root)
    results, moved, skipped, failed = [], 0, 0, 0

    for key in sorted(set(disk) | set(mirror)):
        data = disk.get(key) or mirror.get(key) or b""
        want = _sha(data)
        source = "disk" if key in disk else "mirror-only"
        existing = store.get(key)
        if existing is not None and _sha(existing) == want:
            results.append({"key": key, "bytes": len(data), "source": source,
                            "state": "skipped"})
            skipped += 1
            continue
        if dry_run:
            results.append({"key": key, "bytes": len(data), "source": source,
                            "state": "would-move"})
            moved += 1
            continue
        store.put(key, data, mimetypes.guess_type(key)[0] or "application/octet-stream")
        back = store.get(key)               # verify by read-back, not by the return value
        if back is None or _sha(back) != want:
            results.append({"key": key, "bytes": len(data), "source": source,
                            "state": "FAILED"})
            failed += 1
        else:
            results.append({"key": key, "bytes": len(data), "source": source,
                            "state": "moved", "sha": want[:12]})
            moved += 1

    return {"ok": failed == 0, "refused": False, "dry_run": dry_run, "status": status,
            "moved": moved, "skipped": skipped, "failed": failed, "results": results,
            "mirror_only": sorted(set(mirror) - set(disk))}


def audit_referenced_media(conn, root: str = "") -> dict:
    """Every media key the DATABASE references, and whether the bytes actually exist.

    The inventory above answers "what is on this machine". This answers the question the
    operator actually has when a client presses play and hears nothing: *the portal is
    asking for a file — is it there?* A version row can happily reference a key that no
    store holds, and until you play it, nothing says so.
    """
    from ..web import db

    store = get_object_store(root)
    rows, missing = [], 0
    for prow in conn.execute("SELECT id, client, need FROM projects ORDER BY id").fetchall():
        pid = prow["id"] if hasattr(prow, "keys") else prow[0]
        delivery = db.get_delivery(conn, pid) or {}
        refs = []
        for v in (delivery.get("versions") or []):
            refs.append(("version " + str(v.get("n") or "?"), v.get("filename") or ""))
        pv = delivery.get("pending_version") or {}
        if pv.get("filename"):
            refs.append(("pending", pv["filename"]))
        for a in (delivery.get("assets") or []):
            if a.get("filename"):
                refs.append((a.get("label") or "asset", a["filename"]))
        pic = delivery.get("picture") or {}
        if pic.get("filename"):
            refs.append(("picture", pic["filename"]))
        zp = delivery.get("delivery_zip") or {}
        if zp.get("filename"):
            refs.append(("delivery zip", zp["filename"]))
        for what, filename in refs:
            key = os.path.basename(filename)
            if not key:
                continue
            in_store = bool(store.exists(key))
            in_mirror = db.get_media_blob(conn, key) is not None
            if not in_store and not in_mirror:
                missing += 1
            rows.append({
                "project_id": pid,
                "project": (prow["need"] if hasattr(prow, "keys") else prow[2]) or "",
                "what": what, "key": key,
                "in_store": in_store, "in_mirror": in_mirror,
                "ok": in_store or in_mirror,
            })
    return {"rows": rows, "missing": missing, "checked": len(rows)}


__all__ = ["inventory", "migrate", "verify_round_trip", "read_sources",
           "audit_referenced_media"]
