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
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from ..models import BuyerType, BuyerValue, MusicDiscipline, MusicRequirement, Opportunity
from ..strategic import assess_strategic_value
from ..talent import InviteStatus, ReviewStatus, Talent
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
    -- CMO Strategic-Value lens
    buyer_value TEXT DEFAULT 'unknown',
    marquee INTEGER DEFAULT 0,
    strategic_value REAL,
    strategic_tier TEXT,
    -- human pipeline
    status TEXT DEFAULT 'New',
    outcome_value REAL,
    notes TEXT DEFAULT '',
    -- Outreach-to-win layer
    contact_name TEXT,
    contact_email TEXT,
    contact_role TEXT,
    next_action TEXT,
    next_action_due TEXT,
    last_contacted TEXT
);

CREATE TABLE IF NOT EXISTS outreach_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id INTEGER NOT NULL,
    created_at TEXT,
    channel TEXT,
    direction TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS talent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    disciplines TEXT,            -- JSON list of MusicDiscipline values
    credits TEXT DEFAULT '',
    location TEXT,
    demo_reel_url TEXT,
    review_status TEXT DEFAULT 'Pending',
    invite_status TEXT DEFAULT 'Prospect',
    notes TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id INTEGER,
    client TEXT, need TEXT,
    budget_min REAL, budget_max REAL,
    deadline TEXT,
    status TEXT DEFAULT 'Active',
    roles TEXT,                  -- JSON list of required role names
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    role TEXT,
    talent_id INTEGER,
    created_at TEXT
);
"""

PROJECT_STATES = ["Active", "Delivered"]

# Columns added by the Outreach layer — applied to pre-existing databases via an
# idempotent migration so an older chordential.db keeps working after a pull.
_OUTREACH_COLUMNS = {
    "contact_name": "TEXT",
    "contact_email": "TEXT",
    "contact_role": "TEXT",
    "next_action": "TEXT",
    "next_action_due": "TEXT",
    "last_contacted": "TEXT",
}


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _ensure_schema(conn)
    conn.commit()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotently bring an older database up to the current schema.

    Fresh DBs already have everything from ``_SCHEMA``; this only matters for a
    ``chordential.db`` created before the Outreach layer existed — it adds the
    missing columns (and the events table) without touching existing data.
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    for name, decl in _OUTREACH_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {name} {decl}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            created_at TEXT, channel TEXT, direction TEXT, note TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS talent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT, disciplines TEXT,
            credits TEXT DEFAULT '', location TEXT, demo_reel_url TEXT,
            review_status TEXT DEFAULT 'Pending',
            invite_status TEXT DEFAULT 'Prospect',
            notes TEXT DEFAULT '', created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER, client TEXT, need TEXT,
            budget_min REAL, budget_max REAL, deadline TEXT,
            status TEXT DEFAULT 'Active', roles TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL, role TEXT, talent_id INTEGER, created_at TEXT
        )"""
    )
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
        buyer_value=_enum(row["buyer_value"], BuyerValue, BuyerValue.UNKNOWN),
        marquee=bool(row["marquee"]),
    )


def insert_opportunity(conn: sqlite3.Connection, opp: Opportunity) -> int:
    """Evaluate (qualify + score + strategic value) and store. Returns row id."""
    q, s = evaluate(opp)
    sv = assess_strategic_value(opp)
    cur = conn.execute(
        """
        INSERT INTO opportunities (
            client, need, description, source, source_tier, url, buyer_type,
            music_requirement, budget_min, budget_max, location, tags, created_at,
            qualified, discipline, alignment, action, confidence, needs_review,
            score, tier, win_probability, buyer_value, marquee, strategic_value,
            strategic_tier, status, outcome_value, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            opp.client, opp.need, opp.description, opp.source, opp.source_tier,
            opp.url, opp.buyer_type.value, opp.music_requirement.value,
            opp.budget_min, opp.budget_max, opp.location, json.dumps(opp.tags),
            datetime.now(timezone.utc).isoformat(),
            int(q.qualified), q.discipline.value, q.alignment_pct,
            q.recommended_action.value, q.confidence.value, int(q.needs_human_review),
            s.score, s.tier.value, s.win_probability.value,
            opp.buyer_value.value, int(opp.marquee), sv.score, sv.tier,
            "Passed" if not q.qualified else "New", None, "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_strategic_inputs(
    conn: sqlite3.Connection, opp_id: int, buyer_value: str, marquee: bool
) -> None:
    """Persist human-set buyer value + marquee flag and recompute strategic value."""
    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    if row is None:
        return
    opp = opportunity_from_row(row)
    opp.buyer_value = _enum(buyer_value, BuyerValue, BuyerValue.UNKNOWN)
    opp.marquee = bool(marquee)
    sv = assess_strategic_value(opp)
    conn.execute(
        """UPDATE opportunities
           SET buyer_value = ?, marquee = ?, strategic_value = ?, strategic_tier = ?
           WHERE id = ?""",
        (opp.buyer_value.value, int(opp.marquee), sv.score, sv.tier, opp_id),
    )
    conn.commit()


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
        "strategic": "strategic_value DESC",
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


# --------------------------------------------------------------------------- #
# Outreach-to-win
# --------------------------------------------------------------------------- #
def update_outreach(
    conn: sqlite3.Connection,
    opp_id: int,
    contact_name: str = "",
    contact_email: str = "",
    contact_role: str = "",
    next_action: str = "",
    next_action_due: str = "",
) -> None:
    """Persist the human-managed outreach fields (contact + the single next action)."""
    conn.execute(
        """UPDATE opportunities
           SET contact_name = ?, contact_email = ?, contact_role = ?,
               next_action = ?, next_action_due = ?
           WHERE id = ?""",
        (
            contact_name or None, contact_email or None, contact_role or None,
            next_action or None, next_action_due or None, opp_id,
        ),
    )
    conn.commit()


def add_outreach_event(
    conn: sqlite3.Connection,
    opp_id: int,
    channel: str,
    direction: str,
    note: str,
) -> None:
    """Append one logged touch and stamp ``last_contacted`` on the opportunity."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO outreach_events (opp_id, created_at, channel, direction, note)
           VALUES (?,?,?,?,?)""",
        (opp_id, now, channel, direction, note),
    )
    conn.execute(
        "UPDATE opportunities SET last_contacted = ? WHERE id = ?", (now, opp_id)
    )
    conn.commit()


def list_outreach_events(conn: sqlite3.Connection, opp_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outreach_events WHERE opp_id = ? ORDER BY created_at DESC",
        (opp_id,),
    ).fetchall()


def followups_due(conn: sqlite3.Connection, limit: int = 8) -> List[sqlite3.Row]:
    """Open opportunities whose next action is due on/before today (the follow-up queue)."""
    today = date.today().isoformat()
    return conn.execute(
        """SELECT * FROM opportunities
           WHERE next_action_due IS NOT NULL AND next_action_due != ''
             AND next_action_due <= ?
             AND status NOT IN ('Won','Lost','Passed')
           ORDER BY next_action_due ASC
           LIMIT ?""",
        (today, limit),
    ).fetchall()


def buyer_opportunities(conn: sqlite3.Connection, client: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities WHERE client = ? ORDER BY created_at DESC",
        (client,),
    ).fetchall()


def all_buyers(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """One aggregated row per buyer for the Buyer Graph directory."""
    return conn.execute(
        """
        SELECT
            o.client AS client,
            MIN(o.buyer_type) AS buyer_type,
            COUNT(*) AS opps,
            SUM(o.qualified) AS qualified,
            SUM(CASE WHEN o.status = 'Won' THEN 1 ELSE 0 END) AS won,
            SUM(CASE WHEN o.status = 'Lost' THEN 1 ELSE 0 END) AS lost,
            SUM(CASE WHEN o.status IN ('Pursuing','Submitted') THEN 1 ELSE 0 END) AS open_pursuits,
            MAX(o.strategic_value) AS strategic_value,
            AVG(o.alignment) AS avg_alignment,
            MAX(o.last_contacted) AS last_contacted,
            (SELECT COUNT(*) FROM outreach_events e
                JOIN opportunities oi ON e.opp_id = oi.id
                WHERE oi.client = o.client) AS touches
        FROM opportunities o
        GROUP BY o.client
        """
    ).fetchall()


def buyer_touch_summary(conn: sqlite3.Connection, client: str) -> sqlite3.Row:
    """Total logged outreach touches and the most recent timestamp for a buyer."""
    return conn.execute(
        """SELECT COUNT(*) AS touches, MAX(e.created_at) AS last_contacted
           FROM outreach_events e JOIN opportunities o ON e.opp_id = o.id
           WHERE o.client = ?""",
        (client,),
    ).fetchone()


def buyer_contacts(conn: sqlite3.Connection, client: str) -> List[sqlite3.Row]:
    """Distinct known contacts captured across a buyer's opportunities."""
    return conn.execute(
        """SELECT DISTINCT contact_name, contact_email, contact_role
           FROM opportunities
           WHERE client = ?
             AND (contact_name IS NOT NULL OR contact_email IS NOT NULL)
           ORDER BY contact_name""",
        (client,),
    ).fetchall()


# --------------------------------------------------------------------------- #
# Talent (supply side)
# --------------------------------------------------------------------------- #
REVIEW_STATES = [s.value for s in ReviewStatus]
INVITE_STATES = [s.value for s in InviteStatus]


def _disciplines_from_json(raw: Optional[str]) -> List[MusicDiscipline]:
    out: List[MusicDiscipline] = []
    for v in (json.loads(raw) if raw else []):
        try:
            out.append(MusicDiscipline(v))
        except ValueError:
            continue
    return out


def talent_from_row(row: sqlite3.Row) -> Talent:
    return Talent(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        disciplines=_disciplines_from_json(row["disciplines"]),
        credits=row["credits"] or "",
        location=row["location"],
        demo_reel_url=row["demo_reel_url"],
        review_status=_enum(row["review_status"], ReviewStatus, ReviewStatus.PENDING),
        invite_status=_enum(row["invite_status"], InviteStatus, InviteStatus.PROSPECT),
        notes=row["notes"] or "",
    )


def insert_talent(conn: sqlite3.Connection, t: Talent) -> int:
    cur = conn.execute(
        """INSERT INTO talent
           (name, email, disciplines, credits, location, demo_reel_url,
            review_status, invite_status, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            t.name, t.email, json.dumps([d.value for d in t.disciplines]),
            t.credits, t.location, t.demo_reel_url,
            t.review_status.value, t.invite_status.value, t.notes,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_talent(
    conn: sqlite3.Connection,
    discipline: Optional[str] = None,
    review: Optional[str] = None,
    invite: Optional[str] = None,
) -> List[sqlite3.Row]:
    clauses, params = [], []
    if discipline:
        clauses.append("disciplines LIKE ?")
        params.append(f'%"{discipline}"%')
    if review:
        clauses.append("review_status = ?")
        params.append(review)
    if invite:
        clauses.append("invite_status = ?")
        params.append(invite)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(
        f"SELECT * FROM talent{where} ORDER BY name ASC", params
    ).fetchall()


def get_talent(conn: sqlite3.Connection, talent_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM talent WHERE id = ?", (talent_id,)).fetchone()


def update_talent_review(conn: sqlite3.Connection, talent_id: int, review_status: str) -> None:
    if review_status not in REVIEW_STATES:
        raise ValueError(f"Unknown review status {review_status!r}")
    conn.execute(
        "UPDATE talent SET review_status = ? WHERE id = ?", (review_status, talent_id)
    )
    conn.commit()


def update_talent_invite(conn: sqlite3.Connection, talent_id: int, invite_status: str) -> None:
    if invite_status not in INVITE_STATES:
        raise ValueError(f"Unknown invite status {invite_status!r}")
    conn.execute(
        "UPDATE talent SET invite_status = ? WHERE id = ?", (invite_status, talent_id)
    )
    conn.commit()


def update_talent_profile(
    conn: sqlite3.Connection,
    talent_id: int,
    name: str,
    email: str,
    disciplines: List[str],
    credits: str,
    location: str,
    demo_reel_url: str,
    notes: str,
) -> None:
    valid = [d for d in disciplines if d in {m.value for m in MusicDiscipline}]
    conn.execute(
        """UPDATE talent SET name=?, email=?, disciplines=?, credits=?, location=?,
           demo_reel_url=?, notes=? WHERE id=?""",
        (
            name, email or None, json.dumps(valid), credits, location or None,
            demo_reel_url or None, notes, talent_id,
        ),
    )
    conn.commit()


def talent_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM talent").fetchone()[0]


def load_talent(conn: sqlite3.Connection) -> List[Talent]:
    """All talent as domain objects (for the matcher)."""
    return [talent_from_row(r) for r in conn.execute("SELECT * FROM talent ORDER BY name")]


# --------------------------------------------------------------------------- #
# Projects + assignments (supply side — Jon assigns; nothing auto-assigns)
# --------------------------------------------------------------------------- #
def insert_project(
    conn: sqlite3.Connection,
    opp_id: Optional[int],
    client: str,
    need: str,
    budget_min: Optional[float],
    budget_max: Optional[float],
    roles: List[str],
    deadline: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO projects
           (opp_id, client, need, budget_min, budget_max, deadline, status, roles, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            opp_id, client, need, budget_min, budget_max, deadline, "Active",
            json.dumps(roles), datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def project_for_opp(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM projects WHERE opp_id = ? LIMIT 1", (opp_id,)
    ).fetchone()


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def list_projects(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM assignments a WHERE a.project_id = p.id) AS assigned
           FROM projects p ORDER BY p.created_at DESC"""
    ).fetchall()


def update_project_status(conn: sqlite3.Connection, project_id: int, status: str) -> None:
    if status not in PROJECT_STATES:
        raise ValueError(f"Unknown project status {status!r}")
    conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
    conn.commit()


def add_assignment(
    conn: sqlite3.Connection, project_id: int, role: str, talent_id: int
) -> None:
    """Assign a creator to a role. Called only from the explicit Assign action."""
    conn.execute(
        """INSERT INTO assignments (project_id, role, talent_id, created_at)
           VALUES (?,?,?,?)""",
        (project_id, role, talent_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def remove_assignment(conn: sqlite3.Connection, assignment_id: int) -> None:
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    conn.commit()


def list_assignments(conn: sqlite3.Connection, project_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT a.*, t.name AS talent_name, t.email AS talent_email
           FROM assignments a LEFT JOIN talent t ON a.talent_id = t.id
           WHERE a.project_id = ? ORDER BY a.role, a.created_at""",
        (project_id,),
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


def strategic_spotlight(conn: sqlite3.Connection, limit: int = 5) -> List[sqlite3.Row]:
    """Small-but-strategic opportunities: high strategic value, modest budget.

    This is the CMO's headline — the '$2k agency beats $10k municipal' surface.
    """
    return conn.execute(
        """
        SELECT * FROM opportunities
        WHERE qualified = 1
          AND strategic_value >= 65
          AND (COALESCE(budget_max, budget_min, 0) < 5000 OR budget_min IS NULL)
        ORDER BY strategic_value DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


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
