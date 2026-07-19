"""Print every demo door for a Chordential DB: composer rooms + client portals.

Usage: python tokens.py <db-path> [base-url]
Ensures tokens exist (they're minted lazily) before printing.
"""
import os
import sys

os.environ["CHORDENTIAL_DB"] = sys.argv[1]
BASE = sys.argv[2] if len(sys.argv) > 2 else ""

from chordential_oia.web import db  # noqa: E402  (env must be set first)

conn = db.connect()
try:
    composers = conn.execute(
        "SELECT DISTINCT t.id, t.name FROM talent t "
        "JOIN assignments a ON a.talent_id = t.id ORDER BY t.id"
    ).fetchall()
    for row in composers:
        tok = db.ensure_talent_portal_token(conn, row["id"])
        print(f"composer  {row['name']:<28} {BASE}/creator/{tok}")
    projects = conn.execute(
        "SELECT id, client, need FROM projects ORDER BY id"
    ).fetchall()
    for p in projects:
        tok = db.ensure_project_share_token(conn, p["id"])
        print(
            f"client    project {p['id']} ({p['client']}) "
            f"{BASE}/project/{p['id']}/delivery-portal?k={tok}"
        )
    conn.commit()
finally:
    conn.close()
