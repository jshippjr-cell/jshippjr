"""Populate the dashboard database with opportunities.

Pulls from every registered source plus any sample alert emails, de-duplicates
on (client, need), evaluates each through the engines, and stores it. Safe to
call repeatedly — existing rows are skipped.
"""

from __future__ import annotations

import os
import sqlite3
from typing import List

from ..intake import parse_email_path
from ..models import Opportunity
from ..sources import AVAILABLE_SOURCES
from . import db

_SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "samples",
)


def gather_opportunities() -> List[Opportunity]:
    opps: List[Opportunity] = []
    for cls in AVAILABLE_SOURCES.values():
        opps.extend(cls().fetch(limit=50))
    if os.path.isdir(_SAMPLES_DIR):
        try:
            opps.extend(parse_email_path(_SAMPLES_DIR))
        except Exception:
            pass
    return opps


def seed(conn: sqlite3.Connection) -> int:
    """Insert any not-yet-stored opportunities. Returns the number added."""
    db.init_db(conn)
    added = 0
    for opp in gather_opportunities():
        if not db.opportunity_exists(conn, opp.client, opp.need):
            db.insert_opportunity(conn, opp)
            added += 1
    return added


def reset_and_seed(db_path: str = db.DEFAULT_DB_PATH) -> int:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = db.connect(db_path)
    try:
        return seed(conn)
    finally:
        conn.close()
