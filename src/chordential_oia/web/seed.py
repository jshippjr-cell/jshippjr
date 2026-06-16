"""Populate the dashboard database with opportunities.

Pulls from every registered source plus any sample alert emails, de-duplicates
on (client, need), evaluates each through the engines, and stores it. Safe to
call repeatedly — existing rows are skipped.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from typing import List

from ..estimation import build_estimate
from ..intake import parse_email_path
from ..models import MusicDiscipline, Opportunity
from ..sources import AVAILABLE_SOURCES
from ..talent import InviteStatus, ReviewStatus, Talent
from . import db
from .evaluate import evaluate

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


def _suggested_price(opp: Opportunity) -> float:
    """Suggested price via the standard engines (qualify → discipline/team → estimate)."""
    q, _ = evaluate(opp)
    return build_estimate(
        opp, q.team_shape or q.discipline.team_shape, q.discipline
    ).suggested_price


def seed_demo_pipeline(conn: sqlite3.Connection) -> bool:
    """Stage one tentative bid and one closed win so the Executive Summary's
    pipeline columns show live data on a fresh database.

    Mirrors what Jon would do by hand (submit a bid; mark a deal Won; spin up a
    project and assign approved crew) — it adds nothing the normal flow can't.
    Idempotent: a no-op once any ``Submitted``/``Won`` deal already exists.
    """
    db.init_db(conn)
    if conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE status IN ('Submitted','Won')"
    ).fetchone()[0]:
        return False
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE qualified = 1 ORDER BY alignment DESC"
    ).fetchall()
    if len(rows) < 2:
        return False
    bid_row, won_row = rows[0], rows[1]

    # 1) Tentative — a bid that's out for decision.
    bid_price = _suggested_price(db.opportunity_from_row(bid_row))
    db.update_status(conn, bid_row["id"], "Submitted", round(bid_price))
    db.update_outreach(
        conn, bid_row["id"],
        next_action="Awaiting decision on submitted bid",
        next_action_due=(date.today() + timedelta(days=5)).isoformat(),
    )

    # 2) Won — a closed deal spun up into a project with assigned crew.
    won_opp = db.opportunity_from_row(won_row)
    q, _ = evaluate(won_opp)
    won_price = build_estimate(
        won_opp, q.team_shape or q.discipline.team_shape, q.discipline
    ).suggested_price
    db.update_status(conn, won_row["id"], "Won", round(won_price))
    roles = q.team_shape or ["Composer", "Mixer"]
    pid = db.insert_project(
        conn, won_row["id"], won_row["client"], won_row["need"],
        won_row["budget_min"], won_row["budget_max"], roles,
    )
    matchable = [t for t in db.load_talent(conn) if t.matchable]
    for role, t in zip(roles, matchable):
        db.add_assignment(conn, pid, role, t.id)
    return True


def reset_and_seed(db_path: str = db.DEFAULT_DB_PATH) -> int:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = db.connect(db_path)
    try:
        return seed(conn)
    finally:
        conn.close()
