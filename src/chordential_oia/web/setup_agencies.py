"""The agencies recovered from the directory pages pasted during setup, parsed
with the real per-source parsers and de-duplicated. Committed as data so the
live app can populate the Master Company Database with one click — no re-paste.

This is real public directory data (AdForum, Awwwards, Cannes Lions / lovethework,
DesignRush, The Drum), not demo/invented brands, so it loads as real data rather
than behind the CHORDENTIAL_SEED_DEMO gate.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from . import db

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "setup_agencies.json")


def _load_json() -> List[Dict]:
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


SETUP_AGENCIES: List[Dict] = _load_json()


def setup_count() -> int:
    """How many recovered agencies are available to import."""
    return len(SETUP_AGENCIES)


def load(conn) -> Dict:
    """Upsert every recovered agency into the Master Company Database. Idempotent:
    rows are collapsed on (source, dedup_key), so re-importing refreshes rather
    than duplicates. Returns {total, new}."""
    new = 0
    for rec in SETUP_AGENCIES:
        source = rec.get("source") or "manual"
        if db.upsert_agency(conn, source, rec):
            new += 1
    conn.commit()
    return {"total": len(SETUP_AGENCIES), "new": new}
