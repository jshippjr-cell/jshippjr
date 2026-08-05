"""One-time media migration: copy client media onto the configured object store.

A thin CLI over :mod:`chordential_oia.storage.migrate`. The admin console
(`/settings/storage`) calls the same functions, so a button press and a shell command
cannot drift into doing different things — which matters, because the console exists
precisely for the times the shell will not connect.

Run this BEFORE the Postgres cutover removes the Render disk. Postgres does not carry
uploads: `/var/data/uploads` holds every client picture cut, master, stem and built
delivery ZIP, and files above the mirror cap have no second copy anywhere.

    python scripts/migrate_uploads_to_object_store.py --check      # round-trip one object
    python scripts/migrate_uploads_to_object_store.py --dry-run    # report; write nothing
    python scripts/migrate_uploads_to_object_store.py              # do it

Every object is verified by reading it back and comparing SHA-256; a key that cannot be
read back is reported and the script exits non-zero. Idempotent — an object already
present with a matching digest is skipped, so it is safe to re-run.
"""
from __future__ import annotations

import argparse
import sys

from chordential_oia.storage import storage_status
from chordential_oia.storage.migrate import inventory, migrate, verify_round_trip
from chordential_oia.web import db
from chordential_oia.web.uploads import upload_dir


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would move; write nothing")
    ap.add_argument("--check", action="store_true",
                    help="round-trip one throwaway object and exit")
    ap.add_argument("--dir", default="", help="upload directory (default: the configured one)")
    args = ap.parse_args()

    root = args.dir or upload_dir()
    st = storage_status(root)
    print(f"[storage] requested={st['requested']} active={st['active']} "
          f"durable={st['durable']}")

    if args.check:
        probe = verify_round_trip(root)
        for k in ("put", "read_back", "cleaned_up"):
            print(f"  {k:<11}: {probe[k]}")
        print("VERDICT: " + ("BUCKET WORKS" if probe["ok"] else "BUCKET NOT WORKING"))
        return 0 if probe["ok"] else 1

    conn = db.connect()
    try:
        inv = inventory(conn, root)
        print(f"[source] {inv['on_disk']} on disk, {inv['in_mirror']} in the mirror, "
              f"{inv['total_keys']} distinct keys")
        if inv["mirror_only"]:
            shown = inv["mirror_only"][:5]
            print(f"[source] {len(inv['mirror_only'])} exist ONLY in the mirror "
                  f"(a directory-only copy would have lost these): {shown}"
                  f"{' …' if len(inv['mirror_only']) > 5 else ''}")
        result = migrate(conn, root, dry_run=args.dry_run)
    finally:
        conn.close()

    if result["refused"]:
        print("REFUSING: " + result["reason"], file=sys.stderr)
        return 2

    for r in result["results"]:
        mark = {"moved": "ok    ", "skipped": "skip  ",
                "would-move": "WOULD ", "FAILED": "FAIL  "}[r["state"]]
        extra = f", sha {r['sha']}…" if r.get("sha") else ""
        tag = "  [mirror-only]" if r["source"] == "mirror-only" else ""
        print(f"  {mark} {r['key']}  ({r['bytes']:,} bytes{extra}){tag}")

    verb = "would move" if result["dry_run"] else "moved"
    print(f"\n{verb}={result['moved']} skipped={result['skipped']} "
          f"failed={result['failed']}")
    if result["failed"]:
        print("NOT DONE — re-run after fixing the failures above. Do not remove the disk.",
              file=sys.stderr)
        return 1
    if result["dry_run"]:
        print("dry run only — nothing was written.")
    else:
        print("Every key is readable back from the bucket with a matching digest.")
    return 0


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
