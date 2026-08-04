"""One-time data migration: copy a live SQLite database into Postgres.

Run once at cutover (after the new code is deployed and a Render Postgres exists):

    python scripts/migrate_sqlite_to_postgres.py /path/to/chordential.db \
           postgresql://USER:PASS@HOST/DB

It (1) creates the schema on Postgres via the app's own ``init_db`` (so the
schema always matches the code), (2) copies every table row-for-row preserving
ids, (3) resets each id sequence, and (4) verifies row counts match. The schema
has no formal foreign-key constraints, so table order doesn't matter.
"""
import sqlite3
import sys

import psycopg

from chordential_oia.web import db


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__); return 2
    src_path, pg_url = sys.argv[1], sys.argv[2]
    pg_url = pg_url.replace("postgres://", "postgresql://", 1)

    # 1) Build the schema on Postgres from the code (guaranteed in sync).
    schema_conn = db.connect(pg_url)
    db.init_db(schema_conn)
    schema_conn.commit()
    schema_conn.close()

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]

    dst = psycopg.connect(pg_url, autocommit=False)
    counts = {}
    with dst.cursor() as cur:
        for t in tables:
            rows = src.execute(f"SELECT * FROM {t}").fetchall()
            counts[t] = (len(rows), None)
            if not rows:
                continue
            cols = rows[0].keys()
            collist = ", ".join(f'"{c}"' for c in cols)
            ph = ", ".join(["%s"] * len(cols))
            cur.executemany(f'INSERT INTO "{t}" ({collist}) VALUES ({ph})',
                            [tuple(r) for r in rows])
            # Reset the id sequence so future inserts don't collide with copied ids.
            # ADR-0045: only for tables that HAVE an id. `media_blob` is keyed by
            # `name` (it holds the DB mirror of every uploaded master), and asking
            # Postgres for its id sequence raises UndefinedColumn — which crashed
            # this script mid-copy, after some tables were already written, on the
            # production data, during the cutover. Found by running it for real.
            if "id" in cols:
                cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (t,))
                seq = cur.fetchone()[0]
                if seq:
                    cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM \"{t}\"), 1))", (seq,))
    dst.commit()

    # 4) Verify counts match.
    ok = True
    with dst.cursor() as cur:
        for t in tables:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            got = cur.fetchone()[0]
            want = counts[t][0]
            mark = "ok " if got == want else "MISMATCH"
            if got != want:
                ok = False
            print(f"  {mark} {t}: sqlite={want} postgres={got}")
    dst.close()
    src.close()
    print("\nMigration", "complete." if ok else "had MISMATCHES — investigate.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
