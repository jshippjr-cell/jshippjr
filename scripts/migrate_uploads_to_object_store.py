"""One-time media migration: copy client media onto the configured object store.

Run this BEFORE the Postgres cutover removes the Render disk. Postgres does not carry
uploads — `/var/data/uploads` holds every client picture cut, master, stem and built
delivery ZIP, and files above the mirror cap have no second copy anywhere.

    # on the Render shell, with the bucket vars already set in the dashboard
    python scripts/migrate_uploads_to_object_store.py --dry-run
    python scripts/migrate_uploads_to_object_store.py

Two sources are read, because neither alone is complete:

* **the upload directory** — every file on the disk;
* **the SQLite/Postgres `media_blob` mirror** — the durable copy of anything under the
  mirror cap. After a redeploy wiped the ephemeral disk, some keys exist ONLY here, and
  a directory-only copy would leave them behind.

Every object is verified by reading it back and comparing SHA-256. A key that cannot be
read back is reported and the script exits non-zero: "the copy finished" and "the bytes
are there" are different claims, and only the second one matters the day the disk goes.

Idempotent — an object already present with a matching digest is skipped, so it is safe
to re-run after fixing whatever failed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys

from chordential_oia.storage import get_object_store, storage_status
from chordential_oia.web import db
from chordential_oia.web.uploads import upload_dir


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _from_disk(root: str) -> dict:
    """key -> bytes, for every regular file directly under the upload directory."""
    out = {}
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            out[name] = fh.read()
    return out


def _from_mirror(conn) -> dict:
    """key -> bytes, for every row in the durable blob mirror."""
    out = {}
    try:
        rows = conn.execute("SELECT name FROM media_blob").fetchall()
    except Exception:                       # noqa: BLE001 — no mirror table is fine
        return out
    for r in rows:
        key = r[0] if not hasattr(r, "keys") else r["name"]
        blob = db.get_media_blob(conn, key)
        if blob is not None:
            out[key] = blob[0]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would move; write nothing")
    ap.add_argument("--dir", default="", help="upload directory (default: the configured one)")
    args = ap.parse_args()

    root = args.dir or upload_dir()
    status = storage_status(root)
    print(f"[storage] requested={status['requested']} active={status['active']} "
          f"durable={status['durable']}")
    if not status["durable"]:
        print("REFUSING: the configured store is the local disk (or a half-configured\n"
              "         bucket that fell back to it). Set CHORDENTIAL_STORAGE=s3 and the\n"
              "         four CHORDENTIAL_S3_* vars first — including the s3 extra in the\n"
              "         build, or the store reports durable and cannot write a byte.",
              file=sys.stderr)
        return 2

    conn = db.connect()
    try:
        disk, mirror = _from_disk(root), _from_mirror(conn)
    finally:
        conn.close()

    keys = sorted(set(disk) | set(mirror))
    print(f"[source] {len(disk)} on disk, {len(mirror)} in the mirror, "
          f"{len(keys)} distinct keys")
    only_mirror = sorted(set(mirror) - set(disk))
    if only_mirror:
        print(f"[source] {len(only_mirror)} exist ONLY in the mirror "
              f"(a directory-only copy would have lost these): {only_mirror[:5]}"
              f"{' …' if len(only_mirror) > 5 else ''}")

    store = get_object_store(root)
    moved = skipped = failed = 0
    for key in keys:
        data = disk.get(key) or mirror.get(key) or b""
        want = _sha(data)
        existing = store.get(key)
        if existing is not None and _sha(existing) == want:
            print(f"  skip   {key}  (already present, digest matches)")
            skipped += 1
            continue
        if args.dry_run:
            print(f"  WOULD  {key}  ({len(data):,} bytes)")
            moved += 1
            continue
        import mimetypes
        store.put(key, data, mimetypes.guess_type(key)[0] or "application/octet-stream")
        back = store.get(key)                       # verify by read-back, not by return value
        if back is None or _sha(back) != want:
            print(f"  FAIL   {key}  — not readable back with a matching digest")
            failed += 1
        else:
            print(f"  ok     {key}  ({len(data):,} bytes, sha {want[:12]}…)")
            moved += 1

    verb = "would move" if args.dry_run else "moved"
    print(f"\n{verb}={moved} skipped={skipped} failed={failed}")
    if failed:
        print("NOT DONE — re-run after fixing the failures above. Do not remove the disk.",
              file=sys.stderr)
        return 1
    if args.dry_run:
        print("dry run only — nothing was written.")
    else:
        print("Every key is readable back from the bucket with a matching digest.")
    return 0


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
