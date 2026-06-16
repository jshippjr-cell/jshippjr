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
from ..models import MusicDiscipline, Opportunity
from ..sources import AVAILABLE_SOURCES
from ..talent import InviteStatus, ReviewStatus, Talent
from . import db

# A small starter roster so the supply side isn't empty on first run, and so the
# matcher (next cycle) has real profiles to rank. Mix of disciplines, review
# states, and funnel stages.
_TALENT_SEED = [
    Talent(
        name="Maya Okafor", email="maya@okaforsound.com",
        disciplines=[MusicDiscipline.COMPOSITION, MusicDiscipline.ARRANGEMENT],
        credits="Composer on 2 national auto spots; orchestral arranger for a Netflix doc.",
        location="Los Angeles, CA", demo_reel_url="https://example.com/reels/maya-okafor",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED,
    ),
    Talent(
        name="Devin Park", email="devin@parkaudio.io",
        disciplines=[MusicDiscipline.SOUND_DESIGN, MusicDiscipline.COMPOSITION],
        credits="Sound designer for indie games; hybrid score for a brand campaign.",
        location="Brooklyn, NY", demo_reel_url="https://example.com/reels/devin-park",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.INVITED,
    ),
    Talent(
        name="Sofia Marin", email="sofia@marinmusic.com",
        disciplines=[MusicDiscipline.SONIC_BRANDING, MusicDiscipline.COMPOSITION],
        credits="Sonic logo for a fintech launch; mnemonic system for a retail brand.",
        location="Austin, TX", demo_reel_url="https://example.com/reels/sofia-marin",
        review_status=ReviewStatus.PENDING, invite_status=InviteStatus.PROSPECT,
    ),
    Talent(
        name="Theo Nguyen",
        disciplines=[MusicDiscipline.SUPERVISION],
        credits="Music supervisor; cleared sync for branded content and trailers.",
        location="Remote", review_status=ReviewStatus.PENDING,
        invite_status=InviteStatus.PROSPECT,
    ),
]

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


def seed_talent(conn: sqlite3.Connection) -> int:
    """Populate the starter talent roster if it's empty. Returns the number added."""
    db.init_db(conn)
    if db.talent_count(conn) > 0:
        return 0
    for t in _TALENT_SEED:
        db.insert_talent(conn, t)
    return len(_TALENT_SEED)


def reset_and_seed(db_path: str = db.DEFAULT_DB_PATH) -> int:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = db.connect(db_path)
    try:
        return seed(conn)
    finally:
        conn.close()
