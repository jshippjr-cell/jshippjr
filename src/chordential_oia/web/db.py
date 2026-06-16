"""SQLite persistence for the dashboard.

Opportunities are stored with both their raw facts and a cached evaluation
(qualification + score) so the inbox/lanes can filter and sort in SQL. The
cache is always produced by the existing engines (:mod:`evaluate`) — there is no
separate scoring logic here, per the build constraint. Detail pages reconstruct
the :class:`Opportunity` and re-run the engines for the full breakdown.

SQLite (stdlib) keeps the app self-contained and runnable with no external
service; the schema maps cleanly onto Postgres/Supabase later.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models import BuyerType, MusicRequirement, Opportunity
from .evaluate import evaluate

DEFAULT_DB_PATH = os.environ.get("CHORDENTIAL_DB", "chordential.db")

# Human-managed pipeline states (distinct from the engine's qualification action).
PIPELINE_STATES = ["New", "Pursuing", "Submitted", "Won", "Lost", "Passed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    need TEXT NOT NULL,
    description TEXT DEFAULT '',
    source TEXT DEFAULT 'unknown',
    source_tier INTEGER,
    url TEXT,
    buyer_type TEXT,
    music_requirement TEXT,
    budget_min REAL,
    budget_max REAL,
    location TEXT,
    tags TEXT,
    created_at TEXT,
    -- evaluation cache (always from the engines)
    qualified INTEGER,
    discipline TEXT,
    alignment REAL,
    action TEXT,
    confidence TEXT,
    needs_review INTEGER,
    score REAL,
    tier TEXT,
    win_probability TEXT,
    -- human pipeline
    status TEXT DEFAULT 'New',
    outcome_value REAL,
    notes TEXT DEFAULT ''
);
"""


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# Mapping between Opportunity <-> row
# --------------------------------------------------------------------------- #
def _enum(value, enum_cls, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def opportunity_from_row(row: sqlite3.Row) -> Opportunity:
    return Opportunity(
        client=row["client"],
        need=row["need"],
        description=row["description"] or "",
        source=row["source"] or "unknown",
        source_tier=row["source_tier"],
        url=row["url"],
        buyer_type=_enum(row["buyer_type"], BuyerType, BuyerType.UNKNOWN),
        music_requirement=_enum(
            row["music_requirement"], MusicRequirement, MusicRequirement.IMPLIED
        ),
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        location=row["location"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
    )


def insert_opportunity(conn: sqlite3.Connection, opp: Opportunity) -> int:
    """Evaluate (qualify + score) and store. Returns the new row id."""
    q, s = evaluate(opp)
    cur = conn.execute(
        """
        INSERT INTO opportunities (
            client, need, description, source, source_tier, url, buyer_type,
            music_requirement, budget_min, budget_max, location, tags, created_at,
            qualified, discipline, alignment, action, confidence, needs_review,
            score, tier, win_probability, status, outcome_value, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            opp.client, opp.need, opp.description, opp.source, opp.source_tier,
            opp.url, opp.buyer_type.value, opp.music_requirement.value,
            opp.budget_min, opp.budget_max, opp.location, json.dumps(opp.tags),
            datetime.now(timezone.utc).isoformat(),
            int(q.qualified), q.discipline.value, q.alignment_pct,
            q.recommended_action.value, q.confidence.value, int(q.needs_human_review),
            s.score, s.tier.value, s.win_probability.value,
            "Passed" if not q.qualified else "New", None, "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def opportunity_exists(conn: sqlite3.Connection, client: str, need: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM opportunities WHERE client=? AND need=? LIMIT 1",
        (client, need),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def list_opportunities(
    conn: sqlite3.Connection,
    q: Optional[str] = None,
    action: Optional[str] = None,
    tier: Optional[str] = None,
    discipline: Optional[str] = None,
    buyer_type: Optional[str] = None,
    status: Optional[str] = None,
    min_alignment: Optional[float] = None,
    order_by: str = "alignment",
) -> List[sqlite3.Row]:
    clauses: List[str] = []
    params: List = []
    if q:
        clauses.append("(client LIKE ? OR need LIKE ? OR description LIKE ? OR location LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if action:
        clauses.append("action = ?")
        params.append(action)
    if tier:
        clauses.append("tier = ?")
        params.append(tier)
    if discipline:
        clauses.append("discipline = ?")
        params.append(discipline)
    if buyer_type:
        clauses.append("buyer_type = ?")
        params.append(buyer_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if min_alignment is not None:
        clauses.append("alignment >= ?")
        params.append(min_alignment)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order_cols = {
        "alignment": "alignment DESC",
        "score": "score DESC",
        "budget": "COALESCE(budget_max, budget_min, 0) DESC",
        "client": "client ASC",
        "created": "created_at DESC",
    }
    order = order_cols.get(order_by, "alignment DESC")
    sql = f"SELECT * FROM opportunities{where} ORDER BY {order}"
    return conn.execute(sql, params).fetchall()


def get_opportunity(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
    ).fetchone()


def update_status(
    conn: sqlite3.Connection,
    opp_id: int,
    status: str,
    outcome_value: Optional[float] = None,
) -> None:
    if status not in PIPELINE_STATES:
        raise ValueError(f"Unknown status {status!r}")
    conn.execute(
        "UPDATE opportunities SET status = ?, outcome_value = ? WHERE id = ?",
        (status, outcome_value, opp_id),
    )
    conn.commit()


def update_notes(conn: sqlite3.Connection, opp_id: int, notes: str) -> None:
    conn.execute("UPDATE opportunities SET notes = ? WHERE id = ?", (notes, opp_id))
    conn.commit()


def buyer_opportunities(conn: sqlite3.Connection, client: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities WHERE client = ? ORDER BY created_at DESC",
        (client,),
    ).fetchall()


def distinct_values(conn: sqlite3.Connection, column: str) -> List[str]:
    allowed = {"action", "tier", "discipline", "buyer_type", "status"}
    if column not in allowed:
        raise ValueError(column)
    rows = conn.execute(
        f"SELECT DISTINCT {column} AS v FROM opportunities WHERE {column} IS NOT NULL ORDER BY v"
    ).fetchall()
    return [r["v"] for r in rows]


def lane_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT action, COUNT(*) AS n FROM opportunities GROUP BY action"
    ).fetchall()
    return {r["action"]: r["n"] for r in rows}


def exec_metrics(conn: sqlite3.Connection) -> Dict:
    """Aggregate numbers for the executive summary dashboard."""
    def scalar(sql: str, params=()) -> float:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else 0

    total = scalar("SELECT COUNT(*) FROM opportunities")
    qualified = scalar("SELECT COUNT(*) FROM opportunities WHERE qualified = 1")
    pursue = scalar("SELECT COUNT(*) FROM opportunities WHERE action = 'Pursue'")
    review = scalar("SELECT COUNT(*) FROM opportunities WHERE action = 'Review'")
    won = scalar("SELECT COUNT(*) FROM opportunities WHERE status = 'Won'")
    lost = scalar("SELECT COUNT(*) FROM opportunities WHERE status = 'Lost'")
    pursuing = scalar(
        "SELECT COUNT(*) FROM opportunities WHERE status IN ('Pursuing','Submitted')"
    )
    won_value = scalar("SELECT SUM(outcome_value) FROM opportunities WHERE status = 'Won'")
    pipeline_value = scalar(
        """SELECT SUM(COALESCE(budget_max, budget_min, 0))
           FROM opportunities WHERE status IN ('Pursuing','Submitted')"""
    )
    decided = won + lost
    win_rate = (won / decided * 100.0) if decided else 0.0
    avg_alignment = scalar("SELECT AVG(alignment) FROM opportunities WHERE qualified = 1")

    by_discipline = conn.execute(
        """SELECT discipline, COUNT(*) AS n FROM opportunities
           WHERE qualified = 1 GROUP BY discipline ORDER BY n DESC"""
    ).fetchall()

    return {
        "total": int(total),
        "qualified": int(qualified),
        "pursue": int(pursue),
        "review": int(review),
        "won": int(won),
        "lost": int(lost),
        "pursuing": int(pursuing),
        "won_value": won_value,
        "pipeline_value": pipeline_value,
        "win_rate": win_rate,
        "avg_alignment": avg_alignment,
        "by_discipline": [(r["discipline"], r["n"]) for r in by_discipline],
    }
